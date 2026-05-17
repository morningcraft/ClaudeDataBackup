"""自动备份守护进程（跨平台）。

常驻后台进程，负责：
- 内部定时器（基于 schedule.json 的 time_trigger）
- Claude Desktop 进程启动/关闭监听
- 调度评估 + 备份执行
- 系统通知
- 状态文件写盘供 GUI 读取

启动方式：
    python -m claude_data_backup.autobackup_daemon
    python -m claude_data_backup.autobackup_daemon --stop   # 优雅停止

不依赖 PyObjC / rumps——纯 headless。菜单栏图标留待后续。
"""
from __future__ import annotations
import json
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .log import get_logger
from .paths import detect_platform

log = get_logger(__name__)

PLATFORM = detect_platform()
CONFIG_DIR = Path.home() / ".claude-data-backup"
PID_FILE = CONFIG_DIR / "daemon.pid"
STATUS_FILE = CONFIG_DIR / "daemon_status.json"
CHECK_INTERVAL = 60          # 定时器检查间隔（秒）
CLAUDE_POLL_INTERVAL = 3     # Claude 进程轮询间隔（秒）


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def write_status(**kwargs):
    """将当前状态写盘。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "running": True,
        "pid": os.getpid(),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        **kwargs,
    }
    STATUS_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_status() -> Optional[dict]:
    """读取上次 daemon 写盘的状态。"""
    if not STATUS_FILE.is_file():
        return None
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def is_daemon_running() -> bool:
    """检查 daemon 是否在运行。"""
    if not PID_FILE.is_file():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
        return _pid_exists(pid)
    except Exception:
        return False


def stop_daemon():
    """停止正在运行的 daemon。"""
    if not PID_FILE.is_file():
        return
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGTERM)
    except Exception:
        pass
    PID_FILE.unlink(missing_ok=True)
    STATUS_FILE.unlink(missing_ok=True)


# ─── 平台特定：进程检测 ──────────────────────────────

def _check_claude_running() -> bool:
    if PLATFORM == "mac":
        return _check_claude_running_mac()
    elif PLATFORM == "win":
        return _check_claude_running_win()
    return False


def _check_claude_running_mac() -> bool:
    import subprocess
    try:
        result = subprocess.run(
            ["pgrep", "-f", "/Applications/Claude.app/Contents/MacOS/Claude"],
            capture_output=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def _check_claude_running_win() -> bool:
    import subprocess
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq claude.exe", "/NH"],
            capture_output=True, text=True,
        )
        return "claude.exe" in result.stdout.lower()
    except Exception:
        return False


# ─── 主循环 ──────────────────────────────────────────

def run_daemon():
    """启动守护进程主循环。"""
    from .scheduler import (
        ScheduleConfig,
        evaluate_schedule,
        run_scheduled_backup,
        schedule_config_path,
    )
    from .notifier import notify_backup_result

    # PID 文件
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    log.info("AutoBackup daemon 启动 (PID %s)", os.getpid())

    # 状态初始化
    write_status(
        last_check=None,
        last_backup=None,
        claude_running=_check_claude_running(),
        trigger_types=[],
    )

    # 注册 SIGTERM handler
    stop_requested = False

    def _on_sigterm(signum, frame):
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGTERM, _on_sigterm)

    last_time_check = 0.0
    was_claude_running = _check_claude_running()
    last_claude_check = time.time()
    loop_interval = min(CHECK_INTERVAL, CLAUDE_POLL_INTERVAL)

    while not stop_requested:
        try:
            now = time.time()
            config = ScheduleConfig.load(schedule_config_path())

            # 更新状态（GUI 读取用）
            trigger_types = []
            if config.time_trigger.type:
                trigger_types.append("time")
            if config.condition_triggers.on_claude_close:
                trigger_types.append("claude_close")
            if config.condition_triggers.on_claude_start:
                trigger_types.append("claude_start")

            write_status(
                last_check=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                trigger_types=trigger_types,
                claude_running=was_claude_running,
                schedule_enabled=config.enabled,
                interval_hours=config.time_trigger.interval_hours,
                min_interval_hours=config.min_interval_hours,
            )

            if not config.enabled:
                time.sleep(loop_interval)
                continue

            # ── 定时检查 ──
            if now - last_time_check >= CHECK_INTERVAL:
                last_time_check = now
                result = run_scheduled_backup(config, "time")
                if result["status"] == "ok":
                    stats = result.get("stats", {})
                    count = sum(
                        stats.get(f"mode_{m}", {}).get("count", 0)
                        for m in "abc"
                    )
                    notify_backup_result(True, count)
                    write_status(
                        last_backup=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        last_backup_status="ok",
                        last_backup_count=count,
                    )
                elif result["status"] == "error":
                    notify_backup_result(False, 0)
                    write_status(
                        last_backup=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        last_backup_status="error",
                    )

            # ── Claude 进程监听 ──
            if config.condition_triggers.on_claude_start \
                    or config.condition_triggers.on_claude_close:
                if now - last_claude_check >= CLAUDE_POLL_INTERVAL:
                    last_claude_check = now
                    is_running = _check_claude_running()

                    if is_running and not was_claude_running:
                        result = run_scheduled_backup(config, "claude_start")
                        if result["status"] == "ok":
                            notify_backup_result(True, _count(result))
                    elif not is_running and was_claude_running:
                        result = run_scheduled_backup(config, "claude_close")
                        if result["status"] == "ok":
                            notify_backup_result(True, _count(result))

                    was_claude_running = is_running

            time.sleep(loop_interval)

        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error("daemon 循环异常: %s", e)
            time.sleep(5)

    # 清理
    write_status(running=False)
    PID_FILE.unlink(missing_ok=True)
    STATUS_FILE.unlink(missing_ok=True)
    log.info("AutoBackup daemon 已退出")


def _count(result: dict) -> int:
    try:
        stats = result.get("stats", {})
        return sum(stats.get(f"mode_{m}", {}).get("count", 0) for m in "abc")
    except Exception:
        return 0


if __name__ == "__main__":
    if "--stop" in sys.argv:
        stop_daemon()
    else:
        run_daemon()
