"""HTML 聊天记录查看器生成器。

扫描备份目录，生成自包含的 index.html，嵌入所有对话数据和渲染逻辑。
浏览器直接打开即可查看，无需 HTTP server。
"""
from __future__ import annotations
import base64
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import manifest as mf
from . import cli_exporter
from .file_extractor import get_file_as_data_uri
from .i18n import t as _, get_language


def _json_default(obj: Any) -> str:
    """JSON 序列化 fallback。"""
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    return str(obj)


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """去掉 HTML 标签，只留纯文本。"""
    return _HTML_TAG_RE.sub("", text).strip()


# ---------- 数据采集 ----------

def _load_desktop_conversations(backup_dir: Path,
                                 file_map: dict[str, Path] | None = None) -> list[dict]:
    """读取所有桌面对话的 JSON 文件，转成统一的 messages 格式。"""
    results = []
    # 扫描 desktop-conversations 下所有 .json 文件
    dc_dir = backup_dir / "desktop-conversations"
    if not dc_dir.is_dir():
        return results
    for json_path in dc_dir.rglob("*.json"):
        if json_path.name == "00_index.md":
            continue
        try:
            conv = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if "chat_messages" not in conv:
            continue
        messages = _convert_desktop_messages(conv.get("chat_messages", []), file_map=file_map)
        project = None
        if conv.get("project") and isinstance(conv["project"], dict):
            project = conv["project"].get("name")
        last_ts = messages[-1]["ts"] if messages else conv.get("created_at", "")
        results.append({
            "uuid": conv.get("uuid", ""),
            "title": _strip_html(conv.get("name") or "") or _("renderer.unnamed"),
            "date": _iso_to_date(last_ts),
            "created_at": conv.get("created_at", ""),
            "last_ts": last_ts,
            "model": conv.get("model", ""),
            "source": "online_api",
            "project": project,
            "messageCount": len(conv.get("chat_messages", [])),
            "messages": messages,
        })
    return results


def _convert_desktop_messages(chat_messages: list[dict],
                               file_map: dict[str, Path] | None = None) -> list[dict]:
    """把 claude.ai API 的 chat_messages 转成统一的 messages 格式。"""
    messages = []
    for msg in chat_messages:
        sender = msg.get("sender", "")
        if sender not in ("human", "assistant"):
            continue
        content = msg.get("content", "")
        blocks = _parse_content_blocks(content)
        if not blocks:
            continue

        # 处理消息级别的 files（图片、PDF 等）
        for f in msg.get("files", []):
            if not isinstance(f, dict):
                continue
            if f.get("file_kind") == "image":
                img_data = _resolve_image_file(f, file_map)
                if img_data:
                    blocks.append(img_data)
            elif f.get("file_kind") == "document":
                file_name = f.get("file_name", "")
                file_uuid = f.get("file_uuid", "")
                doc_asset = f.get("document_asset", {})
                pdf_data = _resolve_pdf_file(f, file_map)
                if pdf_data:
                    blocks.append(pdf_data)
                else:
                    blocks.append({
                        "type": "attachment",
                        "name": file_name,
                        "file_type": "pdf",
                        "content": f"[{_('html.pdf_document')}: {file_name}]",
                    })

        # 处理消息级别的 attachments（文本文件）
        for att in msg.get("attachments", []):
            if not isinstance(att, dict):
                continue
            name = att.get("file_name", "")
            extracted = att.get("extracted_content", "")
            if extracted:
                blocks.append({
                    "type": "attachment",
                    "name": name or _("html.unnamed_attachment"),
                    "file_type": att.get("file_type", ""),
                    "content": extracted,
                })

        messages.append({
            "sender": sender,
            "ts": msg.get("created_at", ""),
            "blocks": blocks,
        })
    return messages


def _parse_content_blocks(content: Any) -> list[dict]:
    """解析 content 字段（可能是 string 或 list of blocks）。"""
    if isinstance(content, str):
        if content.strip():
            return [{"type": "text", "text": content}]
        return []
    if not isinstance(content, list):
        return []
    blocks = []
    for b in content:
        if not isinstance(b, dict):
            continue
        btype = b.get("type", "")
        if btype == "text":
            text = b.get("text", "")
            if text.strip():
                blocks.append({"type": "text", "text": text})
        elif btype == "thinking":
            thinking = b.get("thinking", "")
            if thinking.strip():
                blocks.append({"type": "thinking", "thinking": thinking})
        elif btype == "tool_use":
            blocks.append({
                "type": "tool_use",
                "name": b.get("name", ""),
                "input": b.get("input"),
                "id": b.get("id", ""),
            })
        elif btype == "tool_result":
            result_content = b.get("content", "")
            if isinstance(result_content, list):
                text_parts = []
                for part in result_content:
                    if isinstance(part, dict):
                        ptype = part.get("type", "")
                        if ptype == "text":
                            text_parts.append(part.get("text", ""))
                        elif ptype == "image":
                            src = part.get("source", {})
                            if src.get("type") == "base64" and src.get("data"):
                                media = src.get("media_type", "image/png")
                                blocks.append({
                                    "type": "image",
                                    "data_uri": f"data:{media};base64,{src['data']}",
                                })
                            else:
                                text_parts.append(_("html.image_placeholder"))
                        elif ptype == "knowledge":
                            title = part.get("title", "")
                            url = part.get("url", "")
                            kp = _("html.knowledge_placeholder", title=title)
                            text_parts.append(f"[{kp}]({url})" if url else f"[{kp}]")
                        elif ptype == "local_resource":
                            text_parts.append(f"[{_('html.file_placeholder', name=part.get('name', part.get('file_path', '')))}]")
                        else:
                            text_parts.append(f"[{ptype}]")
                result_content = "\n".join(text_parts)
            if not isinstance(result_content, str):
                result_content = str(result_content)
            blocks.append({
                "type": "tool_result",
                "name": b.get("name", ""),
                "content": result_content,
                "is_error": b.get("is_error", False),
            })
        elif btype == "image":
            src = b.get("source", {})
            if src.get("type") == "base64" and src.get("data"):
                media = src.get("media_type", "image/png")
                blocks.append({
                    "type": "image",
                    "data_uri": f"data:{media};base64,{src['data']}",
                })
            else:
                blocks.append({"type": "image"})
    return blocks


def _resolve_image_file(f: dict, file_map: dict[str, Path] | None) -> dict | None:
    """处理 files 数组中的 image 类型。"""
    file_uuid = f.get("file_uuid", "")
    if not file_uuid:
        return None
    file_name = f.get("file_name", "")
    if file_map and file_uuid in file_map:
        data_uri = get_file_as_data_uri(file_map[file_uuid])
        if data_uri:
            return {"type": "image", "data_uri": data_uri,
                    "file_name": file_name, "file_uuid": file_uuid}
    return {"type": "image", "file_name": file_name}


def _resolve_pdf_file(f: dict, file_map: dict[str, Path] | None) -> dict | None:
    """处理 files 数组中的 document（PDF）类型。"""
    file_uuid = f.get("file_uuid", "")
    if not file_uuid:
        return None
    file_name = f.get("file_name", "")
    if file_map and file_uuid in file_map:
        fpath = file_map[file_uuid]
        if fpath.exists() and fpath.suffix.lower() == ".pdf":
            # 返回相对路径（从 index.html 到 files/xxx.pdf）
            return {"type": "pdf", "rel_path": f"files/{fpath.name}",
                    "file_name": file_name, "file_uuid": file_uuid}
    return None


def _load_cli_sessions(backup_dir: Path) -> list[dict]:
    """读取所有 CLI 会话的 JSONL 文件，转成统一的 messages 格式。"""
    results = []
    cc_dir = backup_dir / "claude-code" / "real"
    if not cc_dir.is_dir():
        return results
    for proj_dir in sorted(cc_dir.iterdir()):
        if not proj_dir.is_dir():
            continue
        for jsonl_path in sorted(proj_dir.glob("*.jsonl")):
            session = _parse_jsonl_to_session(jsonl_path, proj_dir.name)
            if session:
                results.append(session)
    return results


def _parse_jsonl_to_session(path: Path, project: str) -> dict | None:
    """解析 .jsonl 文件为统一的 session 格式。"""
    events: list[dict] = []
    session_id = model = ""
    first_ts = last_ts = ""
    try:
        with open(path, encoding="utf-8") as fp:
            for line in fp:
                line = line.rstrip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                events.append(d)
                session_id = session_id or d.get("sessionId", "")
                ts = d.get("timestamp", "")
                if ts:
                    if not first_ts:
                        first_ts = ts
                    last_ts = ts
                if d.get("type") == "assistant":
                    m = d.get("message") or {}
                    model = model or m.get("model", "")
    except OSError:
        return None

    if not events:
        return None

    # 从事件中提取 title
    unnamed = _("renderer.unnamed")
    title = unnamed
    for e in events:
        if e.get("type") == "summary" and e.get("summary"):
            title = _strip_html(str(e["summary"]))[:100]
            break
    if title == unnamed:
        for e in events:
            if e.get("type") != "user":
                continue
            msg = e.get("message") or {}
            c = msg.get("content")
            if isinstance(c, str) and c.strip():
                title = _strip_html(c).splitlines()[0][:100]
                break
            if isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "text":
                        t = _strip_html((b.get("text") or "")).strip()
                        if t:
                            title = t.splitlines()[0][:100]
                            break

    messages = _convert_cli_events(events)

    return {
        "uuid": session_id,
        "title": title,
        "date": _iso_to_date(last_ts),
        "created_at": first_ts,
        "last_ts": last_ts,
        "model": model,
        "source": "cli_log",
        "project": project,
        "messageCount": len(messages),
        "messages": messages,
    }


def _convert_cli_events(events: list[dict]) -> list[dict]:
    """把 CLI 事件流转成统一的 messages 格式。"""
    skip_types = {"permission-mode", "file-history-snapshot", "system",
                  "last-prompt", "queue-operation", "tool_result"}
    messages = []
    for e in events:
        etype = e.get("type", "")
        if etype in skip_types:
            continue
        if etype.startswith("deferred_"):
            continue

        if etype == "summary":
            messages.append({
                "sender": "system",
                "ts": e.get("timestamp", ""),
                "blocks": [{"type": "text", "text": _("html.summary_placeholder", text=e.get('summary', ''))}],
            })
            continue

        if etype not in ("user", "assistant"):
            continue

        msg = e.get("message") or {}
        content = msg.get("content", "")
        blocks = _parse_content_blocks(content)
        if not blocks:
            continue

        sender = "human" if etype == "user" else "assistant"
        messages.append({
            "sender": sender,
            "ts": e.get("timestamp", ""),
            "blocks": blocks,
        })
    return messages


def _iso_to_date(ts: str | None) -> str:
    if not ts:
        return ""
    return ts[:10]


# ---------- HTML 生成 ----------

def generate_html(backup_dir: Path, logger: Callable[[str], None] | None = None,
                  file_map: dict[str, Path] | None = None) -> Path:
    """扫描备份目录，生成 index.html。返回 HTML 文件路径。"""
    if logger:
        logger(_("html.generating"))

    # 采集数据
    convs = _load_desktop_conversations(backup_dir, file_map=file_map)
    sessions = _load_cli_sessions(backup_dir)
    all_items = convs + sessions

    # 按最后一条消息的时间倒序排列
    all_items.sort(key=lambda x: x.get("last_ts", x.get("created_at", "")), reverse=True)

    # 构建嵌入数据
    data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(all_items),
        "items": all_items,
    }

    data_json = json.dumps(data, ensure_ascii=False, default=_json_default)

    # 用 base64 编码避免 JSON 中的特殊字符（反斜杠、</script> 等）破坏 HTML/JS 上下文
    data_b64 = base64.b64encode(data_json.encode("utf-8")).decode("ascii")

    # 构建 I18N JSON 供 JS 使用
    i18n_keys = [
        "html.source_online", "html.source_cache", "html.source_cli",
        "html.msg_count", "html.meta_project", "html.meta_model",
        "html.meta_messages", "html.role_system", "html.thinking_summary",
        "html.tool_call_label", "html.tool_result_label",
        "html.tool_result_error_label", "html.image_alt", "html.pdf_alt",
        "html.pdf_open_hint", "html.attachment_label", "html.doc_fallback",
        "html.tooltip_user_msg", "html.locale_tag",
        "renderer.role_me", "renderer.role_claude",
    ]
    i18n_json = json.dumps({k: _(k) for k in i18n_keys}, ensure_ascii=False)

    html = _HTML_TEMPLATE.replace("__DATA_PLACEHOLDER__", data_b64)
    html = html.replace("__I18N_PLACEHOLDER__", i18n_json)
    html = html.replace("__HTML_LANG__", _("html.html_lang"))
    html = html.replace("__HTML_TITLE__", _("html.viewer_title"))
    html = html.replace("__SIDEBAR_HEADING__", _("html.sidebar_heading"))
    html = html.replace("__SIDEBAR_SUBTITLE__",
                        _("html.sidebar_subtitle", total=len(all_items),
                          ai=len(convs), cc=len(sessions)))
    html = html.replace("__SEARCH_PLACEHOLDER__", _("html.search_placeholder"))
    html = html.replace("__FILTER_ALL__", _("html.filter_all"))
    html = html.replace("__EMPTY_STATE__", _("html.empty_state"))

    out_path = backup_dir / "index.html"
    out_path.write_text(html, encoding="utf-8")

    if logger:
        size_kb = out_path.stat().st_size / 1024
        logger(_("html.generated", count=len(all_items), size=f"{size_kb:.0f}"))

    return out_path


# ---------- HTML 模板 ----------

_HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="__HTML_LANG__">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__HTML_TITLE__</title>
<style>
:root {
  --bg: #f8f9fa;
  --sidebar-bg: #ffffff;
  --sidebar-width: 300px;
  --border: #e0e0e0;
  --text: #1a1a2e;
  --text-secondary: #6c757d;
  --primary: #6c5ce7;
  --primary-light: #a29bfe;
  --human-bg: #e8f0fe;
  --assistant-bg: #ffffff;
  --thinking-bg: #f0f0f0;
  --tool-bg: #fafafa;
  --code-bg: #1e1e2e;
  --code-text: #cdd6f4;
  --radius: 8px;
  --shadow: 0 1px 3px rgba(0,0,0,0.08);
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
  background: var(--bg);
  color: var(--text);
  display: flex;
  height: 100vh;
  overflow: hidden;
}

/* ---- 左侧导航栏 ---- */
#sidebar {
  width: var(--sidebar-width);
  min-width: var(--sidebar-width);
  background: var(--sidebar-bg);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

#sidebar-header {
  padding: 16px;
  border-bottom: 1px solid var(--border);
  background: linear-gradient(135deg, #6c5ce7 0%, #a29bfe 100%);
  color: #fff;
}

#sidebar-header h1 {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 4px;
}

#sidebar-header .subtitle {
  font-size: 12px;
  opacity: 0.85;
}

#search-box {
  padding: 8px 16px;
  border-bottom: 1px solid var(--border);
}

#search-box input {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s;
}

#search-box input:focus {
  border-color: var(--primary);
}

#filter-bar {
  padding: 8px 16px;
  border-bottom: 1px solid var(--border);
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.filter-btn {
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: #fff;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
  color: var(--text-secondary);
}

.filter-btn:hover { border-color: var(--primary); color: var(--primary); }
.filter-btn.active { background: var(--primary); color: #fff; border-color: var(--primary); }

#conv-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}

.conv-item {
  padding: 10px 16px;
  cursor: pointer;
  border-left: 3px solid transparent;
  transition: all 0.15s;
}

.conv-item:hover { background: #f5f5ff; }
.conv-item.active { background: #eef0ff; border-left-color: var(--primary); }

.conv-item .conv-title {
  font-size: 13px;
  font-weight: 500;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conv-item .conv-meta {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 3px;
  display: flex;
  gap: 8px;
}

.conv-item .conv-meta .source-tag {
  display: inline-block;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 500;
}

.source-tag.ai { background: #e8f5e9; color: #2e7d32; }
.source-tag.cache { background: #fff3e0; color: #e65100; }
.source-tag.cli { background: #e3f2fd; color: #1565c0; }

/* ---- 右侧内容区 ---- */
#content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

#content-header {
  padding: 16px 32px 16px 48px;
  border-bottom: 1px solid var(--border);
  background: #fff;
}

#content-header h2 {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 6px;
}

#content-header .meta-line {
  font-size: 12px;
  color: var(--text-secondary);
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

#messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 20px 32px 20px 48px;
}

.message {
  margin-bottom: 16px;
  display: flex;
  flex-direction: column;
  content-visibility: auto;
  contain-intrinsic-size: auto 200px;
}

.message.human { align-items: flex-end; }
.message.assistant { align-items: flex-start; }
.message.system { align-items: center; }

.message .msg-header {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 4px;
  padding: 0 4px;
}

.message .msg-body {
  max-width: 85%;
  padding: 14px 18px;
  border-radius: var(--radius);
  line-height: 1.7;
  font-size: 15px;
  box-shadow: var(--shadow);
  word-wrap: break-word;
  overflow-wrap: break-word;
}

.message.human .msg-body {
  background: var(--human-bg);
  border-bottom-right-radius: 2px;
}

.message.assistant .msg-body {
  background: var(--assistant-bg);
  border-bottom-left-radius: 2px;
}

.message.system .msg-body {
  background: #fffde7;
  font-size: 12px;
  color: var(--text-secondary);
  padding: 6px 12px;
}

/* 思考块 */
.thinking-block {
  background: var(--thinking-bg);
  border-left: 3px solid #b0b0b0;
  padding: 8px 12px;
  margin: 8px 0;
  border-radius: 0 var(--radius) var(--radius) 0;
  font-size: 13px;
  color: #555;
}

.thinking-block summary {
  cursor: pointer;
  font-weight: 500;
  color: var(--text-secondary);
  font-size: 12px;
  user-select: none;
}

.thinking-block summary:hover { color: var(--text); }

.thinking-content {
  margin-top: 8px;
  white-space: pre-wrap;
  max-height: 400px;
  overflow-y: auto;
}

/* 工具调用/结果 */
.tool-block {
  background: var(--tool-bg);
  border: 1px solid #e8e8e8;
  border-radius: var(--radius);
  margin: 8px 0;
  overflow: hidden;
}

.tool-block .tool-header {
  padding: 6px 12px;
  background: #f5f5f5;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
  display: flex;
  align-items: center;
  gap: 6px;
}

.tool-block .tool-header:hover { background: #efefef; }

.tool-block .tool-header .tool-icon { font-size: 14px; }

.tool-block .tool-content {
  padding: 8px 12px;
  font-size: 12px;
  max-height: 300px;
  overflow: auto;
  display: none;
}

.tool-block .tool-content pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
}

.tool-block.expanded .tool-content { display: block; }

/* 代码块 */
.msg-body pre {
  background: var(--code-bg);
  color: var(--code-text);
  padding: 12px;
  border-radius: var(--radius);
  overflow-x: auto;
  font-size: 13px;
  line-height: 1.5;
  margin: 8px 0;
}

.msg-body code {
  font-family: "Cascadia Code", "Fira Code", "JetBrains Mono", Consolas, monospace;
}

.msg-body p code {
  background: #f0f0f0;
  padding: 2px 5px;
  border-radius: 3px;
  font-size: 13px;
}

/* Markdown 内容 */
.msg-body p { margin-bottom: 8px; }
.msg-body p:last-child { margin-bottom: 0; }
.msg-body ul, .msg-body ol { padding-left: 20px; margin: 6px 0; }
.msg-body blockquote { border-left: 3px solid #ddd; padding-left: 12px; margin: 8px 0; color: #666; }
.msg-body h1, .msg-body h2, .msg-body h3 { margin: 12px 0 6px; }
.msg-body hr { border: none; border-top: 1px solid #e0e0e0; margin: 12px 0; }
.msg-body img { max-width: 100%; border-radius: 4px; }

/* 表格 */
.msg-body table { border-collapse: collapse; margin: 10px 0; font-size: 13px; width: auto; max-width: 100%; }
.msg-body th, .msg-body td { border: 1px solid #ddd; padding: 6px 10px; text-align: left; }
.msg-body th { background: #f5f5f5; font-weight: 600; white-space: nowrap; }
.msg-body tr:nth-child(even) { background: #fafafa; }

/* 占位提示 */
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-secondary);
  font-size: 15px;
}

/* 滚动条美化 */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #d0d0d0; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #b0b0b0; }

/* 响应式 */
@media (max-width: 768px) {
  #sidebar { width: 240px; min-width: 240px; }
  .message .msg-body { max-width: 95%; }
}

/* ---- 右侧滚动导航条 ---- */
#scroll-nav {
  position: fixed;
  top: 60px;
  right: 12px;
  width: 24px;
  height: calc(100vh - 80px);
  z-index: 100;
  opacity: 0;
  transition: opacity 0.3s;
  overflow: hidden;
}

#scroll-nav.visible {
  opacity: 1;
}

#scroll-nav-track {
  position: relative;
  width: 100%;
  transition: transform 0.3s ease-out;
}

#scroll-nav-track::before {
  content: '';
  position: absolute;
  top: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 3px;
  height: 100%;
  background: rgba(0,0,0,0.06);
  border-radius: 2px;
}

.scroll-dot {
  position: absolute;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--primary-light);
  border: 2px solid #fff;
  box-shadow: 0 1px 3px rgba(0,0,0,0.2);
  cursor: pointer;
  transition: all 0.25s, opacity 0.3s;
  z-index: 1;
  opacity: 1;
}

.scroll-dot.near-edge {
  opacity: 0.3;
}

.scroll-dot:hover {
  width: 18px;
  height: 18px;
  background: var(--primary);
  box-shadow: 0 0 0 3px rgba(108,92,231,0.3), 0 2px 6px rgba(0,0,0,0.2);
  opacity: 1 !important;
}

.scroll-dot.active {
  background: var(--primary);
  box-shadow: 0 0 0 3px rgba(108,92,231,0.3);
  width: 16px;
  height: 16px;
  opacity: 1 !important;
}

.scroll-tooltip {
  position: fixed;
  right: 36px;
  max-width: 280px;
  padding: 8px 12px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: 0 4px 12px rgba(0,0,0,0.12);
  font-size: 12px;
  line-height: 1.5;
  color: var(--text);
  display: none;
  z-index: 200;
  pointer-events: none;
  transform: scale(0.96);
  transition: transform 0.14s ease;
  overflow: hidden;
  text-overflow: ellipsis;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}

.scroll-tooltip.show {
  display: block;
  transform: scale(1);
}

.scroll-tooltip .tooltip-label {
  font-size: 10px;
  color: var(--primary);
  font-weight: 600;
  margin-bottom: 2px;
}
</style>
</head>
<body>

<div id="sidebar">
  <div id="sidebar-header">
    <h1>__SIDEBAR_HEADING__</h1>
    <div class="subtitle">__SIDEBAR_SUBTITLE__</div>
  </div>
  <div id="search-box">
    <input type="text" id="search-input" placeholder="__SEARCH_PLACEHOLDER__">
  </div>
  <div id="filter-bar">
    <button class="filter-btn active" data-filter="all">__FILTER_ALL__</button>
    <button class="filter-btn" data-filter="ai">Claude.ai</button>
    <button class="filter-btn" data-filter="cli">Claude Code</button>
  </div>
  <div id="conv-list"></div>
</div>

<div id="content">
  <div id="content-header" style="display:none">
    <h2 id="header-title"></h2>
    <div class="meta-line" id="header-meta"></div>
  </div>
  <div id="messages-container">
    <div class="empty-state" id="empty-state">__EMPTY_STATE__</div>
  </div>
</div>

<div id="scroll-nav"><div id="scroll-nav-track"></div></div>
<div class="scroll-tooltip" id="scroll-tooltip">
  <div class="tooltip-label"></div>
  <div class="tooltip-text"></div>
</div>

<script>
const I18N = __I18N_PLACEHOLDER__;
</script>
<script>
// ---- 数据（base64 编码，避免特殊字符破坏 HTML） ----
function _decodeB64(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new TextDecoder('utf-8').decode(bytes);
}
const DATA = JSON.parse(_decodeB64("__DATA_PLACEHOLDER__"));
const items = DATA.items;

// ---- marked.js 精简版（内嵌，纯离线可用） ----
// 基于 marked.js 核心功能的精简实现
const MarkedLite = {
  parse(src) {
    if (!src) return '';
    let html = this._escapeHtml(src);
    // 代码块（先处理，避免内部被其他规则误匹配）
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
      return '<pre><code class="language-' + lang + '">' + code.trim() + '</code></pre>';
    });
    // 行内代码
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    // 表格：匹配连续的 | 开头行
    html = html.replace(/((?:^\|.+\|$\n?)+)/gm, (block) => {
      const lines = block.trim().split('\n').filter(l => l.trim());
      if (lines.length < 2) return block;
      // 检查第二行是否是分隔行（|---|---|）
      if (!/^\|[\s\-:|]+\|$/.test(lines[1].trim())) return block;
      const parseCells = (line) => line.split('|').slice(1, -1).map(c => c.trim());
      const headers = parseCells(lines[0]);
      let out = '<table><thead><tr>' + headers.map(h => '<th>' + h + '</th>').join('') + '</tr></thead><tbody>';
      for (let i = 2; i < lines.length; i++) {
        const cells = parseCells(lines[i]);
        out += '<tr>' + cells.map(c => '<td>' + c + '</td>').join('') + '</tr>';
      }
      out += '</tbody></table>';
      return out;
    });
    // 标题
    html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    // 粗体和斜体
    html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    // 链接
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
    // 图片
    html = html.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<img src="$2" alt="$1">');
    // 水平线
    html = html.replace(/^---+$/gm, '<hr>');
    // 引用块
    html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');
    // 合并相邻 blockquote
    html = html.replace(/<\/blockquote>\n<blockquote>/g, '\n');
    // 列表
    html = html.replace(/^\- (.+)$/gm, '<li>$1</li>');
    html = html.replace(/^(\d+)\. (.+)$/gm, '<li>$2</li>');
    html = html.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');
    // 段落
    html = html.replace(/\n\n/g, '</p><p>');
    html = html.replace(/\n/g, '<br>');
    // 包裹
    if (!html.startsWith('<')) html = '<p>' + html + '</p>';
    return html;
  },
  _escapeHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
};

// ---- 全局状态 ----
let currentFilter = 'all';
let currentSearch = '';
let activeUuid = null;

// ---- 工具函数 ----
function formatDate(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts.slice(0, 10);
  return d.toLocaleDateString(I18N["html.locale_tag"], { year: 'numeric', month: '2-digit', day: '2-digit' });
}

function formatTime(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts;
  return d.toLocaleString(I18N["html.locale_tag"]);
}

function sourceLabel(source) {
  if (source === 'online_api') return '<span class="source-tag ai">' + I18N["html.source_online"] + '</span>';
  if (source === 'cache') return '<span class="source-tag cache">' + I18N["html.source_cache"] + '</span>';
  return '<span class="source-tag cli">' + I18N["html.source_cli"] + '</span>';
}

function sourceFilterKey(source) {
  if (source === 'cli_log') return 'cli';
  return 'ai';
}

// ---- 渲染左侧列表 ----
function renderList() {
  const list = document.getElementById('conv-list');
  const filtered = items.filter(item => {
    if (currentFilter !== 'all' && sourceFilterKey(item.source) !== currentFilter) return false;
    if (currentSearch && !item.title.toLowerCase().includes(currentSearch.toLowerCase())) return false;
    return true;
  });

  list.innerHTML = filtered.map(item => {
    const isActive = item.uuid === activeUuid ? ' active' : '';
    const proj = item.project ? ` · ${item.project}` : '';
    return `<div class="conv-item${isActive}" data-uuid="${item.uuid}" onclick="selectItem('${item.uuid}')">
      <div class="conv-title">${_escHtml(item.title)}</div>
      <div class="conv-meta">
        ${sourceLabel(item.source)}
        <span>${formatDate(item.date)}</span>
        <span>${I18N["html.msg_count"].replace("{n}", item.messageCount)}</span>
        <span>${_escHtml(item.model)}</span>
      </div>
    </div>`;
  }).join('');
}

function _escHtml(s) {
  if (!s) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ---- 渲染右侧内容 ----

function selectItem(uuid) {
  activeUuid = uuid;
  const item = items.find(i => i.uuid === uuid);
  if (!item) return;

  // 更新左侧选中状态
  document.querySelectorAll('.conv-item').forEach(el => {
    el.classList.toggle('active', el.dataset.uuid === uuid);
  });

  // 更新 header
  const header = document.getElementById('content-header');
  header.style.display = 'block';
  document.getElementById('header-title').textContent = item.title;
  const proj = item.project ? `<span>${I18N["html.meta_project"]}: ${_escHtml(item.project)}</span>` : '';
  document.getElementById('header-meta').innerHTML = `
    <span>${I18N["html.meta_model"]}: ${_escHtml(item.model)}</span>
    <span>${I18N["html.meta_messages"]}: ${I18N["html.msg_count"].replace("{n}", item.messageCount)}</span>
    ${proj}
    <span>${formatDate(item.date)}</span>
  `;

  // 一次性渲染所有消息（保证 Ctrl+F 搜索可用）
  const container = document.getElementById('messages-container');
  document.getElementById('empty-state')?.remove();
  container.innerHTML = '';
  const frag = document.createDocumentFragment();
  for (const msg of item.messages) {
    const wrapper = document.createElement('div');
    wrapper.innerHTML = renderMessage(msg);
    frag.appendChild(wrapper.firstChild);
  }
  container.appendChild(frag);
  container.scrollTop = 0;

  // 构建滚动导航
  requestAnimationFrame(() => buildScrollNav());
}

// ---- 滚动导航条（可滚动轨道 + 边缘淡出 + 双向同步） ----
const DOT_PITCH = 24; // 每个 dot 的纵向间距
const EDGE_FADE_PX = 50; // 距离边缘多少像素开始淡出

let _navScrollHandler = null;
let _navWheelHandler = null;

function buildScrollNav() {
  const nav = document.getElementById('scroll-nav');
  const track = document.getElementById('scroll-nav-track');
  const tooltip = document.getElementById('scroll-tooltip');

  // 清理旧的事件监听
  const container = document.getElementById('messages-container');
  if (_navScrollHandler) container.removeEventListener('scroll', _navScrollHandler);
  if (_navWheelHandler) nav.removeEventListener('wheel', _navWheelHandler);

  track.innerHTML = '';
  nav.classList.remove('visible');

  const humanMsgs = container.querySelectorAll('.message.human');
  if (humanMsgs.length < 2) return;

  const containerH = container.scrollHeight;
  const navH = nav.clientHeight;
  const dots = [];
  const numDots = humanMsgs.length;

  // 轨道高度：按 dot 数量等比排列，至少和 nav 等高
  const trackH = Math.max(navH, numDots * DOT_PITCH + 20);
  track.style.height = trackH + 'px';

  // 创建 dot 元素，按比例排列在轨道上
  humanMsgs.forEach((msgEl, i) => {
    const ratio = msgEl.offsetTop / containerH;
    const dotTop = 10 + ratio * (trackH - 20);

    const dot = document.createElement('div');
    dot.className = 'scroll-dot';
    dot.style.top = dotTop + 'px';
    dot.dataset.index = i;

    // 用户消息前两行预览
    const msgBody = msgEl.querySelector('.msg-body');
    let preview = '';
    if (msgBody) {
      preview = msgBody.textContent.trim().split('\n').slice(0, 2).join('\n');
      if (preview.length > 120) preview = preview.slice(0, 120) + '...';
    }

    dot.addEventListener('mouseenter', () => {
      const rect = dot.getBoundingClientRect();
      tooltip.style.top = (rect.top - 10) + 'px';
      tooltip.querySelector('.tooltip-label').textContent = I18N["html.tooltip_user_msg"] + (i + 1);
      tooltip.querySelector('.tooltip-text').textContent = preview;
      tooltip.classList.add('show');
    });

    dot.addEventListener('mouseleave', () => {
      tooltip.classList.remove('show');
    });

    dot.addEventListener('click', () => {
      msgEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });

    track.appendChild(dot);
    dots.push({ dot, el: msgEl, dotTop });
  });

  nav.classList.add('visible');

  // ---- 高亮 + 轨道同步 ----
  let scrollRaf = null;
  _navScrollHandler = () => {
    if (scrollRaf) return;
    scrollRaf = requestAnimationFrame(() => {
      const scrollTop = container.scrollTop;
      const viewMid = scrollTop + container.clientHeight / 2;

      // 找最近的 dot
      let closestIdx = 0;
      let closestDist = Infinity;
      dots.forEach((d, i) => {
        const dist = Math.abs(d.el.offsetTop - viewMid);
        if (dist < closestDist) { closestDist = dist; closestIdx = i; }
      });

      // 更新 active 状态
      dots.forEach((d, i) => {
        d.dot.classList.toggle('active', i === closestIdx);
      });

      // 滚动轨道：让 active dot 保持在 nav 可视区域中央
      if (trackH > navH) {
        const activeDotTop = dots[closestIdx].dotTop;
        const navCenter = navH / 2;
        // 目标偏移：让 active dot 在 nav 中央
        let offset = navCenter - activeDotTop;
        // 限制范围：轨道不能滑出 nav
        offset = Math.min(0, Math.max(navH - trackH, offset));
        track.style.transform = `translateY(${offset}px)`;
      }

      // 边缘淡出：距 nav 可视区域顶部/底部 EDGE_FADE_PX 内的 dot 渐隐
      if (trackH > navH) {
        const offset = parseFloat(track.style.transform?.match(/-?[\d.]+/)?.[0] || 0);
        dots.forEach(d => {
          const visibleTop = d.dotTop + offset;
          const distFromTop = visibleTop;
          const distFromBottom = navH - visibleTop;
          const nearEdge = distFromTop < EDGE_FADE_PX || distFromBottom < EDGE_FADE_PX;
          d.dot.classList.toggle('near-edge', nearEdge);
        });
      }

      scrollRaf = null;
    });
  };
  container.addEventListener('scroll', _navScrollHandler);

  // ---- 鼠标滚轮在导航条上 → 滚动对话 ----
  _navWheelHandler = (e) => {
    e.preventDefault();
    container.scrollBy({ top: e.deltaY * 2, behavior: 'auto' });
  };
  nav.addEventListener('wheel', _navWheelHandler, { passive: false });

  // 初始同步
  _navScrollHandler();
}

function renderMessage(msg) {
  const cls = msg.sender === 'human' ? 'human' : msg.sender === 'system' ? 'system' : 'assistant';
  const label = msg.sender === 'human' ? I18N["renderer.role_me"] : msg.sender === 'system' ? I18N["html.role_system"] : I18N["renderer.role_claude"];
  const ts = formatTime(msg.ts);

  const body = msg.blocks.map(renderBlock).join('');

  return `<div class="message ${cls}">
    <div class="msg-header">${label} —— ${ts}</div>
    <div class="msg-body">${body}</div>
  </div>`;
}

function renderBlock(block) {
  switch (block.type) {
    case 'text':
      return MarkedLite.parse(block.text);
    case 'thinking':
      return `<details class="thinking-block">
        <summary>${I18N["html.thinking_summary"]}</summary>
        <div class="thinking-content">${_escHtml(block.thinking)}</div>
      </details>`;
    case 'tool_use':
      const inputStr = typeof block.input === 'string' ? block.input : JSON.stringify(block.input, null, 2);
      return `<div class="tool-block">
        <div class="tool-header" onclick="this.parentElement.classList.toggle('expanded')">
          <span class="tool-icon">&#9881;</span>
          ${I18N["html.tool_call_label"]} ${_escHtml(block.name)}
        </div>
        <div class="tool-content"><pre>${_escHtml(inputStr)}</pre></div>
      </div>`;
    case 'tool_result':
      const errCls = block.is_error ? ' style="color:#c62828"' : '';
      return `<div class="tool-block">
        <div class="tool-header" onclick="this.parentElement.classList.toggle('expanded')">
          <span class="tool-icon">&#8635;</span>
          ${block.is_error ? I18N["html.tool_result_error_label"] : I18N["html.tool_result_label"]} ${_escHtml(block.name)}
        </div>
        <div class="tool-content"${errCls}><pre>${_escHtml(block.content)}</pre></div>
      </div>`;
    case 'image':
      if (block.data_uri) {
        const alt = block.file_name ? _escHtml(block.file_name) : I18N["html.image_alt"];
        return `<div style="margin:8px 0"><img src="${block.data_uri}" alt="${alt}" style="max-width:100%;max-height:500px;border-radius:6px;cursor:pointer" onclick="window.open(this.src)" title="点击放大"></div>`;
      }
      return `<p><em>${I18N["html.image_placeholder"]}</em></p>`;
    case 'pdf':
      if (block.rel_path) {
        const pdfName = block.file_name ? _escHtml(block.file_name) : I18N["html.pdf_alt"];
        return `<div style="margin:8px 0">
          <a href="${block.rel_path}" target="_blank" rel="noopener"
             style="display:inline-flex;align-items:center;gap:6px;padding:8px 14px;background:#fff;border:1px solid #e0e0e0;border-radius:8px;text-decoration:none;color:#333;font-size:14px;box-shadow:0 1px 3px rgba(0,0,0,0.08);transition:all 0.2s"
             onmouseover="this.style.borderColor='#6c5ce7';this.style.boxShadow='0 2px 8px rgba(108,92,231,0.2)'"
             onmouseout="this.style.borderColor='#e0e0e0';this.style.boxShadow='0 1px 3px rgba(0,0,0,0.08)'">
            <span style="font-size:20px">&#128196;</span>
            <span>${pdfName}</span>
            <span style="font-size:11px;color:#999;margin-left:4px">${I18N["html.pdf_open_hint"]}</span>
          </a>
        </div>`;
      }
      return `<p><em>[${I18N["html.pdf_alt"]}: ${_escHtml(block.file_name || I18N["html.doc_fallback"])}]</em></p>`;
    case 'attachment':
      const ext = (block.file_type || '').toLowerCase();
      const isText = ['txt','srt','csv','json','xml','yaml','yml','md','py','js','ts','html','css','sh','bat','log'].includes(ext);
      if (isText && block.content) {
        return `<div class="tool-block">
          <div class="tool-header" onclick="this.parentElement.classList.toggle('expanded')">
            <span class="tool-icon">&#128196;</span>
            ${I18N["html.attachment_label"]} ${_escHtml(block.name)} (${ext})
          </div>
          <div class="tool-content" style="max-height:400px"><pre>${_escHtml(block.content)}</pre></div>
        </div>`;
      }
      return `<p><em>${I18N["html.attachment_label"]}: ${_escHtml(block.name)}</em></p>`;
    default:
      return `<p><em>[${_escHtml(block.type)}]</em></p>`;
  }
}

// ---- 筛选和搜索 ----
document.getElementById('filter-bar').addEventListener('click', e => {
  if (!e.target.classList.contains('filter-btn')) return;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  e.target.classList.add('active');
  currentFilter = e.target.dataset.filter;
  renderList();
});

document.getElementById('search-input').addEventListener('input', e => {
  currentSearch = e.target.value;
  renderList();
});

// ---- 初始化 ----
renderList();
if (items.length > 0) {
  selectItem(items[0].uuid);
}
</script>
</body>
</html>
'''

if __name__ == "__main__":
    from .config import get_backup_dir
    backup_dir = get_backup_dir()
    p = generate_html(backup_dir, print)
    print(f"生成完成: {p}")
