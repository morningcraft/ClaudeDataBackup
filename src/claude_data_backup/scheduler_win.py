"""Windows 自动备份执行层。

注册表 Run key 管理（登录自启）+ 守护进程生命周期。
daemon 进程由 autobackup_daemon.py 实现。

注意：schtasks /Create /SC ONLOGON 在 Windows 11 上需要管理员权限，
因此改用 HKCU Run 注册表键实现用户级登录自启。
"""
from __future__ import annotations
import os
import subprocess
import sys
import winreg
from pathlib import Path

from .log import get_logger
from .paths import detect_platform
from .autobackup_daemon import is_daemon_running, stop_daemon, read_status

log = get_logger(__name__)

REG_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_APP_NAME = "ClaudeDataBackup AutoBackup"


def _find_real_python() -> str:
    """找到真正的 Python 解释器（不能是 PyInstaller bootloader）。

    打包后 sys.executable 指向 ClaudeDataBackup.exe（bootloader），
    用它跑 run_daemon.py 会重新打开 GUI 窗口。
    """
    def _is_bootloader(p: str) -> bool:
        """PyInstaller bootloader 路径特征：包含 _internal 或 dist 目录。"""
        lower = p.lower()
        return "_internal" in lower or "\\dist\\" in lower

    def _works(p: str) -> bool:
        if _is_bootloader(p):
            return False
        try:
            return subprocess.run(
                [p, "-c", "import sys; print(sys.version)"],
                capture_output=True, timeout=10,
            ).returncode == 0
        except Exception:
            return False

    candidates = [sys.executable]

    # 如果当前是 bootloader，向上找 .venv
    if _is_bootloader(sys.executable):
        exe_path = Path(sys.executable)
        for _ in range(6):
            exe_path = exe_path.parent
            for name in ("python.exe", "python3.exe", "python"):
                candidate = exe_path / ".venv" / "Scripts" / name
                if candidate.is_file():
                    candidates.insert(0, str(candidate))
                    break
            # 也试 venv 直接在上级目录
            for name in ("python.exe", "python3.exe", "python"):
                candidate = exe_path / "Scripts" / name
                if candidate.is_file():
                    candidates.insert(0, str(candidate))
                    break

    # 系统 PATH 中的 python
    for name in ("python.exe", "python3.exe", "py.exe"):
        candidates.append(name)

    for c in candidates:
        if _works(c):
            # 优先用 pythonw.exe（无窗口），避免 daemon 弹出黑色控制台
            if c.lower().endswith("python.exe"):
                w_path = c[:-len("python.exe")] + "pythonw.exe"
                if os.path.isfile(w_path):
                    c = w_path
            log.info("找到真实 Python: %s", c)
            return c

    # fallback
    log.warning("未找到可用 Python，回退到 sys.executable")
    return sys.executable


# 缓存结果，避免重复查找
_real_python: str | None = None


def _get_python() -> str:
    global _real_python
    if _real_python is None:
        _real_python = _find_real_python()
    return _real_python


def _get_daemon_cmd() -> str:
    """构造 daemon 启动命令（用于注册表 Run key）。"""
    python = _get_python()
    return f'"{python}" -c "from claude_data_backup.autobackup_daemon import run_daemon; run_daemon()"'


def _install_logon_registry() -> bool:
    """写入注册表 Run key 实现登录自启（不需要管理员权限）。"""
    try:
        cmd = _get_daemon_cmd()
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY, 0,
                             winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, REG_APP_NAME, 0, winreg.REG_SZ, cmd)
        winreg.CloseKey(key)
        log.info("注册表 Run key 已写入: %s", REG_APP_NAME)
        return True
    except Exception as e:
        log.error("注册表写入失败: %s", e)
        return False


def _uninstall_logon_registry() -> bool:
    """删除注册表 Run key。"""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY, 0,
                             winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, REG_APP_NAME)
        winreg.CloseKey(key)
        log.info("注册表 Run key 已删除: %s", REG_APP_NAME)
        return True
    except FileNotFoundError:
        return True  # 已经不存在
    except Exception as e:
        log.error("注册表删除失败: %s", e)
        return False


def _is_logon_registry_set() -> bool:
    """检查注册表 Run key 是否存在。"""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY, 0,
                             winreg.KEY_READ)
        winreg.QueryValueEx(key, REG_APP_NAME)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


def install(config, interval_minutes: int = 1440) -> bool:
    """安装自动备份：注册表登录自启 + 立即启动 daemon。"""
    if detect_platform() != "win":
        log.warning("install 仅支持 Windows")
        return False
    if not config.enabled:
        return False

    try:
        # 停止旧 daemon
        stop_daemon()

        # 注册表 Run key（登录自启）
        if not _install_logon_registry():
            return False

        # 立即启动 daemon（子进程，不依赖 main.py 生命周期）
        python = _get_python()
        subprocess.Popen(
            [python, "-c",
             "from claude_data_backup.autobackup_daemon import run_daemon; run_daemon()"],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
        )
        log.info("daemon 已作为子进程启动: %s", python)
        return True
    except Exception as e:
        log.error("安装失败: %s", e)
        return False


def uninstall() -> bool:
    """卸载自动备份：删除注册表键 + 停止 daemon。"""
    if detect_platform() != "win":
        return False
    stop_daemon()
    _uninstall_logon_registry()
    log.info("自动备份已卸载")
    return True


def status() -> dict:
    """返回当前安装状态。"""
    result: dict = {
        "platform": "win",
        "daemon_installed": _is_logon_registry_set(),
        "daemon_running": is_daemon_running(),
    }
    st = read_status()
    if st:
        result.update(st)
    return result
