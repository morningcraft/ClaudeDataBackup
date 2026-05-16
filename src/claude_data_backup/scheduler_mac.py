"""macOS 自动备份执行层。

- launchd plist 管理（~/Library/LaunchAgents/com.claudedatabackup.plist）
- Claude Desktop 进程监听（启动/关闭检测）
- 系统唤醒检测
- macOS 系统通知
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

PLIST_NAME = "com.claudedatabackup.plist"
PLIST_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = PLIST_DIR / PLIST_NAME

# watcher 用单独的 label
WATCHER_LABEL = "com.claudedatabackup.watcher"
WATCHER_PATH = PLIST_DIR / "com.claudedatabackup.watcher.plist"

SCRIPT = "python3"


def _python_cmd() -> str:
    """构建执行调度备份的 shell 命令。"""
    python = sys.executable
    module = "claude_data_backup.main"
    return f'{python} -m {module} --schedule run'


def _python_watcher_cmd() -> str:
    """构建 watcher 进程的 shell 命令。"""
    python = sys.executable
    module = "claude_data_backup.scheduler_mac"
    return f'{python} -m {module} --watch'


def _launchd_plist_xml(interval_seconds: int) -> str:
    """生成定时调度的 launchd plist XML。"""
    cmd = _python_cmd()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.claudedatabackup</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/sh</string>
        <string>-c</string>
        <string>{cmd}</string>
    </array>
    <key>StartInterval</key>
    <integer>{interval_seconds}</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{Path.home() / '.claude-data-backup' / 'logs' / 'scheduler.log'}</string>
    <key>StandardErrorPath</key>
    <string>{Path.home() / '.claude-data-backup' / 'logs' / 'scheduler.err'}</string>
</dict>
</plist>"""


def _watcher_plist_xml() -> str:
    """生成后台 watcher 的 launchd plist XML。"""
    cmd = _python_watcher_cmd()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{WATCHER_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/sh</string>
        <string>-c</string>
        <string>{cmd}</string>
    </array>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{Path.home() / '.claude-data-backup' / 'logs' / 'watcher.log'}</string>
    <key>StandardErrorPath</key>
    <string>{Path.home() / '.claude-data-backup' / 'logs' / 'watcher.err'}</string>
</dict>
</plist>"""


# ─── launchd 管理 ─────────────────────────────────────

def install(config, interval_seconds: int = 3600) -> bool:
    """安装 launchd plist 并加载。

    创建两个 agent:
    - com.claudedatabackup: 定时调度（StartInterval）
    - com.claudedatabackup.watcher: 后台进程监听（KeepAlive）
    """
    if detect_platform() != "mac":
        log.warning("调度器安装仅支持 macOS")
        return False

    try:
        PLIST_DIR.mkdir(parents=True, exist_ok=True)
        uid = os.getuid()

        # 主调度 plist
        plist_xml = _launchd_plist_xml(interval_seconds)
        PLIST_PATH.write_text(plist_xml, encoding="utf-8")
        # 先卸载旧版（可能不存在，忽略错误）
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{PLIST_NAME}"],
                       capture_output=True)
        result = subprocess.run(
            ["launchctl", "bootstrap", f"gui/{uid}", str(PLIST_PATH)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            # bootstrap 可能因为已加载而报错，用 enable + kickstart
            subprocess.run(["launchctl", "enable", f"gui/{uid}/{PLIST_NAME}"],
                           capture_output=True)
            subprocess.run(["launchctl", "kickstart", f"gui/{uid}/{PLIST_NAME}"],
                           capture_output=True)
        log.info("调度器已安装: %s (间隔 %ss)", PLIST_PATH, interval_seconds)

        # watcher plist（如果配置了条件触发）
        if (config.condition_triggers.on_claude_start
                or config.condition_triggers.on_claude_close
                or config.condition_triggers.on_system_wake):
            watcher_xml = _watcher_plist_xml()
            WATCHER_PATH.write_text(watcher_xml, encoding="utf-8")
            subprocess.run(["launchctl", "bootout", f"gui/{uid}/{WATCHER_LABEL}"],
                           capture_output=True)
            result = subprocess.run(
                ["launchctl", "bootstrap", f"gui/{uid}", str(WATCHER_PATH)],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                subprocess.run(["launchctl", "enable", f"gui/{uid}/{WATCHER_LABEL}"],
                               capture_output=True)
                subprocess.run(["launchctl", "kickstart", f"gui/{uid}/{WATCHER_LABEL}"],
                               capture_output=True)
            log.info("watcher 已安装: %s", WATCHER_PATH)

        return True
    except Exception as e:
        log.error("launchd 操作失败: %s", e)
        return False


def uninstall() -> bool:
    """卸载 launchd plist。"""
    if detect_platform() != "mac":
        return False

    success = True
    for label, path in [
        (PLIST_NAME, PLIST_PATH),
        (WATCHER_LABEL, WATCHER_PATH),
    ]:
        try:
            subprocess.run(
                ["launchctl", "bootout", f"gui/{os.getuid()}/{label}"],
                capture_output=True,
            )
        except Exception:
            pass
        if path.is_file():
            path.unlink()
            log.info("已删除: %s", path)
        else:
            success = False
    return success


def status() -> dict:
    """返回当前安装状态。"""
    result: dict = {
        "platform": detect_platform(),
        "scheduler_installed": False,
        "watcher_installed": False,
    }
    if result["platform"] != "mac":
        return result

    # macOS 14+ launchctl print 不可靠，改用 launchctl list
    try:
        proc = subprocess.run(
            ["launchctl", "list", PLIST_NAME],
            capture_output=True, text=True,
        )
        result["scheduler_installed"] = proc.returncode == 0
    except Exception:
        pass

    try:
        proc = subprocess.run(
            ["launchctl", "list", WATCHER_LABEL],
            capture_output=True, text=True,
        )
        result["watcher_installed"] = proc.returncode == 0
    except Exception:
        pass

    return result


# ─── 进程监听（watcher 模式）─────────────────────────

def _check_claude_running() -> bool:
    """检查 Claude Desktop 是否在运行。"""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "Claude.app/Contents/MacOS/Claude"],
            capture_output=True, text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def run_watcher():
    """后台监听 Claude Desktop 进程启动/关闭 + 系统唤醒。

    以 --watch 参数启动时进入此模式。
    持续运行，每 3 秒轮询一次。
    """
    from .scheduler import (
        ScheduleConfig,
        evaluate_schedule,
        run_scheduled_backup,
        schedule_config_path,
    )

    log.info(_("schedule.watcher_started"))
    was_running = _check_claude_running()

    while True:
        try:
            time.sleep(3)
            is_running = _check_claude_running()

            config = ScheduleConfig.load(schedule_config_path())
            if not config.enabled:
                continue

            # Claude Desktop 启动
            if is_running and not was_running:
                result = run_scheduled_backup(config, "claude_start")
                if result["status"] == "ok":
                    notify_backup_result(True, _count_from_stats(result))

            # Claude Desktop 关闭
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
    """从备份结果提取对话总数。"""
    try:
        stats = result.get("stats", {})
        count = 0
        for mode in ("mode_a", "mode_b", "mode_c"):
            count += stats.get(mode, {}).get("count", 0)
        return count
    except Exception:
        return 0


if __name__ == "__main__":
    import sys
    if "--watch" in sys.argv:
        run_watcher()
    else:
        print("scheduler_mac.py: 请通过 main.py --schedule 管理")
