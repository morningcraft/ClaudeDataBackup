"""customtkinter 现代化 GUI —— 给非 CLI 用户的双击界面。

设计原则：
- 现代扁平外观，深色/浅色主题跟随系统
- 用 threading.Thread 跑主流程、queue.Queue 收日志，避免 UI 卡死
- 所有按钮和标签中文
"""
from __future__ import annotations
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

import sys as _sys

from . import __version__
from . import paths
from . import cookies
from . import cli_exporter
from . import config as cfg
from . import manifest as mf
from .log import setup_logging, get_logger, log_path
from .main import run, run_incremental

log = get_logger(__name__)

# 主题配色
ctk.set_appearance_mode("system")
ctk.set_default_color_theme("blue")

# 统一无衬线字体：Windows 用微软雅黑，macOS 用苹方，其他用系统默认
if _sys.platform == "win32":
    UI_FONT = "Microsoft YaHei"
elif _sys.platform == "darwin":
    UI_FONT = "PingFang SC"
else:
    UI_FONT = "sans-serif"


class App:
    def __init__(self, root: ctk.CTk):
        log.info("App.__init__ 开始")
        self.root = root
        self.root.title(f"ClaudeDataBackup v{__version__}")
        self.root.geometry("800x720")
        self.root.minsize(700, 580)

        # 设置窗口图标
        self._set_icon()

        self._build_ui()
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._worker: threading.Thread | None = None
        # 初始化为配置中的备份目录，这样重启后不需要先备份就能查看聊天记录
        self._last_output_dir: Path | None = cfg.get_backup_dir()

        # 技术日志只写文件，GUI textbox 只显示 logger() 回调的用户可读内容
        # （GuiHandler 已移除，避免技术细节污染用户界面）

        self._diagnose()
        self.root.after(100, self._drain_log_queue)
        log.info("App.__init__ 完成，mainloop 即将进入")

    def _set_icon(self) -> None:
        """设置窗口图标（打包后从 _MEIPASS 读取，开发时从 assets/ 读取）。"""
        try:
            if sys.platform == "darwin":
                icon_name = "app-icon.icns"
            else:
                icon_name = "app-icon.ico"
            if hasattr(sys, "_MEIPASS"):
                icon_path = Path(sys._MEIPASS) / "assets" / icon_name
            else:
                icon_path = Path(__file__).resolve().parent.parent.parent / "assets" / icon_name
            log.debug("_set_icon: 查找 %s → %s (存在=%s)", icon_name, icon_path, icon_path.is_file())
            if icon_path.is_file():
                if sys.platform == "darwin":
                    # macOS tkinter 不支持 iconbitmap(default=...)，直接传路径
                    self.root.iconbitmap(str(icon_path))
                else:
                    self.root.iconbitmap(default=str(icon_path))
                log.debug("_set_icon: 图标设置成功")
        except Exception as e:
            log.warning("_set_icon 失败: %s", e)

    def _build_ui(self) -> None:
        # 主容器，带滚动
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        main_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        main_frame.grid(row=0, column=0, sticky="nsew", padx=20, pady=(16, 12))
        main_frame.grid_columnconfigure(0, weight=1)

        row = 0

        # ---- 标题 ----
        title = ctk.CTkLabel(main_frame, text="ClaudeDataBackup",
                              font=ctk.CTkFont(family=UI_FONT, size=22, weight="bold"))
        title.grid(row=row, column=0, sticky="w", pady=(0, 12))
        row += 1

        # ---- 环境检测 ----
        env_frame = ctk.CTkFrame(main_frame)
        env_frame.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        env_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(env_frame, text="环境检测",
                      font=ctk.CTkFont(family=UI_FONT, size=13, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 4))
        self.env_label = ctk.CTkLabel(env_frame, text="检测中 ...",
                                       anchor="w", wraplength=700)
        self.env_label.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        row += 1

        # ---- 备份目录 ----
        dir_frame = ctk.CTkFrame(main_frame)
        dir_frame.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        dir_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(dir_frame, text="备份目录",
                      font=ctk.CTkFont(family=UI_FONT, size=13, weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(10, 4))
        self.backup_dir_var = ctk.StringVar(value=str(cfg.get_backup_dir()))
        ctk.CTkEntry(dir_frame, textvariable=self.backup_dir_var).grid(
            row=1, column=0, sticky="ew", padx=(12, 4), pady=(0, 10))
        ctk.CTkButton(dir_frame, text="更改", width=60,
                       command=self._pick_backup_dir).grid(
            row=1, column=1, padx=(0, 12), pady=(0, 10))
        row += 1

        # ---- 数据源选择 ----
        src_frame = ctk.CTkFrame(main_frame)
        src_frame.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        src_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(src_frame, text="数据源选择",
                      font=ctk.CTkFont(family=UI_FONT, size=13, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 4))

        sources = cfg.get_sources()
        self.src_claude_ai = ctk.BooleanVar(value=sources.get("claude_ai", True))
        self.src_claude_code = ctk.BooleanVar(value=sources.get("claude_code", True))

        # Claude.ai 行
        ai_row = ctk.CTkFrame(src_frame, fg_color="transparent")
        ai_row.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 4))
        ai_row.grid_columnconfigure(0, weight=1)
        ctk.CTkCheckBox(ai_row, text="Claude.ai 对话（在线 API + 缓存）",
                         variable=self.src_claude_ai,
                         checkbox_width=20, checkbox_height=20).grid(
            row=0, column=0, sticky="w")
        self.ai_status_label = ctk.CTkLabel(ai_row, text="", text_color=("gray40", "gray70"),
                                             font=ctk.CTkFont(family=UI_FONT, size=12))
        self.ai_status_label.grid(row=0, column=1, sticky="e")

        # Claude Code 行
        cc_row = ctk.CTkFrame(src_frame, fg_color="transparent")
        cc_row.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 4))
        cc_row.grid_columnconfigure(0, weight=1)
        ctk.CTkCheckBox(cc_row, text="Claude Code 会话（本地日志）",
                         variable=self.src_claude_code,
                         checkbox_width=20, checkbox_height=20).grid(
            row=0, column=0, sticky="w")
        self.cc_status_label = ctk.CTkLabel(cc_row, text="", text_color=("gray40", "gray70"),
                                             font=ctk.CTkFont(family=UI_FONT, size=12))
        self.cc_status_label.grid(row=0, column=1, sticky="e")

        # Claude Code 项目选择
        self.cc_projects_frame = ctk.CTkFrame(src_frame, fg_color="transparent")
        self.cc_projects_frame.grid(row=3, column=0, sticky="ew", padx=(36, 12), pady=(0, 8))
        self.cc_projects_visible = False
        self.cc_expand_btn = ctk.CTkButton(
            self.cc_projects_frame, text="展开项目选择 ▸", width=120, height=28,
            font=ctk.CTkFont(family=UI_FONT, size=12), fg_color="transparent",
            text_color=("gray10", "gray90"), hover_color=("gray85", "gray25"),
            command=self._toggle_cc_projects, anchor="w")
        self.cc_expand_btn.pack(anchor="w")
        self.cc_projects_inner = ctk.CTkFrame(src_frame, fg_color="transparent")
        self._cc_project_vars: list[tuple[str, ctk.BooleanVar]] = []
        row += 1

        # ---- 主操作按钮 ----
        self.backup_btn = ctk.CTkButton(
            main_frame, text="立即备份", height=44,
            font=ctk.CTkFont(family=UI_FONT, size=15, weight="bold"),
            command=self._start_incremental)
        self.backup_btn.grid(row=row, column=0, sticky="ew", pady=(4, 2))
        ctk.CTkLabel(main_frame, text="增量模式：只下载新的和变化的内容",
                      text_color=("gray40", "gray70"), font=ctk.CTkFont(family=UI_FONT, size=12)).grid(
            row=row + 1, column=0, sticky="w", pady=(0, 8))
        row += 2

        # ---- 次操作按钮 ----
        btn_row = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_row.grid(row=row, column=0, sticky="ew", pady=(0, 10))

        self.view_btn = ctk.CTkButton(
            btn_row, text="查看聊天记录", width=120, height=32,
            font=ctk.CTkFont(family=UI_FONT, size=13), state="disabled",
            command=self._open_viewer)
        self.view_btn.pack(side="left")

        self.export_btn = ctk.CTkButton(
            btn_row, text="导出完整副本", width=120, height=32,
            font=ctk.CTkFont(family=UI_FONT, size=13),
            command=self._start_export)
        self.export_btn.pack(side="left", padx=(8, 0))

        self.open_btn = ctk.CTkButton(
            btn_row, text="打开备份目录", width=120, height=32,
            font=ctk.CTkFont(family=UI_FONT, size=13), state="disabled",
            command=self._open_backup_dir)
        self.open_btn.pack(side="left", padx=(8, 0))

        ctk.CTkButton(
            btn_row, text="打开日志", width=80, height=32,
            font=ctk.CTkFont(family=UI_FONT, size=13),
            fg_color="transparent", text_color=("gray10", "gray90"),
            hover_color=("gray85", "gray25"),
            command=self._open_log).pack(side="left", padx=(8, 0))

        ctk.CTkButton(
            btn_row, text="退出", width=60, height=32,
            font=ctk.CTkFont(family=UI_FONT, size=13),
            fg_color="transparent", text_color=("gray10", "gray90"),
            hover_color=("gray85", "gray25"),
            command=self.root.quit).pack(side="right")
        row += 1

        # ---- 日志 ----
        log_frame = ctk.CTkFrame(main_frame)
        log_frame.grid(row=row, column=0, sticky="nsew", pady=(0, 4))
        main_frame.grid_rowconfigure(row, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(log_frame, text="日志",
                      font=ctk.CTkFont(family=UI_FONT, size=13, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 4))

        self.log_text = ctk.CTkTextbox(log_frame, wrap="word",
                                        font=ctk.CTkFont(family="Consolas", size=12))
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 10))

    # ---------- 环境诊断 ----------

    def _diagnose(self) -> None:
        t0 = time.monotonic()
        log.info("_diagnose 开始")
        lines = []

        t = time.monotonic()
        r = paths.report()
        log.debug("paths.report() 完成 (%.3fs)", time.monotonic() - t)

        if r.get("claude_desktop_installed"):
            lines.append("Claude Desktop: 已检测到")
        else:
            lines.append("Claude Desktop: 未检测到")

        t = time.monotonic()
        cs = cookies.describe_cookie_state()
        log.debug("cookies.describe_cookie_state() 完成 (%.3fs)", time.monotonic() - t)
        if cs.get("cookies_readable"):
            has_sk = cs.get("has_session_key")
            lines.append(f"Cookie: 可读（sessionKey={'有' if has_sk else '无'}）")
        else:
            lines.append(f"Cookie: 不可读（{cs.get('error', '未知')}）")

        proj = paths.claude_cli_projects_dir_optional()
        if proj:
            t = time.monotonic()
            counts = cli_exporter.count_sessions()
            log.debug("cli_exporter.count_sessions() 完成 (%.3fs)", time.monotonic() - t)
            total_cc = counts["real"] + counts["observer"]
            lines.append(f"Claude Code: 已检测到（{total_cc} 个会话）")
            self.cc_status_label.configure(text=f"已检测到 {total_cc} 个会话")
            self._populate_cc_projects(counts)
        else:
            lines.append("Claude Code: 未检测到")
            self.cc_status_label.configure(text="未检测到")

        self.env_label.configure(text="  |  ".join(lines))
        self._update_backup_status()
        log.info("_diagnose 完成 (%.3fs)", time.monotonic() - t0)

    def _update_backup_status(self) -> None:
        backup_dir = Path(self.backup_dir_var.get()).expanduser()
        manifest = mf.load_manifest(backup_dir)
        s = mf.summary(manifest)
        log.debug("_update_backup_status: conv=%d, session=%d", s["conversation_count"], s["session_count"])

        if s["conversation_count"] > 0:
            self.ai_status_label.configure(
                text=f"已备份 {s['conversation_count']} 条  "
                     f"上次: {manifest.get('last_backup_time', '-')}")
        else:
            self.ai_status_label.configure(text="尚未备份")

        if s["session_count"] > 0:
            self.cc_status_label.configure(
                text=f"已备份 {s['session_count']} 个  "
                     f"上次: {manifest.get('last_backup_time', '-')}")

        has_backup = s["conversation_count"] > 0 or s["session_count"] > 0
        if has_backup:
            self.open_btn.configure(state="normal")

        html_path = backup_dir / "index.html"
        if html_path.is_file():
            self.view_btn.configure(state="normal")

    def _populate_cc_projects(self, counts: dict) -> None:
        projects_dir = paths.claude_cli_projects_dir_optional()
        if not projects_dir:
            return

        self._cc_project_vars.clear()
        mode = cfg.get_claude_code_projects_config()
        selected = set(mode.get("_selected", []))

        for d in sorted(projects_dir.iterdir()):
            if not d.is_dir():
                continue
            cat = cli_exporter.categorize(d.name)
            if cat is None:
                continue
            session_files = list(d.glob("*.jsonl"))
            if not session_files:
                continue
            var = ctk.BooleanVar(value=(mode.get("_mode") == "all" or d.name in selected))
            self._cc_project_vars.append((d.name, var))

    def _toggle_cc_projects(self) -> None:
        if self.cc_projects_visible:
            self.cc_projects_inner.grid_forget()
            self.cc_expand_btn.configure(text="展开项目选择 ▸")
            self.cc_projects_visible = False
        else:
            self.cc_projects_inner.grid(row=4, column=0, sticky="ew",
                                         padx=(36, 12), pady=(0, 8))
            for w in self.cc_projects_inner.winfo_children():
                w.destroy()
            for name, var in self._cc_project_vars:
                ctk.CTkCheckBox(self.cc_projects_inner, text=name,
                                 variable=var, checkbox_width=18,
                                 checkbox_height=18).pack(anchor="w", pady=1)
            self.cc_expand_btn.configure(text="收起项目选择 ▾")
            self.cc_projects_visible = True

    # ---------- 目录选择 ----------

    def _pick_backup_dir(self) -> None:
        d = filedialog.askdirectory(initialdir=str(Path(self.backup_dir_var.get()).parent))
        if d:
            self.backup_dir_var.set(d)
            cfg.set_backup_dir(Path(d))
            self._update_backup_status()

    # ---------- 增量备份 ----------

    def _start_incremental(self) -> None:
        modes = self._collect_modes()
        if not modes:
            return

        cfg.set_sources(claude_ai=self.src_claude_ai.get(),
                        claude_code=self.src_claude_code.get())
        self._save_cc_project_selection()

        backup_dir = Path(self.backup_dir_var.get()).expanduser()
        self._last_output_dir = backup_dir
        self._set_buttons_busy(True)
        self._clear_log()
        self._log(f"[备份] 开始增量备份 —— 目录：{backup_dir}，模式：{modes}")

        def worker():
            try:
                run_incremental(backup_dir, modes, self._log)
            except Exception as e:
                log.error("增量备份失败: %s", e, exc_info=True)
                self._log(f"[致命错误] {e}")
            finally:
                self._log("[完成] 备份结束")
                self.root.after(0, self._on_done)

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def _start_export(self) -> None:
        modes = self._collect_modes()
        if not modes:
            return

        d = filedialog.askdirectory(title="选择导出目录")
        if not d:
            return
        output = Path(d) / "ClaudeDataBackup"
        self._last_output_dir = output

        self._set_buttons_busy(True)
        self._clear_log()
        self._log(f"[导出] 开始一次性导出 —— 目录：{output}，模式：{modes}")

        def worker():
            try:
                run(output, modes, self._log)
            except Exception as e:
                log.error("一次性导出失败: %s", e, exc_info=True)
                self._log(f"[致命错误] {e}")
            finally:
                self._log("[完成] 导出结束")
                self.root.after(0, lambda: self._on_export_done(output))

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def _collect_modes(self) -> str:
        modes = ""
        if self.src_claude_ai.get():
            modes += "ab"
        if self.src_claude_code.get():
            modes += "c"
        modes = "".join(sorted(set(modes)))
        if not modes:
            messagebox.showerror("错误", "至少要勾选一个数据源")
            return ""
        return modes

    def _save_cc_project_selection(self) -> None:
        if not self._cc_project_vars:
            return
        if self.cc_projects_visible:
            selected = [name for name, var in self._cc_project_vars if var.get()]
            total = len(self._cc_project_vars)
            if len(selected) == total:
                cfg.set_claude_code_projects("all")
            elif len(selected) == 0:
                cfg.set_claude_code_projects("none")
            else:
                cfg.set_claude_code_projects("selected", selected)

    def _on_done(self) -> None:
        self._set_buttons_busy(False)
        self._update_backup_status()

    def _on_export_done(self, output: Path) -> None:
        self._on_done()
        self._open_dir(output)

    def _set_buttons_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.backup_btn.configure(state=state)
        self.export_btn.configure(state=state)
        self.open_btn.configure(state="disabled" if busy else "normal")
        self.view_btn.configure(state="disabled" if busy else "normal")

    def _open_viewer(self) -> None:
        log.info("_open_viewer 被调用, _last_output_dir=%s", self._last_output_dir)
        # 优先用最近一次备份/导出的实际目录，其次用配置的备份目录
        candidates = []
        if self._last_output_dir:
            candidates.append(self._last_output_dir / "index.html")
        backup_dir = Path(self.backup_dir_var.get()).expanduser()
        if backup_dir != self._last_output_dir:
            candidates.append(backup_dir / "index.html")

        for html_path in candidates:
            log.info("_open_viewer 检查: %s (存在=%s)", html_path, html_path.exists())
            if html_path.exists():
                log.info("_open_viewer 打开: %s", html_path)
                self._open_file(html_path)
                return

        log.warning("_open_viewer: 未找到 index.html, candidates=%s", candidates)
        messagebox.showwarning("提示", "尚无聊天记录，请先执行备份")

    def _open_backup_dir(self) -> None:
        path = Path(self.backup_dir_var.get()).expanduser()
        if not path.exists():
            messagebox.showwarning("提示", "备份目录还不存在")
            return
        self._open_dir(path)

    def _open_dir(self, path: Path) -> None:
        if not path.exists():
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def _open_file(self, path: Path) -> None:
        """用系统默认程序打开文件（比 webbrowser.open 在 .app 包里更可靠）。"""
        log.info("_open_file: %s", path)
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            elif sys.platform == "win32":
                os.startfile(str(path))
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            log.error("_open_file 失败: %s", e, exc_info=True)

    def _open_log(self) -> None:
        """打开日志文件所在目录，选中日志文件。"""
        lp = log_path()
        if not lp.parent.exists():
            messagebox.showwarning("提示", "日志目录还不存在")
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(lp)])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(lp)])
        else:
            subprocess.Popen(["xdg-open", str(lp.parent)])

    # ---------- 日志 ----------

    def _log(self, msg: str) -> None:
        self._log_queue.put(msg)

    def _drain_log_queue(self) -> None:
        try:
            while True:
                msg = self._log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self._drain_log_queue)

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")


def main():
    setup_logging()
    log.info("=== ClaudeDataBackup v%s 启动 ===", __version__)
    log.info("平台: %s, Python: %s, 打包: %s",
             sys.platform, sys.version.split()[0], hasattr(sys, "_MEIPASS"))
    try:
        root = ctk.CTk()
        log.debug("CTk 根窗口创建完成")
        App(root)
        log.info("进入 mainloop")
        root.mainloop()
    except Exception:
        log.critical("GUI 启动失败", exc_info=True)
        raise


if __name__ == "__main__":
    main()
