"""应用配置管理。

持久化到 ~/.claude-data-backup/config.json。
管理备份目录、数据源选择、Claude Code 项目过滤等。
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".claude-data-backup"
CONFIG_FILE = CONFIG_DIR / "config.json"

_DEFAULTS: dict[str, Any] = {
    "backup_dir": str(Path.home() / "Documents" / "ClaudeDataBackup"),
    "sources": {
        "claude_ai": True,
        "claude_code": True,
    },
    "claude_code_projects": {
        "_mode": "all",       # "all" | "selected" | "none"
        "_selected": [],      # 项目目录名列表（_mode="selected" 时生效）
    },
    "last_run_time": None,
    "last_run_stats": None,
}


def load_config() -> dict:
    """读取配置，不存在或损坏则返回默认值。"""
    if not CONFIG_FILE.is_file():
        return dict(_DEFAULTS)
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        # 合并默认值（补全新增字段）
        merged = dict(_DEFAULTS)
        _deep_update(merged, data)
        return merged
    except (json.JSONDecodeError, OSError):
        return dict(_DEFAULTS)


def save_config(cfg: dict) -> None:
    """写入配置文件。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _deep_update(base: dict, override: dict) -> dict:
    """递归合并 override 到 base。"""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_update(base[k], v)
        else:
            base[k] = v
    return base


def get_backup_dir() -> Path:
    """获取备份目录。"""
    cfg = load_config()
    return Path(cfg["backup_dir"]).expanduser()


def set_backup_dir(path: Path) -> None:
    """设置并保存备份目录。"""
    cfg = load_config()
    cfg["backup_dir"] = str(path)
    save_config(cfg)


def get_sources() -> dict[str, bool]:
    """获取数据源开关。"""
    cfg = load_config()
    return dict(cfg["sources"])


def set_sources(claude_ai: bool | None = None, claude_code: bool | None = None) -> None:
    """设置数据源开关。"""
    cfg = load_config()
    if claude_ai is not None:
        cfg["sources"]["claude_ai"] = claude_ai
    if claude_code is not None:
        cfg["sources"]["claude_code"] = claude_code
    save_config(cfg)


def get_claude_code_projects_config() -> dict:
    """获取 Claude Code 项目选择配置。"""
    cfg = load_config()
    return dict(cfg["claude_code_projects"])


def set_claude_code_projects(mode: str, selected: list[str] | None = None) -> None:
    """设置 Claude Code 项目选择。mode: "all" | "selected" | "none"。"""
    cfg = load_config()
    cfg["claude_code_projects"]["_mode"] = mode
    if selected is not None:
        cfg["claude_code_projects"]["_selected"] = selected
    save_config(cfg)


def update_last_run(stats: dict) -> None:
    """更新最近一次运行时间和统计。"""
    from datetime import datetime
    cfg = load_config()
    cfg["last_run_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cfg["last_run_stats"] = stats
    save_config(cfg)


if __name__ == "__main__":
    import json as _json
    cfg = load_config()
    print(_json.dumps(cfg, ensure_ascii=False, indent=2))
    print(f"\n配置文件: {CONFIG_FILE}")
    print(f"备份目录: {get_backup_dir()}")
