"""Mode C —— Claude Code 本地 .jsonl 会话日志导出。

从 `~/.claude/projects/*/session.jsonl` 读事件流，聚合成 Session 结构。
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Literal

from .paths import claude_cli_projects_dir_optional

Category = Literal["real", "observer"]


@dataclass
class SessionData:
    """一个 Claude Code session 的所有事件 + 派生元数据。"""
    project: str            # 项目名（由 cwd 的 basename 得出）
    category: Category      # "real" 或 "observer"
    session_id: str
    cwd: str
    model: str
    version: str
    first_ts: str | None
    last_ts: str | None
    user_turns: int
    assistant_turns: int
    total_events: int
    events: list[dict]
    source_path: Path       # 原始 .jsonl 路径（Mode C 要硬链接它）
    title: str = ""


def categorize(project_dir_name: str) -> Category | None:
    """返回该目录应归类到哪里，或 None 表示跳过（公司测试）。"""
    if project_dir_name.startswith("-private-tmp-diag-"):
        return None
    if project_dir_name.startswith("-private-tmp-mcp-timing"):
        return None
    if "claude-mem-observer-sessions" in project_dir_name:
        return "observer"
    return "real"


def _derive_title(events: list[dict]) -> str:
    # 优先用 summary 事件
    for e in events:
        if e.get("type") == "summary" and e.get("summary"):
            return str(e["summary"])
    # 否则用第一条 user 消息的第一行
    for e in events:
        if e.get("type") != "user":
            continue
        msg = e.get("message") or {}
        c = msg.get("content")
        if isinstance(c, str) and c.strip():
            return c.strip().splitlines()[0]
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "text":
                    t = (b.get("text") or "").strip()
                    if t:
                        return t.splitlines()[0]
    return "(无用户输入)"


def parse_session(path: Path, category: Category, project: str) -> SessionData | None:
    """流式读一个 .jsonl 文件，返回 SessionData。读不下来返回 None。"""
    events: list[dict] = []
    session_id = cwd = model = version = ""
    first_ts = last_ts = None
    user_count = asst_count = 0

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
                cwd = cwd or d.get("cwd", "")
                version = version or d.get("version", "")
                ts = d.get("timestamp") or (d.get("message") or {}).get("timestamp")
                if ts:
                    first_ts = first_ts or ts
                    last_ts = ts
                t = d.get("type")
                if t == "user":
                    user_count += 1
                elif t == "assistant":
                    asst_count += 1
                    m = (d.get("message") or {})
                    model = model or m.get("model") or ""
    except OSError:
        return None

    sd = SessionData(
        project=project,
        category=category,
        session_id=session_id,
        cwd=cwd,
        model=model,
        version=version,
        first_ts=first_ts,
        last_ts=last_ts,
        user_turns=user_count,
        assistant_turns=asst_count,
        total_events=len(events),
        events=events,
        source_path=path,
    )
    sd.title = _derive_title(events)
    return sd


def iter_sessions() -> Iterator[SessionData]:
    """流式遍历所有真实 + observer 会话，跳过 diag / mcp-timing。"""
    projects_dir = claude_cli_projects_dir_optional()
    if projects_dir is None:
        return
    for proj_dir in sorted(projects_dir.iterdir()):
        if not proj_dir.is_dir():
            continue
        cat = categorize(proj_dir.name)
        if cat is None:
            continue
        sessions = sorted(proj_dir.glob("*.jsonl"))
        if not sessions:
            continue
        # 项目名：读第一个 session 的 cwd，取 basename
        project_name = proj_dir.name  # fallback
        try:
            with open(sessions[0], encoding="utf-8") as fp:
                for line in fp:
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if d.get("cwd"):
                        project_name = os.path.basename(d["cwd"].rstrip("/"))
                        break
        except OSError:
            pass

        for sp in sessions:
            sd = parse_session(sp, cat, project_name)
            if sd:
                yield sd


def count_sessions() -> dict[str, int]:
    """快速统计（不解析内容），给 GUI / 启动日志用。"""
    projects_dir = claude_cli_projects_dir_optional()
    if projects_dir is None:
        return {"real": 0, "observer": 0, "skipped_test": 0}
    r = {"real": 0, "observer": 0, "skipped_test": 0}
    for proj_dir in projects_dir.iterdir():
        if not proj_dir.is_dir():
            continue
        n = sum(1 for _ in proj_dir.glob("*.jsonl"))
        cat = categorize(proj_dir.name)
        if cat is None:
            r["skipped_test"] += n
        else:
            r[cat] += n
    return r


if __name__ == "__main__":
    counts = count_sessions()
    print(f"Sessions: real={counts['real']}, observer={counts['observer']}, "
          f"skipped_test={counts['skipped_test']}")
    c = 0
    for s in iter_sessions():
        c += 1
        if c <= 3:
            print(f"  [{s.category}] {s.project} · {s.title[:40]} · "
                  f"{s.user_turns}U/{s.assistant_turns}A · {s.total_events} events")
    print(f"Total parsed: {c}")
