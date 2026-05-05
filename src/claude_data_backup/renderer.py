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

_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(s: str, max_len: int = 80) -> str:
    if not s:
        return "未命名"
    s = _INVALID_NAME_CHARS.sub("", s)
    s = s.replace("\n", " ").strip()
    s = re.sub(r"\s+", " ", s)
    if len(s) > max_len:
        s = s[:max_len].rstrip() + "…"
    return s or "未命名"


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
    return s[:limit] + f"\n\n……（已截断 {len(s) - limit} 字符）"


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
                out.append("> **[思考]**\n>\n> " + t2.replace("\n", "\n> "))
        elif t == "tool_use":
            name = c.get("name", "tool")
            inp = c.get("input") or {}
            msg = c.get("message") or ""
            body = json.dumps(inp, ensure_ascii=False, indent=2)
            tid = c.get("id", "")
            header = f"**[工具调用：{name}]**" + (f" —— {msg}" if msg else "") + (f" `{tid}`" if tid else "")
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
                            parts.append("[图片已省略]")
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
            label = "工具返回" + ("（出错）" if is_err else "")
            label_full = f"{label}：{name}" if name else label
            prefix = f"**[{label_full}]**" + (f" `{tid}`" if tid else "")
            out.append(f"{prefix}\n\n```\n{truncate_for_md(body, 2000)}\n```")
        elif t == "image":
            out.append("**[图片]** *（二进制已省略）*")
        else:
            out.append(f"**[{t}]** `{json.dumps(c, ensure_ascii=False)[:400]}`")
    return out


# ---------- Desktop conversation (Mode A / Mode B) ----------

def render_desktop_conversation(conv: dict, source: str) -> str:
    """渲染一条 claude.ai 对话。source 取值 `"在线 API（完整）"` / `"缓存残骸（可能不完整）"`。"""
    name = conv.get("name") or "(未命名)"
    created = conv.get("created_at") or ""
    updated = conv.get("updated_at") or ""
    model = conv.get("model") or ""
    uuid = conv.get("uuid")
    project = (conv.get("project") or {}).get("name") if conv.get("project") else None
    platform = conv.get("platform") or ""
    summary = conv.get("summary") or ""
    messages = conv.get("chat_messages") or []

    lines = [f"# {name}", ""]
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append(f"| 数据来源 | {source} |")
    lines.append(f"| UUID | `{uuid}` |")
    lines.append(f"| 创建时间 | {created} |")
    lines.append(f"| 更新时间 | {updated} |")
    lines.append(f"| 模型 | `{model}` |")
    lines.append(f"| 平台 | {platform} |")
    if project:
        lines.append(f"| 项目 | {project} |")
    lines.append(f"| 消息数 | {len(messages)} |")
    if summary:
        lines.append("")
        lines.append(f"**摘要：** {summary}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for m in messages:
        sender = m.get("sender")
        ts = m.get("created_at", "")
        role = {"human": "我", "assistant": "Claude"}.get(sender, sender or "?")
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
            lines.append("**附件：**")
            for a in atts:
                nm = a.get("file_name") or a.get("name") or "(文件)"
                ext = a.get("extracted_content")
                lines.append(f"- `{nm}`" + (f" —— 提取了 {len(ext)} 字符" if ext else ""))
            for f in files:
                nm = f.get("file_name") or f.get("name") or f.get("file_uuid") or "(文件)"
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
    lines = [f"# {session.title}", ""]
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append(f"| 数据来源 | CLI 本地日志（完整） |")
    lines.append(f"| 会话 ID | `{session.session_id}` |")
    lines.append(f"| 工作目录 | `{session.cwd}` |")
    lines.append(f"| 开始时间 | {session.first_ts or ''} |")
    lines.append(f"| 最后活动 | {session.last_ts or ''} |")
    lines.append(f"| 模型 | `{session.model}` |")
    lines.append(f"| CLI 版本 | `{session.version}` |")
    lines.append(f"| 用户轮数 | {session.user_turns} |")
    lines.append(f"| 助手轮数 | {session.assistant_turns} |")
    lines.append(f"| 事件总数 | {session.total_events} |")
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
            heading = "工具返回" if _is_tool_result_only(content) else "我"
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
            lines.append(f"## Claude —— `{m}` —— {ts}")
            lines.append("")
            lines.extend(blocks)
            lines.append("")
        elif t == "attachment":
            att = e.get("attachment") or {}
            atype = att.get("type")
            if atype in _NOISE_ATTACHMENT_TYPES:
                continue
            label = atype or "附件"
            name = (att.get("name") or att.get("filename") or att.get("path")
                    or e.get("filename") or "")
            lines.append(f"> **[附件：{label}]** {name}".rstrip())
            lines.append("")
        elif t == "summary":
            lines.append(f"> **[摘要]** {e.get('summary', '')}")
            lines.append("")
        # 跳过：permission-mode / file-history-snapshot / system / last-prompt / queue-operation
    return "\n".join(lines)


# ---------- 索引页 ----------

def render_top_index(stats: dict, when: str) -> str:
    """顶层 INDEX.md。stats 由 main.py 填充。"""
    lines = [
        "# Claude 对话归档",
        "",
        f"导出时间：{when}。",
        f"导出来源：{stats.get('source_platform', '-')}。",
        "",
        "## 数量概览",
        "",
    ]
    ma = stats.get("mode_a", {})
    mb = stats.get("mode_b", {})
    mc = stats.get("mode_c", {})

    if ma.get("status") == "ok":
        lines.append(f"- **Mode A · 在线 API 全量**：{ma.get('count', 0)} 条（完整）")
    else:
        lines.append(f"- Mode A · 在线 API 全量：跳过（{ma.get('reason', '未运行')}）")

    if mb.get("status") == "ok":
        extra = f"（其中 {mb.get('new_unique_to_b', 0)} 条是 A 没拿到的）" if ma.get("status") == "ok" else ""
        lines.append(f"- **Mode B · 缓存残骸**：{mb.get('cached_total', 0)} 条{extra}")
    else:
        lines.append(f"- Mode B · 缓存残骸：跳过（{mb.get('reason', '未运行')}）")

    if mc.get("status") == "ok":
        lines.append(f"- **Mode C · Claude Code 本地日志**："
                     f"{mc.get('real', 0)} 个真实会话 + {mc.get('observer', 0)} 个观察器会话")
    else:
        lines.append(f"- Mode C · Claude Code 本地日志：跳过（{mc.get('reason', '未运行')}）")

    lines += [
        "",
        "## 从哪里开始读",
        "",
        "- [`desktop-conversations/00_index.md`](desktop-conversations/00_index.md) —— "
        "claude.ai 网页对话索引（Mode A + Mode B 合并）。",
        "- [`claude-code/real/00_index.md`](claude-code/real/00_index.md) —— "
        "真实 Claude Code 项目会话索引。",
        "- [`claude-code/observer/00_index.md`](claude-code/observer/00_index.md) —— "
        "claude-mem 观察器自动产生的会话索引。",
        "- [`STATS.md`](STATS.md) —— 本次运行的详细统计。",
        "",
        "## 每条对话的格式",
        "",
        "- `<日期>__<标题>.md` —— 人类可读。思考块 `> **[思考]**`；工具调用/返回包装在代码块里；",
        "  超过约 2000 字符的工具返回在 Markdown 里会被截断，但在备份里保留完整内容。",
        "- `<日期>__<标题>.json`（Desktop）或 `.jsonl`（CLI）—— 机器可读的原始数据。",
        "",
        "## 隐私",
        "",
        "- 所有数据均从本机读取，未上传任何远程服务器。",
        "- cookie 和 sessionKey 只在内存里存在，不落盘。",
        "- 由 [ClaudeDataBackup](https://github.com/Raven940309/ClaudeDataBackup) 生成。",
    ]
    return "\n".join(lines)


def render_stats_report(stats: dict, when: str) -> str:
    lines = [
        "# STATS.md —— 本次运行统计",
        "",
        f"时间：{when}",
        "",
        "```json",
        json.dumps(stats, ensure_ascii=False, indent=2, default=str),
        "```",
    ]
    return "\n".join(lines)
