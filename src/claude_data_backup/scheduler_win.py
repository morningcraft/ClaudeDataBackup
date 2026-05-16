"""Windows 自动备份执行层。

- Task Scheduler 任务管理（schtasks.exe）
- Claude Desktop 进程监听（启动/关闭检测）
- 系统唤醒检测
- Windows 通知
"""
from __future__ import annotations
import os
import subprocess
import sys
import time
from pathlib import Path

from .i18n import t as _
from .log import get_logger
from .paths import detect_platform
from .notifier import notify_backup_result

log = get_logger(__name__)

TASK_NAME = "ClaudeDataBackup Auto Backup"
WATCHER_TASK_NAME = "ClaudeDataBackup Watcher"


def _python_cmd() -> str:
    """构建执行调度备份的命令。"""
    python = sys.executable
    return f'"{python}" -m claude_data_backup.main --schedule run'


def _python_watcher_cmd() -> str:
    """构建 watcher 的命令。"""
    python = sys.executable
    return f'"{python}" -m claude_data_backup.scheduler_win --watch'


def _schtasks(*args, check: bool = True) -> subprocess.CompletedProcess:
    """执行 schtasks 命令。"""
    return subprocess.run(
        ["schtasks"] + list(args),
        capture_output=True, text=True,
        check=check,
    )


# ─── Task Scheduler 管理 ──────────────────────────────

def install(config, interval_hours: int = 24) -> bool:
    """创建 Windows Task Scheduler 任务。

    两个任务:
    - 定时调度：每隔 interval_hours 触发
    - 后台 watcher：登录时启动，持续运行
    """
    if detect_platform() != "win":
        log.warning("调度器安装仅支持 Windows")
        return False

    try:
        # 主调度任务
        _schtasks(
            "/Create", "/F",
            "/TN", TASK_NAME,
            "/TR", _python_cmd(),
            "/SC", "HOURLY",
            "/MO", str(max(interval_hours, 1)),
            "/RL", "LIMITED",
            "/DELAY", "0001:00",
            check=False,
        )
        log.info("Task Scheduler 任务已创建: %s", TASK_NAME)

        # watcher 任务（条件触发用）
        if (config.condition_triggers.on_claude_start
                or config.condition_triggers.on_claude_close
                or config.condition_triggers.on_system_wake):
            _schtasks(
                "/Create", "/F",
                "/TN", WATCHER_TASK_NAME,
                "/TR", _python_watcher_cmd(),
                "/SC", "ONLOGON",
                "/RL", "LIMITED",
                "/DELAY", "0001:00",
                check=False,
            )
            log.info("Task Scheduler 任务已创建: %s", WATCHER_TASK_NAME)

        return True
    except subprocess.CalledProcessError as e:
        log.error("schtasks 操作失败: %s", e.stderr)
        return False


def uninstall() -> bool:
    """删除 Task Scheduler 任务。"""
    if detect_platform() != "win":
        return False

    success = True
    for name in [TASK_NAME, WATCHER_TASK_NAME]:
        try:
            _schtasks("/Delete", "/F", "/TN", name, check=False)
            log.info("已删除任务: %s", name)
        except Exception:
            success = False
    return success


def status() -> dict:
    """返回当前安装状态。"""
    result: dict = {
        "platform": detect_platform(),
        "scheduler_installed": False,
        "watcher_installed": False,
    }
    if result["platform"] != "win":
        return result

    try:
        proc = _schtasks("/Query", "/TN", TASK_NAME, check=False)
        result["scheduler_installed"] = proc.returncode == 0
    except Exception:
        pass

    try:
        proc = _schtasks("/Query", "/TN", WATCHER_TASK_NAME, check=False)
        result["watcher_installed"] = proc.returncode == 0
    except Exception:
        pass

    return result


# ─── 进程监听（watcher 模式）─────────────────────────

def _check_claude_running() -> bool:
    """检查 Claude Desktop 是否在运行。"""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq claude.exe", "/NH"],
            capture_output=True, text=True,
        )
        return "claude.exe" in result.stdout.lower()
    except Exception:
        return False


def run_watcher():
    """后台监听 Claude Desktop 进程启动/关闭。

    以 --watch 参数启动时进入此模式。
    """
    from .scheduler import (
        ScheduleConfig,
        run_scheduled_backup,
        schedule_config_path,
    )

    log.info(_("schedule.watcher_started"))
    was_running = _check_claude_running()

    while True:
        try:
            time.sleep(5)
            is_running = _check_claude_running()

            config = ScheduleConfig.load(schedule_config_path())
            if not config.enabled:
                continue

            if is_running and not was_running:
                result = run_scheduled_backup(config, "claude_start")
                if result["status"] == "ok":
                    notify_backup_result(True, _count_from_stats(result))

            elif not is_running and was_running:
                result = run_scheduled_backup(config, "claude_close")
                if result["status"] == "ok":
                    notify_backup_result(True, _count_from_stats(result))

            was_running = is_running
        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error("watcher 异常: %s", e)
            time.sleep(5)

    log.info(_("schedule.watcher_stopped"))


def _count_from_stats(result: dict) -> int:
    try:
        stats = result.get("stats", {})
        return sum(stats.get(m, {}).get("count", 0)
                   for m in ("mode_a", "mode_b", "mode_c"))
    except Exception:
        return 0


if __name__ == "__main__":
    if "--watch" in sys.argv:
        run_watcher()
    else:
        print("scheduler_win.py: 请通过 main.py --schedule 管理")
