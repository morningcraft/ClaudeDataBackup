"""备份清单管理。

记录已备份的对话和 CLI 会话元数据，支持增量检测。
清单文件位于备份目录根：manifest.json
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path

MANIFEST_FILENAME = "manifest.json"


def _manifest_path(backup_dir: Path) -> Path:
    return backup_dir / MANIFEST_FILENAME


def load_manifest(backup_dir: Path) -> dict:
    """读取清单，不存在则返回空结构。"""
    p = _manifest_path(backup_dir)
    if not p.is_file():
        return _empty_manifest()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "version" not in data:
            return _empty_manifest()
        return data
    except (json.JSONDecodeError, OSError):
        return _empty_manifest()


def save_manifest(backup_dir: Path, manifest: dict) -> None:
    """写入清单文件。"""
    backup_dir.mkdir(parents=True, exist_ok=True)
    manifest["last_backup_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _manifest_path(backup_dir).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _empty_manifest() -> dict:
    return {
        "version": 1,
        "last_backup_time": None,
        "conversations": {},
        "cli_sessions": {},
    }


# ---------- 对话（Claude.ai） ----------

def needs_conversation_update(manifest: dict, uuid: str, updated_at: str) -> bool:
    """判断对话是否需要更新。

    - 新 UUID：需要
    - 已有但 updated_at 变了：需要
    - 已有且 updated_at 相同：不需要
    """
    existing = manifest["conversations"].get(uuid)
    if not existing:
        return True
    return existing.get("updated_at") != updated_at


def register_conversation(manifest: dict, uuid: str, meta: dict) -> None:
    """记录一条已备份的对话。"""
    manifest["conversations"][uuid] = {
        "title": meta.get("title", ""),
        "updated_at": meta.get("updated_at", ""),
        "message_count": meta.get("message_count", 0),
        "model": meta.get("model", ""),
        "project": meta.get("project"),
        "source": meta.get("source", "online_api"),
        "file": meta.get("file", ""),
    }


def get_backed_up_conversations(manifest: dict) -> dict[str, dict]:
    """返回所有已备份对话的元数据。"""
    return dict(manifest["conversations"])


# ---------- CLI 会话（Claude Code） ----------

def needs_session_update(manifest: dict, session_id: str, last_ts: str) -> bool:
    """判断 CLI 会话是否需要更新。"""
    existing = manifest["cli_sessions"].get(session_id)
    if not existing:
        return True
    return existing.get("last_ts") != last_ts


def register_cli_session(manifest: dict, session_id: str, meta: dict) -> None:
    """记录一个已备份的 CLI 会话。"""
    manifest["cli_sessions"][session_id] = {
        "title": meta.get("title", ""),
        "project": meta.get("project", ""),
        "first_ts": meta.get("first_ts", ""),
        "last_ts": meta.get("last_ts", ""),
        "source": meta.get("source", "cli_log"),
        "file": meta.get("file", ""),
    }


def get_backed_up_sessions(manifest: dict) -> dict[str, dict]:
    """返回所有已备份 CLI 会话的元数据。"""
    return dict(manifest["cli_sessions"])


# ---------- 统计 ----------

def summary(manifest: dict) -> dict:
    """返回清单摘要。"""
    convs = manifest["conversations"]
    sessions = manifest["cli_sessions"]
    return {
        "conversation_count": len(convs),
        "session_count": len(sessions),
        "last_backup_time": manifest.get("last_backup_time"),
    }


if __name__ == "__main__":
    from .config import get_backup_dir
    backup_dir = get_backup_dir()
    m = load_manifest(backup_dir)
    s = summary(m)
    print(f"清单文件: {_manifest_path(backup_dir)}")
    print(f"对话数: {s['conversation_count']}")
    print(f"会话数: {s['session_count']}")
    print(f"上次备份: {s['last_backup_time']}")
