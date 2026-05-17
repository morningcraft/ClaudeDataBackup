"""CLI 入口 —— 编排 Mode A/B/C，合并结果，写 Markdown + JSON/JSONL 输出。

用法：
    claude-data-backup --output ~/Desktop/my-export              # 一次性导出
    claude-data-backup --incremental                              # 增量备份
    claude-data-backup --incremental --mode a                     # 只增量 Mode A
    claude-data-backup --set-backup-dir ~/my-backup               # 修改备份目录
    claude-data-backup --mode bc                                  # 只跑 Mode B 和 Mode C
"""
from __future__ import annotations
import argparse
import json
import sys
import traceback
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import __version__
from . import paths
from . import cookies
from . import cache_extractor
from . import cli_exporter
from . import renderer
from . import config as cfg
from . import manifest as mf
from .i18n import t as _, init_language, save_language_preference
from .log import setup_logging, get_logger
from .html_viewer import generate_html as generate_html_viewer
from .api_fetcher import ApiFetcher, ApiError
from .file_extractor import extract_all_files

log = get_logger(__name__)


def _default_output_dir() -> Path:
    date = datetime.now().strftime("%Y-%m-%d")
    return Path.home() / "Desktop" / f"ClaudeDataBackup-{date}"


def _emit(msg: str, verbose: bool, always: bool = False) -> None:
    if verbose or always:
        print(msg, flush=True)


# ---------- 三模式执行 ----------

def run_mode_a(output_root: Path, logger: Callable[[str], None]) -> tuple[dict[str, dict], dict]:
    """返回 (uuid → conversation, stats)。"""
    logger(_("main.mode_a_trying"))
    sk = cookies.get_session_key()
    if not sk:
        logger(_("main.mode_a_no_key"))
        return {}, {"status": "skipped", "reason": _("main.mode_a_skipped_no_key")}

    fetcher = ApiFetcher(sk)
    logger(_("main.mode_a_checking"))
    if not fetcher.probe():
        logger(_("main.mode_a_invalid"))
        return {}, {"status": "skipped", "reason": _("main.mode_a_skipped_invalid")}

    orgs = fetcher.list_organizations()
    if not orgs:
        logger(_("main.mode_a_no_org"))
        return {}, {"status": "skipped", "reason": _("main.mode_a_skipped_no_org")}

    org_uuid = orgs[0]["uuid"]
    logger(_("main.mode_a_login_ok", org=org_uuid[:8]))

    raw_dir = output_root / "_raw" / "mode_a"
    convs: dict[str, dict] = {}

    def progress(idx, total, name):
        logger(f"[Mode A] {idx+1}/{total}: {name[:50]}")

    try:
        for conv in fetcher.stream_all(org_uuid, save_dir=raw_dir, progress=progress):
            if "uuid" in conv:
                convs[conv["uuid"]] = conv
    except ApiError as e:
        logger(_("main.mode_a_fetch_error", error=str(e)))

    # 也把 projects 抓回来，供后续渲染用
    try:
        projects = fetcher.list_projects(org_uuid)
        (raw_dir / "_projects.json").write_text(
            json.dumps(projects, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except ApiError:
        pass

    return convs, {"status": "ok", "count": len(convs), "org_uuid": org_uuid}


def run_mode_b(logger: Callable[[str], None]) -> tuple[dict[str, dict], dict]:
    logger(_("main.mode_b_scanning"))
    try:
        cache_dir = paths.claude_desktop_cache_dir()
    except FileNotFoundError as e:
        logger(_("main.mode_b_no_dir", error=str(e)))
        return {}, {"status": "skipped", "reason": str(e)}

    def progress(idx, total):
        if idx == 0 or idx == total or idx % 500 == 0:
            logger(_("main.mode_b_progress", idx=idx, total=total))

    convs = cache_extractor.extract_conversations(cache_dir, progress=progress)
    logger(_("main.mode_b_result", count=len(convs)))
    return convs, {"status": "ok", "cached_total": len(convs)}


def run_mode_c(logger: Callable[[str], None]) -> tuple[list[cli_exporter.SessionData], dict]:
    projects_dir = paths.claude_cli_projects_dir_optional()
    if projects_dir is None:
        logger(_("main.mode_c_no_dir"))
        return [], {"status": "skipped", "reason": _("main.mode_c_skipped_no_dir")}

    counts = cli_exporter.count_sessions()
    logger(_("main.mode_c_prepare", real=counts['real'],
             observer=counts['observer'], test=counts['skipped_test']))

    sessions: list[cli_exporter.SessionData] = []
    for idx, s in enumerate(cli_exporter.iter_sessions(skip_observer=True)):
        sessions.append(s)
        if (idx + 1) % 50 == 0:
            logger(_("main.mode_c_parsing", idx=idx + 1))
    logger(_("main.mode_c_total", count=len(sessions)))
    return sessions, {"status": "ok",
                      "real": sum(1 for s in sessions if s.category == "real")}


# ---------- 写出 ----------

def write_desktop_conversations(out_root: Path,
                                 combined: dict[str, tuple[str, dict]],
                                 logger: Callable[[str], None]) -> list[dict]:
    """combined: uuid → (source_label, conv)。source_label 例如 "在线 API（完整）"。"""
    base = out_root / "desktop-conversations"
    (base / "projects").mkdir(parents=True, exist_ok=True)
    (base / "unassigned").mkdir(exist_ok=True)

    index_rows: list[dict] = []

    for uuid, (source_label, conv) in combined.items():
        name = conv.get("name") or _("renderer.unnamed")
        date = renderer.iso_to_date(conv.get("created_at"))
        project = (conv.get("project") or {}).get("name") if conv.get("project") else None

        proj_dir = (base / "projects" / renderer.safe_name(project, 60)
                    if project else base / "unassigned")
        proj_dir.mkdir(parents=True, exist_ok=True)

        stem = f"{date}__{renderer.safe_name(name, 80)}"
        md_path = proj_dir / f"{stem}.md"
        json_path = proj_dir / f"{stem}.json"
        # 避免同名：附上 uuid 前缀
        if md_path.exists():
            stem = f"{stem}__{uuid[:8]}"
            md_path = proj_dir / f"{stem}.md"
            json_path = proj_dir / f"{stem}.json"

        md_path.write_text(renderer.render_desktop_conversation(conv, source_label), encoding="utf-8")
        json_path.write_text(json.dumps(conv, ensure_ascii=False, indent=2), encoding="utf-8")

        index_rows.append({
            "date": date, "name": name, "project": project or "-",
            "messages": len(conv.get("chat_messages", [])),
            "model": conv.get("model", ""),
            "source": source_label,
            "path": str(md_path.relative_to(base)),
        })

    # 写索引
    index_rows.sort(key=lambda r: r["date"], reverse=True)
    idx_lines = [
        f"# {_('renderer.desktop_index_title')}",
        "",
        _("renderer.desktop_index_count", count=len(index_rows)),
        "",
        f"| {_('renderer.columns_date')} | {_('renderer.columns_title')} | {_('renderer.columns_project')} | {_('renderer.columns_messages')} | {_('renderer.columns_model')} | {_('renderer.columns_source')} | {_('renderer.columns_file')} |",
        "|---|---|---|--:|---|---|---|",
    ]
    for r in index_rows:
        idx_lines.append(
            f"| {r['date']} | {r['name']} | {r['project']} | {r['messages']} | "
            f"`{r['model']}` | {r['source']} | [{_('renderer.open')}]({r['path']}) |"
        )
    (base / "00_index.md").write_text("\n".join(idx_lines), encoding="utf-8")
    logger(_("main.write_desktop", count=len(index_rows)))
    return index_rows


def write_cli_sessions(out_root: Path,
                        sessions: list[cli_exporter.SessionData],
                        logger: Callable[[str], None]) -> int:
    base = out_root / "claude-code"
    real_dir = base / "real"
    real_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []

    for s in sessions:
        proj_out = real_dir / renderer.safe_name(s.project, 80)
        proj_out.mkdir(parents=True, exist_ok=True)
        date = renderer.iso_to_date(s.first_ts)
        stem = f"{date}__{renderer.safe_name(s.title, 80)}__{s.session_id[:8]}"
        md_path = proj_out / f"{stem}.md"
        jsonl_path = proj_out / f"{stem}.jsonl"
        md_path.write_text(renderer.render_cli_session(s), encoding="utf-8")
        renderer.hardlink_or_copy(s.source_path, jsonl_path)

        rows.append({
            "date": date, "project": s.project, "title": s.title,
            "user_turns": s.user_turns, "asst_turns": s.assistant_turns,
            "events": s.total_events, "model": s.model,
            "path": str(md_path.relative_to(base)),
        })

    rows.sort(key=lambda r: (r["project"], r["date"]), reverse=True)
    lines = [
        f"# {_('renderer.cli_index_title')}",
        "",
        _("renderer.cli_index_count", count=len(rows)),
        _("renderer.cli_index_desc"),
        "",
        f"| {_('renderer.columns_date')} | {_('renderer.columns_project')} | {_('renderer.columns_title')} | User/Asst Turns | Events | {_('renderer.columns_model')} | {_('renderer.columns_file')} |",
        "|---|---|---|--:|--:|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['date']} | {r['project']} | {r['title'][:60]} | "
            f"{r['user_turns']}/{r['asst_turns']} | {r['events']} | "
            f"`{r['model']}` | [{_('renderer.open')}]({r['path']}) |"
        )
    (base / "00_index.md").write_text("\n".join(lines), encoding="utf-8")
    logger(_("main.write_cli", count=len(rows)))
    return len(rows)


# ---------- 主入口 ----------

def run(output_dir: Path, modes: str, logger: Callable[[str], None]) -> dict:
    """主流程。返回 stats dict。"""
    log.info("run() 开始: output=%s, modes=%s", output_dir, modes)
    output_dir.mkdir(parents=True, exist_ok=True)
    when = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stats: dict = {
        "version": __version__,
        "run_time": when,
        "source_platform": paths.detect_platform(),
        "output_dir": str(output_dir),
    }

    a_convs: dict[str, dict] = {}
    b_convs: dict[str, dict] = {}
    c_sessions: list[cli_exporter.SessionData] = []

    if "a" in modes:
        a_convs, stats["mode_a"] = run_mode_a(output_dir, logger)
    else:
        stats["mode_a"] = {"status": "skipped", "reason": _("main.mode_a_skipped_user")}

    if "b" in modes:
        b_convs, stats["mode_b"] = run_mode_b(logger)
    else:
        stats["mode_b"] = {"status": "skipped", "reason": _("main.mode_b_skipped_user")}

    if "c" in modes:
        c_sessions, stats["mode_c"] = run_mode_c(logger)
    else:
        stats["mode_c"] = {"status": "skipped", "reason": _("main.mode_c_skipped_user")}

    # 合并 A + B：A 优先
    combined: dict[str, tuple[str, dict]] = {}
    for uuid, conv in a_convs.items():
        combined[uuid] = (_("main.combined_source_api"), conv)
    new_from_b = 0
    for uuid, conv in b_convs.items():
        if uuid not in combined:
            combined[uuid] = (_("main.combined_source_cache"), conv)
            new_from_b += 1
    stats["mode_b"]["new_unique_to_b"] = new_from_b

    # 写出
    if combined:
        write_desktop_conversations(output_dir, combined, logger)
    if c_sessions:
        write_cli_sessions(output_dir, c_sessions, logger)

    # 提取文件附件
    sk = cookies.get_session_key()
    file_map = extract_all_files(output_dir, session_key=sk, logger=logger)

    # 顶层索引 + STATS
    (output_dir / "INDEX.md").write_text(
        renderer.render_top_index(stats, when), encoding="utf-8"
    )
    (output_dir / "STATS.md").write_text(
        renderer.render_stats_report(stats, when), encoding="utf-8"
    )
    generate_html_viewer(output_dir, logger, file_map=file_map)
    logger(_("main.complete_output", dir=str(output_dir)))
    return stats


# ---------- 增量备份 ----------

def _incremental_mode_a(backup_dir: Path, manifest: dict,
                         logger: Callable[[str], None]) -> tuple[dict[str, dict], dict]:
    """增量 Mode A：只抓新的或更新的对话。返回 (uuid→conv, stats)。"""
    logger(_("main.mode_a_trying"))
    sk = cookies.get_session_key()
    if not sk:
        logger(_("main.mode_a_no_key"))
        return {}, {"status": "skipped", "reason": _("main.mode_a_skipped_no_key")}

    fetcher = ApiFetcher(sk)
    if not fetcher.probe():
        logger(_("main.mode_a_invalid"))
        return {}, {"status": "skipped", "reason": _("main.mode_a_skipped_invalid")}

    orgs = fetcher.list_organizations()
    if not orgs:
        logger(_("main.mode_a_no_org"))
        return {}, {"status": "skipped", "reason": _("main.mode_a_skipped_no_org")}

    org_uuid = orgs[0]["uuid"]
    logger(_("main.mode_a_login_ok", org=org_uuid[:8]))

    # 构建 skip_map：uuid → updated_at
    skip_map: dict[str, str] = {}
    for uuid, meta in manifest["conversations"].items():
        if meta.get("source") in ("online_api", "cache+api"):
            skip_map[uuid] = meta.get("updated_at", "")

    raw_dir = backup_dir / "_raw" / "mode_a"
    convs: dict[str, dict] = {}
    new_count = 0
    updated_count = 0

    def progress(idx, total, name):
        logger(f"[Mode A] {idx+1}/{total}: {name[:50]}")

    try:
        for conv in fetcher.stream_all(org_uuid, save_dir=raw_dir,
                                       progress=progress, skip_map=skip_map):
            uuid = conv.get("uuid")
            if not uuid:
                continue
            convs[uuid] = conv
            if uuid in skip_map:
                updated_count += 1
            else:
                new_count += 1
    except ApiError as e:
        logger(_("main.mode_a_fetch_error", error=str(e)))

    logger(_("main.mode_a_new_count", new=new_count, updated=updated_count))

    # 抓 projects
    try:
        projects = fetcher.list_projects(org_uuid)
        (raw_dir / "_projects.json").write_text(
            json.dumps(projects, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except ApiError:
        pass

    return convs, {"status": "ok", "count": len(convs),
                    "new": new_count, "updated": updated_count,
                    "org_uuid": org_uuid}


def _incremental_mode_b(manifest: dict,
                         logger: Callable[[str], None]) -> tuple[dict[str, dict], dict]:
    """增量 Mode B：扫描缓存，只返回 manifest 中没有的对话。"""
    logger(_("main.mode_b_scanning"))
    try:
        cache_dir = paths.claude_desktop_cache_dir()
    except FileNotFoundError as e:
        logger(_("main.mode_b_no_dir", error=str(e)))
        return {}, {"status": "skipped", "reason": str(e)}

    def progress(idx, total):
        if idx == 0 or idx == total or idx % 500 == 0:
            logger(_("main.mode_b_progress", idx=idx, total=total))

    all_convs = cache_extractor.extract_conversations(cache_dir, progress=progress)

    # 只保留 manifest 中没有的（或者 source 是 cache 的可以被 api 覆盖）
    new_convs: dict[str, dict] = {}
    for uuid, conv in all_convs.items():
        existing = manifest["conversations"].get(uuid)
        if not existing:
            new_convs[uuid] = conv
        elif existing.get("source") == "cache" and existing.get("updated_at") != conv.get("updated_at", ""):
            new_convs[uuid] = conv

    logger(_("main.mode_b_new", total=len(all_convs), new=len(new_convs)))
    return new_convs, {"status": "ok", "cached_total": len(all_convs),
                        "new": len(new_convs)}


def _incremental_mode_c(backup_dir: Path, manifest: dict,
                         logger: Callable[[str], None]) -> tuple[list[cli_exporter.SessionData], dict]:
    """增量 Mode C：扫描会话，只返回 manifest 中没有的。"""
    projects_dir = paths.claude_cli_projects_dir_optional()
    if projects_dir is None:
        logger(_("main.mode_c_no_dir"))
        log.info(_("main.mode_c_no_dir"))
        return [], {"status": "skipped", "reason": _("main.mode_c_skipped_no_dir")}

    counts = cli_exporter.count_sessions()
    msg = _("main.mode_c_prepare", real=counts['real'],
            observer=counts['observer'], test=counts['skipped_test'])
    logger(msg)
    log.info(msg)

    new_sessions: list[cli_exporter.SessionData] = []
    for s in cli_exporter.iter_sessions(skip_observer=True):
        if not mf.needs_session_update(manifest, s.session_id, s.last_ts or "",
                                     backup_dir=backup_dir):
            continue
        new_sessions.append(s)

    msg = _("main.mode_c_new", count=len(new_sessions))
    logger(msg)
    log.info(msg)
    return new_sessions, {"status": "ok", "new": len(new_sessions),
                           "real": sum(1 for s in new_sessions if s.category == "real")}


def run_incremental(backup_dir: Path, modes: str,
                    logger: Callable[[str], None]) -> dict:
    """增量备份主流程。

    1. 加载 manifest
    2. 按 modes 执行各模式，只抓新的/更新的
    3. 写出到 backup_dir（覆盖更新的文件，新增新文件）
    4. 更新 manifest
    """
    log.info("run_incremental() 开始: dir=%s, modes=%s", backup_dir, modes)
    backup_dir.mkdir(parents=True, exist_ok=True)
    manifest = mf.load_manifest(backup_dir)
    when = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stats: dict = {
        "version": __version__,
        "run_time": when,
        "mode": "incremental",
        "source_platform": paths.detect_platform(),
        "backup_dir": str(backup_dir),
    }

    a_convs: dict[str, dict] = {}
    b_convs: dict[str, dict] = {}
    c_sessions: list[cli_exporter.SessionData] = []

    if "a" in modes:
        a_convs, stats["mode_a"] = _incremental_mode_a(backup_dir, manifest, logger)
    else:
        stats["mode_a"] = {"status": "skipped", "reason": _("main.mode_a_skipped_user")}

    if "b" in modes:
        b_convs, stats["mode_b"] = _incremental_mode_b(manifest, logger)
    else:
        stats["mode_b"] = {"status": "skipped", "reason": _("main.mode_b_skipped_user")}

    if "c" in modes:
        c_sessions, stats["mode_c"] = _incremental_mode_c(backup_dir, manifest, logger)
    else:
        stats["mode_c"] = {"status": "skipped", "reason": _("main.mode_c_skipped_user")}

    # 合并 A + B：A 优先
    api_label = _("main.combined_source_api")
    cache_label = _("main.combined_source_cache")
    combined: dict[str, tuple[str, dict]] = {}
    for uuid, conv in a_convs.items():
        combined[uuid] = (api_label, conv)
    new_from_b = 0
    for uuid, conv in b_convs.items():
        if uuid not in combined:
            combined[uuid] = (cache_label, conv)
            new_from_b += 1
    stats["mode_b"]["new_unique_to_b"] = new_from_b

    # 写出
    if combined:
        write_desktop_conversations(backup_dir, combined, logger)
        # 注册到 manifest
        for uuid, (source_label, conv) in combined.items():
            mf.register_conversation(manifest, uuid, {
                "title": conv.get("name", ""),
                "updated_at": conv.get("updated_at", ""),
                "message_count": len(conv.get("chat_messages", [])),
                "model": conv.get("model", ""),
                "project": (conv.get("project") or {}).get("name") if conv.get("project") else None,
                "source": "online_api" if source_label == api_label else "cache",
                "file": f"desktop-conversations/{uuid}",
            })

    if c_sessions:
        write_cli_sessions(backup_dir, c_sessions, logger)
        for s in c_sessions:
            mf.register_cli_session(manifest, s.session_id, {
                "title": s.title,
                "project": s.project,
                "category": s.category,
                "first_ts": s.first_ts or "",
                "last_ts": s.last_ts or "",
                "source": "cli_log",
                "file": f"claude-code/{s.category}/{s.project}",
            })

    # 保存 manifest
    mf.save_manifest(backup_dir, manifest)

    # 提取文件附件
    sk = cookies.get_session_key()
    file_map = extract_all_files(backup_dir, session_key=sk, logger=logger)

    # 顶层索引
    (backup_dir / "INDEX.md").write_text(
        renderer.render_top_index(stats, when), encoding="utf-8"
    )
    (backup_dir / "STATS.md").write_text(
        renderer.render_stats_report(stats, when), encoding="utf-8"
    )

    # 更新配置中的 last_run
    s = mf.summary(manifest)
    cfg.update_last_run({
        "mode_a": stats["mode_a"].get("count", 0),
        "mode_b": stats["mode_b"].get("cached_total", 0),
        "mode_c": stats["mode_c"].get("real", 0),
        "conversation_total": s["conversation_count"],
        "session_total": s["session_count"],
    })

    generate_html_viewer(backup_dir, logger, file_map=file_map)
    logger(_("main.complete_incremental", dir=str(backup_dir)))
    return stats


def _handle_schedule(action: str, args):
    """处理 --schedule 子命令。"""
    from .scheduler import (
        ScheduleConfig,
        schedule_config_path,
        get_next_run_time,
    )
    from .autobackup_daemon import is_daemon_running, read_status

    if action == "install":
        config = ScheduleConfig.load(schedule_config_path())
        if not config.enabled:
            print(_("schedule.skipped_disabled"))
            print(_("cli.schedule_hint_enable"))
            return

        if paths.detect_platform() == "mac":
            from .scheduler_mac import install as plat_install
            ok = plat_install(config, config.time_trigger.interval_hours * 3600)
        elif paths.detect_platform() == "win":
            from .scheduler_win import install as plat_install
            ok = plat_install(config, config.time_trigger.interval_hours)
        else:
            print(_("cli.schedule_unsupported_platform"))
            return

        if ok:
            print(_("schedule.installed", path=str(schedule_config_path())))
        else:
            print(_("schedule.install_failed", error="see log"))

    elif action == "uninstall":
        if paths.detect_platform() == "mac":
            from .scheduler_mac import uninstall as plat_uninstall
            plat_uninstall()
        elif paths.detect_platform() == "win":
            from .scheduler_win import uninstall as plat_uninstall
            plat_uninstall()
        print(_("schedule.uninstalled"))

    elif action == "status":
        st: dict = {"platform": paths.detect_platform()}
        if paths.detect_platform() == "mac":
            from .scheduler_mac import status as plat_status
            st = plat_status()
        elif paths.detect_platform() == "win":
            from .scheduler_win import status as plat_status
            st = plat_status()

        config = ScheduleConfig.load(schedule_config_path())
        next_run = get_next_run_time(config)
        from datetime import datetime
        print(f"  平台: {st.get('platform', '?')}")
        print(f"  启用: {config.enabled}")
        print(f"  daemon 已安装: {st.get('daemon_installed', False)}")
        print(f"  daemon 运行中: {st.get('daemon_running', False)}")
        print(f"  定时触发: {config.time_trigger.type} / {config.time_trigger.interval_hours}h")
        print(f"  Claude 关闭触发: {config.condition_triggers.on_claude_close}")
        print(f"  Claude 启动触发: {config.condition_triggers.on_claude_start}")
        print(f"  最小间隔: {config.min_interval_minutes}m")
        if next_run:
            print(_("schedule.next_run",
                     time=datetime.fromtimestamp(next_run).strftime("%Y-%m-%d %H:%M")))
        st_file = read_status()
        if st_file:
            print(f"\n  [daemon 状态]")
            print(f"  上次检查: {st_file.get('last_check', 'N/A')}")
            print(f"  上次备份: {st_file.get('last_backup', 'N/A')}")
            print(f"  Claude 运行中: {st_file.get('claude_running', 'N/A')}")

    elif action == "run":
        # 兼容旧版：直接跑 daemon
        from .autobackup_daemon import run_daemon
        run_daemon()


def main():
    init_language(cfg.get_backup_dir())
    setup_logging()
    log.info("=== ClaudeDataBackup CLI v%s 启动 ===", __version__)

    # Windows cmd 默认 GBK 编码，中文输出会乱码
    if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
        log.info("stdout 编码 %s，尝试切换 UTF-8", sys.stdout.encoding)
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception as e:
            log.warning("stdout 编码切换失败: %s", e)

    ap = argparse.ArgumentParser(
        description=_("cli.description")
    )
    ap.add_argument("--output", type=Path, default=None,
                    help=_("cli.output_help"))
    ap.add_argument("--incremental", "-i", action="store_true",
                    help=_("cli.incremental_help"))
    ap.add_argument("--set-backup-dir", type=Path, default=None,
                    help=_("cli.set_dir_help"))
    ap.add_argument("--mode", default="abc",
                    help=_("cli.mode_help"))
    ap.add_argument("--verbose", "-v", action="store_true", help=_("cli.verbose_help"))
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    ap.add_argument("--schedule", choices=["install", "uninstall", "status", "run"],
                    default=None, help=_("cli.schedule_help"))
    args = ap.parse_args()
    log.info("参数: output=%s, incremental=%s, mode=%s, set_backup_dir=%s, schedule=%s",
             args.output, args.incremental, args.mode, args.set_backup_dir, args.schedule)

    # ── schedule 子命令 ──
    if args.schedule:
        _handle_schedule(args.schedule, args)
        return

    # 设置备份目录
    if args.set_backup_dir:
        cfg.set_backup_dir(args.set_backup_dir)
        print(_("cli.dir_set", dir=str(args.set_backup_dir)))
        if not args.incremental and args.output is None:
            return  # 只设置目录，不做备份

    modes = args.mode.lower()
    if not any(c in modes for c in "abc"):
        log.error("--mode 至少要包含 a/b/c 中的一个: %s", args.mode)
        print(_("cli.mode_error"), file=sys.stderr)
        sys.exit(2)

    def logger(msg):
        print(msg, flush=True)

    try:
        if args.incremental:
            backup_dir = cfg.get_backup_dir()
            log.info("增量备份目录: %s", backup_dir)
            stats = run_incremental(backup_dir, modes, logger)
            save_language_preference(backup_dir)
        else:
            out = args.output or _default_output_dir()
            log.info("一次性导出目录: %s", out)
            stats = run(out, modes, logger)
            save_language_preference(out)
    except Exception:
        log.critical("CLI 执行失败", exc_info=True)
        traceback.print_exc()
        sys.exit(1)

    # 最后的汇总
    log.info("CLI 执行完成: %s", stats)
    print("\n" + _("cli.summary_header"))
    if args.incremental:
        print(_("cli.mode_incremental"))
        print(_("cli.dir_label", dir=str(cfg.get_backup_dir())))
    else:
        print(_("cli.mode_full"))
    print(f"Mode A: {stats['mode_a'].get('status')}"
          f" ({stats['mode_a'].get('count', 0)})")
    print(f"Mode B: {stats['mode_b'].get('status')}"
          f" ({stats['mode_b'].get('cached_total', 0)})")
    print(f"Mode C: {stats['mode_c'].get('status')}"
          f" (real={stats['mode_c'].get('real', 0)})")
    if not args.incremental:
        print(_("cli.output_label", dir=str(args.output or _default_output_dir())))


if __name__ == "__main__":
    main()
