"""Windows 自动备份执行层。

Task Scheduler 管理 + 守护进程生命周期。
daemon 进程由 autobackup_daemon.py 实现。
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

from .log import get_logger
from .paths import detect_platform
from .autobackup_daemon import is_daemon_running, stop_daemon, read_status

log = get_logger(__name__)

TASK_NAME = "ClaudeDataBackup AutoBackup Daemon"


def install(config, interval_hours: int = 24) -> bool:
    """创建 Task Scheduler 任务启动 daemon。"""
    if detect_platform() != "win":
        log.warning("install 仅支持 Windows")
        return False
    if not config.enabled:
        return False

    python = sys.executable
    try:
        # 停止旧 daemon
        stop_daemon()
        subprocess.run(
            ["schtasks", "/Delete", "/F", "/TN", TASK_NAME],
            capture_output=True,
        )

        # daemon 入口脚本
        script = Path(__file__).resolve().parent.parent.parent / "run_daemon.py"
        daemon_cmd = f'"{python}" "{script}"'

        # 创建新任务：登录时启动 daemon
        subprocess.run(
            [
                "schtasks", "/Create", "/F",
                "/TN", TASK_NAME,
                "/TR", daemon_cmd,
                "/SC", "ONLOGON",
                "/RL", "LIMITED",
                "/DELAY", "0001:00",
            ],
            capture_output=True, text=True, check=True,
        )
        # 立即启动
        subprocess.run(
            ["schtasks", "/Run", "/TN", TASK_NAME],
            capture_output=True,
        )
        log.info("Task Scheduler daemon 已安装: %s", TASK_NAME)
        return True
    except subprocess.CalledProcessError as e:
        log.error("schtasks 失败: %s", e.stderr)
        return False


def uninstall() -> bool:
    """删除 Task Scheduler 任务 + 停止 daemon。"""
    if detect_platform() != "win":
        return False
    stop_daemon()
    try:
        subprocess.run(
            ["schtasks", "/Delete", "/F", "/TN", TASK_NAME],
            capture_output=True,
        )
        log.info("已删除 Task Scheduler 任务: %s", TASK_NAME)
        return True
    except Exception:
        return False


def status() -> dict:
    """返回当前安装状态。"""
    result: dict = {
        "platform": "win",
        "daemon_installed": False,
        "daemon_running": is_daemon_running(),
    }
    try:
        proc = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME],
            capture_output=True,
        )
        result["daemon_installed"] = proc.returncode == 0
    except Exception:
        pass
    st = read_status()
    if st:
        result.update(st)
    return result
