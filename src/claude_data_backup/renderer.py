"""统一渲染层 —— 把 conversation 和 session 转成中文 Markdown。

Mode A (API) 和 Mode B (Cache) 的 conversation JSON 结构一致，共用 `render_desktop_conversation`。
Mode C (CLI) 的 session 用 `render_cli_session`。
"""
from __future__ import annotations
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cli_exporter import SessionData
from .i18n import t as _

_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(s: str, max_bytes: int = 160) -> str:
    """生成文件系统安全的名字，按 UTF-8 字节长度截断。

    max_bytes 默认 160：给日期前缀(~12B)、分隔符(2B)、session ID(9B)、
    扩展名(~6B) 留出余量，确保完整路径的文件名不超过 255 字节。
    """
    if not s:
        return _("renderer.unnamed")
    s = _INVALID_NAME_CHARS.sub("", s)
    s = s.replace("\n", " ").strip()
    s = re.sub(r"\s+", " ", s)
    # 按字节截断（SMB/NAS 文件名限制 255 字节）
    encoded = s.encode("utf-8")
    if len(encoded) > max_bytes:
        # 截断到 max_bytes 以内，确保不截断多字节字符
        truncated = encoded[:max_bytes - 3]  # 留 3 字节给 "…"
        # 回退到最近的字符边界
        while truncated and (truncated[-1] & 0xC0) == 0x80:
            truncated = truncated[:-1]
        s = truncated.decode("utf-8", errors="ignore") + "…"
    return s or _("renderer.unnamed")


def iso_to_date(s: Any) -> str:
    if not s:
        return "0000-00-00"
    try:
        if isinstance(s, (int, float)):
            return datetime.fromtimestamp(s / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        return str(s)[:10]
    except (ValueError, OSError):
        return "0000-00-00"


def truncate_for_md(s: str, limit: int = 2000) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + "\n\n" + _("renderer.truncated", n=len(s) - limit)


def hardlink_or_copy(src: Path, dst: Path) -> None:
    """优先硬链接，跨卷/权限失败时 fallback 到复制。"""
    if dst.exists():
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


# ---------- content blocks (共用：Mode A/B/C) ----------

def _render_blocks(blocks: Any) -> list[str]:
    """渲染 Anthropic Messages-API 风格的 content blocks（string 或 list）。"""
    out: list[str] = []
    if isinstance(blocks, str):
        if blocks.strip():
            out.append(blocks.rstrip())
        return out
    if not isinstance(blocks, list):
        out.append(f"`{json.dumps(blocks, ensure_ascii=False)[:400]}`")
        return out
    for c in blocks:
        if not isinstance(c, dict):
            out.append(f"`{str(c)[:400]}`")
            continue
        t = c.get("type")
        if t == "text":
            txt = (c.get("text") or "").rstrip()
            if txt:
                out.append(txt)
        elif t == "thinking":
            t2 = (c.get("thinking") or "").strip()
            if t2:
                out.append("> **[" + _("renderer.thinking") + "]**\n>\n> " + t2.replace("\n", "\n> "))
        elif t == "tool_use":
            name = c.get("name", "tool")
            inp = c.get("input") or {}
            msg = c.get("message") or ""
            body = json.dumps(inp, ensure_ascii=False, indent=2)
            tid = c.get("id", "")
            header = f"**[{_('renderer.tool_call', name=name)}]**" + (f" —— {msg}" if msg else "") + (f" `{tid}`" if tid else "")
            out.append(f"{header}\n\n```json\n{truncate_for_md(body, 1500)}\n```")
        elif t == "tool_result":
            tid = c.get("tool_use_id", "")
            name = c.get("name", "")
            body_c = c.get("content")
            if isinstance(body_c, list):
                parts = []
                for i in body_c:
                    if isinstance(i, dict):
                        if i.get("type") == "text":
                            parts.append(i.get("text", ""))
                        elif i.get("type") == "image":
                            parts.append("[" + _("renderer.image_omitted") + "]")
                        else:
                            parts.append(json.dumps(i, ensure_ascii=False))
                    else:
                        parts.append(str(i))
                body = "\n\n".join(parts)
            elif isinstance(body_c, str):
                body = body_c
            else:
                body = json.dumps(body_c, ensure_ascii=False) if body_c is not None else ""
            is_err = bool(c.get("is_error"))
            label = _("renderer.tool_result_error") if is_err else _("renderer.tool_result")
            label_full = f"{label}：{name}" if name else label
            prefix = f"**[{label_full}]**" + (f" `{tid}`" if tid else "")
            out.append(f"{prefix}\n\n```\n{truncate_for_md(body, 2000)}\n```")
        elif t == "image":
            out.append("**[" + _("renderer.image_binary_omitted") + "]** *（binary omitted）*")
        else:
            out.append(f"**[{t}]** `{json.dumps(c, ensure_ascii=False)[:400]}`")
    return out


# ---------- Desktop conversation (Mode A / Mode B) ----------

def render_desktop_conversation(conv: dict, source: str) -> str:
    """渲染一条 claude.ai 对话。"""
    name = conv.get("name") or _("renderer.unnamed")
    created = conv.get("created_at") or ""
    updated = conv.get("updated_at") or ""
    model = conv.get("model") or ""
    uuid = conv.get("uuid")
    project = (conv.get("project") or {}).get("name") if conv.get("project") else None
    platform = conv.get("platform") or ""
    summary = conv.get("summary") or ""
    messages = conv.get("chat_messages") or []

    role_me = _("renderer.role_me")
    role_claude = _("renderer.role_claude")

    lines = [f"# {name}", ""]
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append(f"| {_('renderer.field_source')} | {source} |")
    lines.append(f"| {_('renderer.field_uuid')} | `{uuid}` |")
    lines.append(f"| {_('renderer.field_created')} | {created} |")
    lines.append(f"| {_('renderer.field_updated')} | {updated} |")
    lines.append(f"| {_('renderer.field_model')} | `{model}` |")
    lines.append(f"| {_('renderer.field_platform')} | {platform} |")
    if project:
        lines.append(f"| {_('renderer.field_project')} | {project} |")
    lines.append(f"| {_('renderer.field_message_count')} | {len(messages)} |")
    if summary:
        lines.append("")
        lines.append(f"**{_('renderer.summary_label')}：** {summary}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for m in messages:
        sender = m.get("sender")
        ts = m.get("created_at", "")
        role = {"human": role_me, "assistant": role_claude}.get(sender, sender or "?")
        lines.append(f"## {role} —— {ts}")
        lines.append("")
        blocks = _render_blocks(m.get("content"))
        if not blocks and m.get("text"):
            blocks = [m["text"]]
        lines.extend(blocks)
        lines.append("")
        atts = m.get("attachments") or []
        files = m.get("files") or []
        if atts or files:
            lines.append(f"**{_('renderer.attachment_label')}：**")
            for a in atts:
                nm = a.get("file_name") or a.get("name") or f"({_('renderer.file_label')})"
                ext = a.get("extracted_content")
                lines.append(f"- `{nm}`" + (f" —— {_('renderer.extracted_chars', n=len(ext))}" if ext else ""))
            for f in files:
                nm = f.get("file_name") or f.get("name") or f.get("file_uuid") or f"({_('renderer.file_label')})"
                lines.append(f"- `{nm}`")
            lines.append("")
        lines.append("")
    return "\n".join(lines)


# ---------- CLI session (Mode C) ----------

def _is_tool_result_only(blocks: Any) -> bool:
    if not isinstance(blocks, list) or not blocks:
        return False
    return all(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks)


_NOISE_ATTACHMENT_TYPES = {
    "deferred_tools_delta",
    "deferred_slash_commands_delta",
    "deferred_mcp_delta",
    "deferred_agents_delta",
}


def render_cli_session(session: SessionData) -> str:
    role_me = _("renderer.role_me")
    role_claude = _("renderer.role_claude")
    tool_result = _("renderer.tool_result_heading")
    attachment_label = _("renderer.attachment_label")

    lines = [f"# {session.title}", ""]
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append(f"| {_('renderer.field_source')} | {_('renderer.source_cli_full')} |")
    lines.append(f"| {_('renderer.field_session_id')} | `{session.session_id}` |")
    lines.append(f"| {_('renderer.field_work_dir')} | `{session.cwd}` |")
    lines.append(f"| {_('renderer.field_start_time')} | {session.first_ts or ''} |")
    lines.append(f"| {_('renderer.field_last_activity')} | {session.last_ts or ''} |")
    lines.append(f"| {_('renderer.field_model')} | `{session.model}` |")
    lines.append(f"| {_('renderer.field_cli_version')} | `{session.version}` |")
    lines.append(f"| {_('renderer.field_user_turns')} | {session.user_turns} |")
    lines.append(f"| {_('renderer.field_assistant_turns')} | {session.assistant_turns} |")
    lines.append(f"| {_('renderer.field_total_events')} | {session.total_events} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    for e in session.events:
        t = e.get("type")
        ts = e.get("timestamp") or ""
        if t == "user":
            msg = e.get("message") or {}
            content = msg.get("content")
            blocks = _render_blocks(content)
            if not blocks:
                continue
            heading = tool_result if _is_tool_result_only(content) else role_me
            lines.append(f"## {heading} —— {ts}")
            lines.append("")
            lines.extend(blocks)
            lines.append("")
        elif t == "assistant":
            msg = e.get("message") or {}
            m = msg.get("model") or ""
            blocks = _render_blocks(msg.get("content"))
            if not blocks:
                continue
            lines.append(f"## {role_claude} —— `{m}` —— {ts}")
            lines.append("")
            lines.extend(blocks)
            lines.append("")
        elif t == "attachment":
            att = e.get("attachment") or {}
            atype = att.get("type")
            if atype in _NOISE_ATTACHMENT_TYPES:
                continue
            label = atype or attachment_label
            name = (att.get("name") or att.get("filename") or att.get("path")
                    or e.get("filename") or "")
            lines.append(f"> **[{_('renderer.attachment_label')}：{label}]** {name}".rstrip())
            lines.append("")
        elif t == "summary":
            lines.append(f"> **[{_('renderer.summary_label')}]** {e.get('summary', '')}")
            lines.append("")
        # 跳过：permission-mode / file-history-snapshot / system / last-prompt / queue-operation
    return "\n".join(lines)


# ---------- 索引页 ----------

def render_top_index(stats: dict, when: str) -> str:
    """顶层 INDEX.md。stats 由 main.py 填充。"""
    lines = [
        f"# {_('renderer.index_title')}",
        "",
        f"{_('renderer.index_export_time')}：{when}。",
        f"{_('renderer.index_source')}：{stats.get('source_platform', '-')}。",
        "",
        f"## {_('renderer.index_overview')}",
        "",
    ]
    ma = stats.get("mode_a", {})
    mb = stats.get("mode_b", {})
    mc = stats.get("mode_c", {})
    reason_not_run = _("renderer.reason_not_run")

    if ma.get("status") == "ok":
        lines.append(_("renderer.mode_a_ok", count=ma.get('count', 0)))
    else:
        lines.append(_("renderer.mode_a_skip", reason=ma.get('reason', reason_not_run)))

    if mb.get("status") == "ok":
        extra = _("renderer.mode_b_new_unique", n=mb.get('new_unique_to_b', 0)) if ma.get("status") == "ok" else ""
        lines.append(_("renderer.mode_b_ok", count=mb.get('cached_total', 0)) + extra)
    else:
        lines.append(_("renderer.mode_b_skip", reason=mb.get('reason', reason_not_run)))

    if mc.get("status") == "ok":
        lines.append(_("renderer.mode_c_ok", real=mc.get('real', 0), observer=mc.get('observer', 0)))
    else:
        lines.append(_("renderer.mode_c_skip", reason=mc.get('reason', reason_not_run)))

    lines += [
        "",
        f"## {_('renderer.index_where_to_read')}",
        "",
        "- [`desktop-conversations/00_index.md`](desktop-conversations/00_index.md) —— "
        + _("renderer.index_desktop_link"),
        "- [`claude-code/real/00_index.md`](claude-code/real/00_index.md) —— "
        + _("renderer.index_real_link"),
        "- [`claude-code/observer/00_index.md`](claude-code/observer/00_index.md) —— "
        + _("renderer.index_observer_link"),
        "- [`STATS.md`](STATS.md) —— " + _("renderer.index_stats_link"),
        "",
        f"## {_('renderer.index_format_title')}",
        "",
        "- `<date>__<title>.md` —— " + _("renderer.index_format_md"),
        "  " + _("renderer.index_format_overflow"),
        "- `<date>__<title>.json` (Desktop) or `.jsonl` (CLI) —— " + _("renderer.index_format_raw"),
        "",
        f"## {_('renderer.index_privacy_title')}",
        "",
        "- " + _("renderer.index_privacy_local"),
        "- " + _("renderer.index_privacy_cookie"),
        "- " + _("renderer.index_privacy_generated"),
    ]
    return "\n".join(lines)


def render_stats_report(stats: dict, when: str) -> str:
    lines = [
        f"# {_('renderer.stats_title')}",
        "",
        f"{_('renderer.stats_time')}：{when}",
        "",
        "```json",
        json.dumps(stats, ensure_ascii=False, indent=2, default=str),
        "```",
    ]
    return "\n".join(lines)
