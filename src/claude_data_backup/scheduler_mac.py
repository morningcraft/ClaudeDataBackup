"""macOS 自动备份执行层。

launchd plist 管理 + 守护进程生命周期。
daemon 进程由 autobackup_daemon.py 实现（headless，常驻，内部定时器）。
"""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

from .log import get_logger
from .paths import detect_platform
from .autobackup_daemon import is_daemon_running, stop_daemon, read_status

log = get_logger(__name__)

PLIST_LABEL = "com.claudedatabackup.daemon"
PLIST_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = PLIST_DIR / f"{PLIST_LABEL}.plist"
LOG_DIR = Path.home() / ".claude-data-backup" / "logs"
CONFIG_DIR = Path.home() / ".claude-data-backup"


def _daemon_python() -> str:
    """返回可运行 daemon 的 symlink 路径。

    创建一个叫 ClaudeDataBackupDaemon 的 symlink 指向 python，
    macOS 后台活动通知会显示 "ClaudeDataBackupDaemon" 而非 "Python3"。

    关键约束：不能用 PyInstaller bootloader——它不认识我们的 run_daemon.py，
    会回退到默认入口 run_gui.py 导致无限打开 GUI 窗口。
    """
    import subprocess as _sp

    def _is_bootloader(p: str) -> bool:
        """PyInstaller bootloader 路径特征：在 .app/Contents/MacOS/ 下。"""
        return ".app/Contents/MacOS/" in p

    def _works(p: str) -> bool:
        if _is_bootloader(p):
            return False  # bootloader 能跑 -c 但绝不能当 python 用
        try:
            return _sp.run(
                [p, "-c", "import claude_data_backup.autobackup_daemon"],
                capture_output=True, timeout=10,
            ).returncode == 0
        except Exception:
            return False

    # 找真实 python（绝对不能是 PyInstaller bootloader）
    candidates = [sys.executable]

    # 如果当前是 bootloader，找 .venv
    if _is_bootloader(sys.executable):
        exe_path = Path(sys.executable)
        for _ in range(6):
            exe_path = exe_path.parent
            candidate = exe_path / ".venv" / "bin" / "python3"
            if candidate.is_file():
                candidates.insert(0, str(candidate))
                break

    # 系统 python
    candidates.extend(["/opt/homebrew/bin/python3", "/usr/bin/python3"])

    real_python = None
    for c in candidates:
        if os.path.isfile(c) and _works(c):
            real_python = c
            break

    if not real_python:
        # 最后的 fallback（不推荐，但总比没装好）
        real_python = sys.executable

    # 创建命名 symlink，macOS 按 argv[0] 文件名显示通知来源
    link_path = CONFIG_DIR / "ClaudeDataBackupDaemon"
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if link_path.is_symlink():
            current_target = os.readlink(str(link_path))
            if current_target != real_python:
                link_path.unlink()
                os.symlink(real_python, str(link_path))
        else:
            if link_path.exists():
                link_path.unlink()
            os.symlink(real_python, str(link_path))
    except OSError:
        return real_python

    return str(link_path)


def _daemon_script() -> str:
    """返回 run_daemon.py 的绝对路径。"""
    script = Path(__file__).resolve().parent.parent.parent / "run_daemon.py"
    if script.is_file():
        return str(script)
    return str(Path.home() / "dev" / "claudeDataBackup" / "run_daemon.py")


def _daemon_plist_xml() -> str:
    """生成 daemon 的 launchd plist。

    ProgramArguments[0] 用 ClaudeDataBackupDaemon symlink，
    macOS 通知显示 "ClaudeDataBackupDaemon" 而非 "Python3"。
    不经过 /bin/sh，直接数组传参。
    """
    python = _daemon_python()
    script = _daemon_script()
    stdout = str(LOG_DIR / "daemon.log")
    stderr = str(LOG_DIR / "daemon.err")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>{script}</string>
    </array>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{stdout}</string>
    <key>StandardErrorPath</key>
    <string>{stderr}</string>
    <key>ProcessType</key>
    <string>Background</string>
</dict>
</plist>"""


def install(config, interval_minutes: int = 1440) -> bool:
    """安装 launchd plist 并启动 daemon。"""
    if detect_platform() != "mac":
        log.warning("install 仅支持 macOS")
        return False

    if not config.enabled:
        return False

    try:
        PLIST_DIR.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        uid = os.getuid()

        subprocess.run(
            ["launchctl", "bootout", f"gui/{uid}/{PLIST_LABEL}"],
            capture_output=True,
        )
        stop_daemon()

        PLIST_PATH.write_text(_daemon_plist_xml(), encoding="utf-8")
        result = subprocess.run(
            ["launchctl", "bootstrap", f"gui/{uid}", str(PLIST_PATH)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            subprocess.run(
                ["launchctl", "enable", f"gui/{uid}/{PLIST_LABEL}"],
                capture_output=True,
            )
            subprocess.run(
                ["launchctl", "kickstart", f"gui/{uid}/{PLIST_LABEL}"],
                capture_output=True,
            )

        log.info("launchd daemon 已安装: %s", PLIST_PATH)
        return True
    except Exception as e:
        log.error("launchd 安装失败: %s", e)
        return False


def uninstall() -> bool:
    """卸载 launchd plist + 停止 daemon。"""
    if detect_platform() != "mac":
        return False

    try:
        uid = os.getuid()
        subprocess.run(
            ["launchctl", "bootout", f"gui/{uid}/{PLIST_LABEL}"],
            capture_output=True,
        )
    except Exception:
        pass

    stop_daemon()

    if PLIST_PATH.is_file():
        PLIST_PATH.unlink()
        log.info("已删除: %s", PLIST_PATH)

    # 清理 daemon symlink
    symlink = CONFIG_DIR / "ClaudeDataBackupDaemon"
    symlink.unlink(missing_ok=True)

    return True


def status() -> dict:
    """返回当前安装状态。"""
    result: dict = {
        "platform": "mac",
        "daemon_installed": PLIST_PATH.is_file() or is_daemon_running(),
        "daemon_running": is_daemon_running(),
    }
    st = read_status()
    if st:
        result.update(st)
    return result
