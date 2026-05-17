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


def _daemon_python() -> str:
    """返回可运行 daemon 的有效 Python 路径。

    优先用当前 python。如果是 PyInstaller .app（不支持模块导入），
    则退到项目 .venv，最后尝试系统 python3。
    """
    import subprocess as _sp

    def _works(p: str) -> bool:
        try:
            return _sp.run(
                [p, "-c", "import claude_data_backup.autobackup_daemon"],
                capture_output=True, timeout=10,
            ).returncode == 0
        except Exception:
            return False

    if _works(sys.executable):
        return sys.executable

    # PyInstaller .app 场景 —— 在 .app 同级或上级找 .venv
    exe_path = Path(sys.executable)
    for _ in range(6):
        exe_path = exe_path.parent
        candidate = exe_path / ".venv" / "bin" / "python3"
        if candidate.is_file() and _works(str(candidate)):
            return str(candidate)

    for p in ["/usr/bin/python3", "/opt/homebrew/bin/python3"]:
        if os.path.isfile(p) and _works(p):
            return p

    return sys.executable


def _daemon_script() -> str:
    """返回 run_daemon.py 的绝对路径。"""
    # run_daemon.py 在项目根目录，和 src/ 同级
    script = Path(__file__).resolve().parent.parent.parent / "run_daemon.py"
    if script.is_file():
        return str(script)
    return str(Path.home() / "dev" / "claudeDataBackup" / "run_daemon.py")


def _daemon_plist_xml() -> str:
    """生成 daemon 的 launchd plist。

    关键设计：
    - ProgramArguments 是数组，直接调 Python + run_daemon.py 脚本，
      不经过 /bin/sh，不依赖 -m（PyInstaller 不支持 -m）
    - KeepAlive + RunAtLoad：登录即启动，崩溃自动重启
    - 内部定时器由 daemon 管理，launchd 只负责进程存活
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


def install(config, interval_seconds: int = 3600) -> bool:
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

        # 先停旧 daemon
        subprocess.run(
            ["launchctl", "bootout", f"gui/{uid}/{PLIST_LABEL}"],
            capture_output=True,
        )
        stop_daemon()

        # 写 plist 并加载
        PLIST_PATH.write_text(_daemon_plist_xml(), encoding="utf-8")
        result = subprocess.run(
            ["launchctl", "bootstrap", f"gui/{uid}", str(PLIST_PATH)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            # 可能已加载，enable + kickstart
            subprocess.run(
                ["launchctl", "enable", f"gui/{uid}/{PLIST_LABEL}"],
                capture_output=True,
            )
            subprocess.run(
                ["launchctl", "kickstart", f"gui/{uid}/{PLIST_LABEL}"],
                capture_output=True,
            )

        log.info("launchd daemon 已安装: %s → %s", PLIST_PATH, python)
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
