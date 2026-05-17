"""自动备份调度引擎（跨平台核心）。

纯逻辑模块——不 import 任何平台特定库。
负责：配置读写、触发条件评估、备份执行包装。
"""
from __future__ import annotations
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Callable, Optional


# ─── 配置 dataclass ──────────────────────────────────

@dataclass
class TimeTrigger:
    """定时触发配置。"""
    type: str = "periodic"       # "periodic" | "daily" | "weekly" | "monthly"
    interval_minutes: int = 1440     # periodic 用
    days: Optional[list[int]] = None   # weekly: [1..7]=Mon..Sun; monthly: [1..31]
    time: Optional[str] = None   # "HH:MM" for daily/weekly/monthly


@dataclass
class ConditionTriggers:
    """条件触发开关。"""
    on_claude_start: bool = False
    on_claude_close: bool = False
    on_system_wake: bool = False


@dataclass
class ScheduleConfig:
    """自动备份调度配置。"""
    enabled: bool = False
    mode: str = "abc"
    backup_dir: str = "~/Documents/ClaudeDataBackup"
    time_trigger: TimeTrigger = field(default_factory=TimeTrigger)
    condition_triggers: ConditionTriggers = field(default_factory=ConditionTriggers)
    min_interval_minutes: int = 1
    notify_success: bool = True
    notify_failure: bool = True

    # ── JSON 序列化 ──

    def to_dict(self) -> dict:
        tt = {
            "type": self.time_trigger.type,
        }
        if self.time_trigger.type == "periodic":
            tt["interval_minutes"] = self.time_trigger.interval_minutes
        else:
            tt["days"] = self.time_trigger.days
            tt["time"] = self.time_trigger.time

        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "backup_dir": self.backup_dir,
            "time_trigger": tt,
            "condition_triggers": {
                "on_claude_start": self.condition_triggers.on_claude_start,
                "on_claude_close": self.condition_triggers.on_claude_close,
                "on_system_wake": self.condition_triggers.on_system_wake,
            },
            "min_interval_minutes": self.min_interval_minutes,
            "notify_success": self.notify_success,
            "notify_failure": self.notify_failure,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ScheduleConfig":
        tt_raw = d.get("time_trigger", {})
        time_trigger = TimeTrigger(
            type=tt_raw.get("type", "periodic"),
            # backward compat: old configs use interval_hours
            interval_minutes=tt_raw.get("interval_minutes",
                              tt_raw.get("interval_hours", 24) * 60),
            days=tt_raw.get("days"),
            time=tt_raw.get("time"),
        )

        ct_raw = d.get("condition_triggers", {})
        condition_triggers = ConditionTriggers(
            on_claude_start=ct_raw.get("on_claude_start", False),
            on_claude_close=ct_raw.get("on_claude_close", False),
            on_system_wake=ct_raw.get("on_system_wake", False),
        )

        return cls(
            enabled=d.get("enabled", False),
            mode=d.get("mode", "abc"),
            backup_dir=d.get("backup_dir", "~/Documents/ClaudeDataBackup"),
            time_trigger=time_trigger,
            condition_triggers=condition_triggers,
            min_interval_minutes=d.get("min_interval_minutes", 1),
            notify_success=d.get("notify_success", True),
            notify_failure=d.get("notify_failure", True),
        )

    @classmethod
    def load(cls, path: Path) -> "ScheduleConfig":
        if path.is_file():
            try:
                return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                pass
        return cls()

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# ─── 核心评估逻辑 ────────────────────────────────────

def get_last_backup_time(backup_dir: Path) -> Optional[float]:
    """从 manifest.json 读取 last_backup_time，转为 Unix timestamp。"""
    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        mf = json.loads(manifest_path.read_text(encoding="utf-8"))
        raw = mf.get("last_backup_time")
        if raw:
            # manifest 存的是 YYYY-MM-DD HH:MM:SS 字符串
            dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
            return dt.timestamp()
    except Exception:
        pass
    return None


def _match_time_trigger(tt: TimeTrigger) -> bool:
    """检查当前时间是否匹配 time_trigger。"""
    now = datetime.now()
    if tt.type == "periodic":
        return True  # periodic 由 launchd/Task Scheduler 间隔控制

    if tt.time:
        try:
            h, m = map(int, tt.time.split(":"))
            if now.hour != h or now.minute != m:
                return False
        except Exception:
            pass

    if tt.type == "daily":
        return True
    elif tt.type == "weekly":
        if tt.days:
            # Python weekday: 0=Mon → 1..7 mapping: +1
            today = (now.weekday() + 1) % 7 or 7
            return today in tt.days
    elif tt.type == "monthly":
        if tt.days:
            return now.day in tt.days

    return True


def evaluate_schedule(
    config: ScheduleConfig,
    trigger_reason: str,
    backup_dir: Path,
) -> tuple[bool, str]:
    """评估此时是否应执行备份。

    Args:
        config: 调度配置
        trigger_reason: "time" | "claude_start" | "claude_close" | "system_wake" | "manual"
        backup_dir: 备份目录（用于读 manifest 获取上次备份时间）

    Returns:
        (should_run, reason) —— reason 是中文/英文的状态说明
    """
    if not config.enabled:
        return False, "schedule.skipped_disabled"

    # 最小间隔检查（所有触发类型都受此约束，manual 除外）
    if trigger_reason != "manual" and config.min_interval_minutes > 0:
        last_time = get_last_backup_time(backup_dir)
        if last_time:
            elapsed = (time.time() - last_time) / 60.0
            if elapsed < config.min_interval_minutes:
                return False, "schedule.skipped_interval"

    # 按触发类型检查
    if trigger_reason == "time":
        if not _match_time_trigger(config.time_trigger):
            return False, "schedule.skipped_time"

    elif trigger_reason == "claude_start":
        if not config.condition_triggers.on_claude_start:
            return False, "schedule.skipped_condition"

    elif trigger_reason == "claude_close":
        if not config.condition_triggers.on_claude_close:
            return False, "schedule.skipped_condition"

    elif trigger_reason == "system_wake":
        if not config.condition_triggers.on_system_wake:
            return False, "schedule.skipped_condition"

    # manual 总是通过
    return True, ""


def get_next_run_time(config: ScheduleConfig) -> Optional[float]:
    """估算下次定时触发的时间（仅用于 GUI 展示）。"""
    if not config.enabled:
        return None

    tt = config.time_trigger
    now = datetime.now()

    if tt.type == "periodic":
        return time.time() + tt.interval_minutes * 60

    if tt.time:
        try:
            h, m = map(int, tt.time.split(":"))
            next_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if next_dt <= now:
                from datetime import timedelta
                if tt.type == "weekly" and tt.days:
                    # 找下一个匹配的 weekday
                    today_idx = (now.weekday() + 1) % 7 or 7
                    for offset in range(1, 8):
                        day = (today_idx + offset - 1) % 7 + 1
                        if day in tt.days:
                            next_dt = now.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=offset)
                            return next_dt.timestamp()
                    return None
                elif tt.type == "monthly" and tt.days:
                    for offset in range(1, 32):
                        candidate = now + timedelta(days=offset)
                        if candidate.day in tt.days:
                            return candidate.replace(hour=h, minute=m, second=0, microsecond=0).timestamp()
                    return None
                else:
                    next_dt += timedelta(days=1)
            return next_dt.timestamp()
        except Exception:
            pass

    return None


def run_scheduled_backup(
    config: ScheduleConfig,
    trigger_reason: str,
    logger: Optional[Callable[[str], None]] = None,
) -> dict:
    """评估并执行一次调度备份。"""
    from .i18n import t as _
    from .main import run_incremental
    from .log import get_logger
    log = get_logger(__name__)

    backup_dir = Path(config.backup_dir).expanduser()
    should_run, skip_key = evaluate_schedule(config, trigger_reason, backup_dir)

    def emit(msg: str):
        if logger:
            logger(msg)
        log.info(msg)

    if not should_run:
        if skip_key == "schedule.skipped_interval":
            last_time = get_last_backup_time(backup_dir)
            elapsed = (time.time() - last_time) / 3600.0 if last_time else 0
            emit(_(skip_key, elapsed=elapsed, min_minutes=config.min_interval_minutes))
        elif skip_key == "schedule.skipped_condition":
            emit(_(skip_key, reason=trigger_reason))
        else:
            emit(_(skip_key))
        return {"status": "skipped", "reason": skip_key}

    emit(_("schedule.running", reason=trigger_reason))

    try:
        stats = run_incremental(backup_dir, config.mode, emit)
        emit(_("schedule.done"))
        return {"status": "ok", "stats": stats}
    except Exception as e:
        emit(_("schedule.failed", error=str(e)))
        return {"status": "error", "error": str(e)}


# ─── 调度配置路径 ────────────────────────────────────

def schedule_config_path() -> Path:
    from .config import CONFIG_DIR
    return CONFIG_DIR / "schedule.json"
