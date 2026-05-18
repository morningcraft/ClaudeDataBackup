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
    """返回可运行 daemon 的可执行文件路径。

    打包 .app 模式：直接用 .app 的 bootloader（它知道如何从 .pyz 加载模块），
    配合 --daemon 参数让 run_gui.py 进入 daemon 模式而非打开 GUI。
    macOS 通知按 argv[0] 文件名显示来源。

    开发模式：找系统 python + run_daemon.py。
    """
    exe = sys.executable
    is_bootloader = ".app/Contents/MacOS/" in exe

    if is_bootloader:
        # 打包模式：直接用 bootloader，创建命名 symlink
        real_exe = exe
    else:
        # 开发模式：找可用 python
        import subprocess as _sp

        def _can_run(p: str) -> bool:
            try:
                return _sp.run(
                    [p, "-c", "import sys; print(sys.version)"],
                    capture_output=True, timeout=10,
                ).returncode == 0
            except Exception:
                return False

        candidates = ["/opt/homebrew/bin/python3", "/usr/bin/python3"]
        real_exe = None
        for c in candidates:
            if os.path.isfile(c) and _can_run(c):
                real_exe = c
                break
        if not real_exe:
            real_exe = exe
            log.warning("未找到可用 Python，回退到 sys.executable: %s", real_exe)

    # 创建命名 symlink，macOS 按 argv[0] 文件名显示通知来源
    link_path = CONFIG_DIR / "ClaudeDataBackupDaemon"
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if link_path.is_symlink():
            if os.readlink(str(link_path)) != real_exe:
                link_path.unlink()
                os.symlink(real_exe, str(link_path))
        else:
            if link_path.exists():
                link_path.unlink()
            os.symlink(real_exe, str(link_path))
    except OSError:
        return real_exe

    return str(link_path)


def _daemon_script() -> str:
    """返回 daemon 入口参数。

    打包模式：用 --daemon 参数让 run_gui.py 进入 daemon 模式。
    开发模式：用 run_daemon.py 脚本。
    """
    exe = sys.executable
    if ".app/Contents/MacOS/" in exe:
        # 打包模式：用 --daemon 参数
        return "--daemon"

    # 开发模式：找 run_daemon.py
    dev_script = Path(__file__).resolve().parent.parent.parent / "run_daemon.py"
    if dev_script.is_file():
        return str(dev_script)
    return str(Path.home() / "dev" / "claudeDataBackup" / "run_daemon.py")


def _daemon_plist_xml() -> str:
    """生成 daemon 的 launchd plist。

    打包模式：bootloader + --daemon（复用 .app 的模块加载能力）。
    开发模式：python + run_daemon.py。
    ProgramArguments[0] 用 ClaudeDataBackupDaemon symlink 显示通知来源。
    """
    python = _daemon_python()
    script = _daemon_script()
    stdout = str(LOG_DIR / "daemon.log")
    stderr = str(LOG_DIR / "daemon.err")

    if script == "--daemon":
        # 打包模式：[bootloader, --daemon]
        args_xml = f"""
        <string>{python}</string>
        <string>--daemon</string>"""
    else:
        # 开发模式：[python, run_daemon.py]
        args_xml = f"""
        <string>{python}</string>
        <string>{script}</string>"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>{args_xml}
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
