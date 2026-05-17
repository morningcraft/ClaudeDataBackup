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
import tkinter
from tkinter import filedialog, messagebox

import customtkinter as ctk

import sys as _sys

from . import __version__
from . import paths
from . import cookies
from . import cli_exporter
from . import config as cfg
from . import manifest as mf
from .i18n import t as _, init_language, get_language, load_locale, save_language_preference
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
        self.root.geometry("580x760")
        self.root.minsize(520, 600)

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
        self._load_schedule_config()
        self.root.after(5000, self._poll_auto_status)
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
        # Modern Apple-inspired card palette (light / dark)
        CARD_BG = ("#F5F5F7", "#1C1C1E")
        ACCENT = ("#007AFF", "#0A84FF")
        ACCENT_HOVER = ("#0056CC", "#0066D6")
        SECONDARY_BG = ("#E8F2FF", "#152940")
        SECONDARY_HOVER = ("#D0E4FF", "#1E3555")

        # 固定布局（不用滚动容器 —— macOS Tk Canvas 不收 MouseWheel）
        self.main_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        self.main_frame.pack(fill="both", expand=True, padx=20, pady=(16, 12))
        self.main_frame.grid_columnconfigure(0, weight=1)

        row = 0

        # ---- 标题行（标题 + 语言切换） ----
        header_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        header_frame.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        header_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(header_frame, text="ClaudeDataBackup",
                      font=ctk.CTkFont(family=UI_FONT, size=22, weight="bold"),
                      text_color=ACCENT).grid(row=0, column=0, sticky="w")

        lang_label = _("gui.lang_toggle_zh") if get_language() == "zh" else _("gui.lang_toggle_en")
        self.lang_btn = ctk.CTkButton(
            header_frame, text=lang_label,
            width=80, height=32,
            font=ctk.CTkFont(family=UI_FONT, size=14),
            fg_color="transparent", text_color=("gray10", "gray90"),
            hover_color=("gray85", "gray25"),
            command=self._toggle_language)
        self.lang_btn.grid(row=0, column=1, sticky="e")
        row += 1

        # ---- 环境检测 ----
        env_frame = ctk.CTkFrame(self.main_frame, fg_color=CARD_BG, corner_radius=10)
        env_frame.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        env_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(env_frame, text=_("gui.env_detection"),
                      font=ctk.CTkFont(family=UI_FONT, size=13, weight="bold"),
                      text_color=ACCENT).grid(
            row=0, column=0, sticky="w", padx=14, pady=(12, 6))
        self.env_label = ctk.CTkLabel(env_frame, text=_("gui.env_detecting"),
                                       anchor="w", wraplength=680,
                                       font=ctk.CTkFont(family=UI_FONT, size=13))
        self.env_label.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))
        row += 1

        # ---- 备份目录 ----
        dir_frame = ctk.CTkFrame(self.main_frame, fg_color=CARD_BG, corner_radius=10)
        dir_frame.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        dir_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(dir_frame, text=_("gui.backup_dir"),
                      font=ctk.CTkFont(family=UI_FONT, size=13, weight="bold"),
                      text_color=ACCENT).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 6))
        self.backup_dir_var = ctk.StringVar(value=str(cfg.get_backup_dir()))
        ctk.CTkEntry(dir_frame, textvariable=self.backup_dir_var,
                      font=ctk.CTkFont(family=UI_FONT, size=13)).grid(
            row=1, column=0, sticky="ew", padx=(14, 6), pady=(0, 12))
        ctk.CTkButton(dir_frame, text=_("gui.change"), width=70,
                       font=ctk.CTkFont(family=UI_FONT, size=13),
                       fg_color=SECONDARY_BG, text_color=ACCENT,
                       hover_color=SECONDARY_HOVER,
                       command=self._pick_backup_dir).grid(
            row=1, column=1, padx=(0, 14), pady=(0, 12))
        row += 1

        # ---- 数据源选择 ----
        src_frame = ctk.CTkFrame(self.main_frame, fg_color=CARD_BG, corner_radius=10)
        src_frame.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        src_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(src_frame, text=_("gui.data_source"),
                      font=ctk.CTkFont(family=UI_FONT, size=13, weight="bold"),
                      text_color=ACCENT).grid(
            row=0, column=0, sticky="w", padx=14, pady=(12, 6))

        sources = cfg.get_sources()
        self.src_claude_ai = ctk.BooleanVar(value=sources.get("claude_ai", True))
        self.src_claude_code = ctk.BooleanVar(value=sources.get("claude_code", True))

        # Claude.ai 行
        ai_row = ctk.CTkFrame(src_frame, fg_color="transparent")
        ai_row.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 4))
        ai_row.grid_columnconfigure(0, weight=1)
        ctk.CTkCheckBox(ai_row, text=_("gui.ai_source_checkbox"),
                         variable=self.src_claude_ai,
                         checkbox_width=20, checkbox_height=20,
                         fg_color=ACCENT,
                         font=ctk.CTkFont(family=UI_FONT, size=13)).grid(
            row=0, column=0, sticky="w")
        self.ai_status_label = ctk.CTkLabel(ai_row, text="", text_color=("gray50", "gray60"),
                                             font=ctk.CTkFont(family=UI_FONT, size=12))
        self.ai_status_label.grid(row=0, column=1, sticky="e")

        # Claude Code 行
        cc_row = ctk.CTkFrame(src_frame, fg_color="transparent")
        cc_row.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 4))
        cc_row.grid_columnconfigure(0, weight=1)
        ctk.CTkCheckBox(cc_row, text=_("gui.cc_source_checkbox"),
                         variable=self.src_claude_code,
                         checkbox_width=20, checkbox_height=20,
                         fg_color=ACCENT,
                         font=ctk.CTkFont(family=UI_FONT, size=13)).grid(
            row=0, column=0, sticky="w")
        self.cc_status_label = ctk.CTkLabel(cc_row, text="", text_color=("gray50", "gray60"),
                                             font=ctk.CTkFont(family=UI_FONT, size=12))
        self.cc_status_label.grid(row=0, column=1, sticky="e")

        # Claude Code 项目选择
        self.cc_projects_frame = ctk.CTkFrame(src_frame, fg_color="transparent")
        self.cc_projects_frame.grid(row=3, column=0, sticky="ew", padx=(38, 14), pady=(0, 6))
        self.cc_projects_visible = False
        self.cc_expand_btn = ctk.CTkButton(
            self.cc_projects_frame, text=_("gui.expand_projects"), width=120, height=28,
            font=ctk.CTkFont(family=UI_FONT, size=12), fg_color="transparent",
            text_color=ACCENT, hover_color=("gray90", "gray25"),
            command=self._toggle_cc_projects, anchor="w")
        self.cc_expand_btn.pack(anchor="w")
        # 限高可滚动项目列表（CTkTextbox = macOS 触控板原生 + CTk 视觉风格）
        is_dark = ctk.get_appearance_mode().lower() == "dark"
        self.cc_projects_text = ctk.CTkTextbox(
            src_frame, height=130, wrap="word",
            border_width=0, corner_radius=6,
            font=ctk.CTkFont(family=UI_FONT, size=13),
        )
        checked_color = ACCENT[1] if is_dark else ACCENT[0]
        unchecked_color = "#636366" if is_dark else "#8E8E93"
        self.cc_projects_text._textbox.tag_configure("checked", foreground=checked_color)
        self.cc_projects_text._textbox.tag_configure("unchecked", foreground=unchecked_color)
        self.cc_projects_text.bind("<Button-1>", self._on_project_click)
        self._cc_project_vars: list[tuple[str, ctk.BooleanVar]] = []
        row += 1

        # ---- 自动备份 ----
        auto_frame = ctk.CTkFrame(self.main_frame, fg_color=CARD_BG, corner_radius=10)
        auto_frame.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        auto_frame.grid_columnconfigure(2, weight=1)

        self.auto_enabled_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(auto_frame, text=_("gui.auto_enabled"),
                         variable=self.auto_enabled_var,
                         checkbox_width=20, checkbox_height=20,
                         fg_color=ACCENT,
                         font=ctk.CTkFont(family=UI_FONT, size=13),
                         command=self._on_auto_enabled_toggle).grid(
            row=0, column=0, sticky="w", padx=14, pady=(12, 6))

        # 定时触发行
        time_row = ctk.CTkFrame(auto_frame, fg_color="transparent")
        time_row.grid(row=1, column=0, columnspan=3, sticky="ew", padx=14, pady=(0, 2))

        self.auto_time_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(time_row, text=_("gui.auto_trigger_periodic"),
                         variable=self.auto_time_var,
                         checkbox_width=20, checkbox_height=20,
                         font=ctk.CTkFont(family=UI_FONT, size=13),
                         command=self._on_auto_trigger_changed).pack(side="left")

        # 间隔输入 H+M 右对齐
        interval_box = ctk.CTkFrame(time_row, fg_color="transparent")
        interval_box.pack(side="right")
        self.auto_interval_h_var = ctk.StringVar(value="24")
        self.auto_interval_m_var = ctk.StringVar(value="0")
        h_entry = ctk.CTkEntry(interval_box, width=38, height=24,
                      font=ctk.CTkFont(family=UI_FONT, size=12),
                      textvariable=self.auto_interval_h_var)
        h_entry.pack(side="left")
        self.auto_hour_label = ctk.CTkLabel(interval_box, text=_("gui.auto_hour_unit"),
                      font=ctk.CTkFont(family=UI_FONT, size=12),
                      text_color=("gray50", "gray60"))
        self.auto_hour_label.pack(side="left", padx=(2, 6))
        m_entry = ctk.CTkEntry(interval_box, width=38, height=24,
                      font=ctk.CTkFont(family=UI_FONT, size=12),
                      textvariable=self.auto_interval_m_var)
        m_entry.pack(side="left")
        self.auto_min_label = ctk.CTkLabel(interval_box, text=_("gui.auto_minute_unit"),
                      font=ctk.CTkFont(family=UI_FONT, size=12),
                      text_color=("gray50", "gray60")).pack(side="left", padx=(2, 0))
        self.auto_interval_entry = h_entry  # for busy-state disabling
        h_entry.bind("<FocusOut>", self._on_auto_interval_changed)
        h_entry.bind("<Return>", self._on_auto_interval_changed)
        m_entry.bind("<FocusOut>", self._on_auto_interval_changed)
        m_entry.bind("<Return>", self._on_auto_interval_changed)

        # Claude 关闭时触发行
        close_row = ctk.CTkFrame(auto_frame, fg_color="transparent")
        close_row.grid(row=2, column=0, columnspan=3, sticky="ew", padx=14, pady=(0, 2))

        self.auto_close_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(close_row, text=_("gui.auto_trigger_claude_close"),
                         variable=self.auto_close_var,
                         checkbox_width=20, checkbox_height=20,
                         font=ctk.CTkFont(family=UI_FONT, size=13),
                         command=self._on_auto_trigger_changed).pack(side="left")

        # 最小间隔（同行右侧）
        ctk.CTkLabel(close_row, text=_("gui.auto_debounce_label"),
                      font=ctk.CTkFont(family=UI_FONT, size=12),
                      text_color=("gray50", "gray60")).pack(side="right")
        self.auto_debounce_var = ctk.StringVar(value="1")
        debounce_entry = ctk.CTkEntry(close_row, width=44, height=24,
                      font=ctk.CTkFont(family=UI_FONT, size=12),
                      textvariable=self.auto_debounce_var)
        debounce_entry.pack(side="right", padx=(0, 4))
        self.auto_debounce_entry = debounce_entry
        self.auto_debounce_entry.bind("<FocusOut>", self._on_auto_debounce_changed)
        self.auto_debounce_entry.bind("<Return>", self._on_auto_debounce_changed)

        # 状态行
        self.auto_status_label = ctk.CTkLabel(
            auto_frame, text=_("gui.auto_status_inactive"),
            font=ctk.CTkFont(family=UI_FONT, size=11),
            text_color=("gray50", "gray60"))
        self.auto_status_label.grid(row=3, column=0, columnspan=3,
                                     sticky="w", padx=14, pady=(4, 2))

        # 使用说明
        self.auto_hint_label = ctk.CTkLabel(
            auto_frame, text=_("gui.auto_hint"),
            font=ctk.CTkFont(family=UI_FONT, size=10),
            text_color=("gray60", "gray65"))
        self.auto_hint_label.grid(row=4, column=0, columnspan=3,
                                   sticky="w", padx=14, pady=(0, 10))

        row += 1

        # ---- 主操作按钮 ----
        self.backup_btn = ctk.CTkButton(
            self.main_frame, text=_("gui.backup_now"), height=44,
            font=ctk.CTkFont(family=UI_FONT, size=15, weight="bold"),
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=self._start_incremental)
        self.backup_btn.grid(row=row, column=0, sticky="ew", pady=(4, 2))
        ctk.CTkLabel(self.main_frame, text=_("gui.incremental_hint"),
                      text_color=("gray50", "gray60"),
                      font=ctk.CTkFont(family=UI_FONT, size=12)).grid(
            row=row + 1, column=0, sticky="w", pady=(0, 12))
        row += 2

        # ---- 次操作按钮 ----
        btn_row = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        btn_row.grid(row=row, column=0, sticky="ew", pady=(0, 12))

        self.view_btn = ctk.CTkButton(
            btn_row, text=_("gui.view_chat"), width=120, height=32,
            font=ctk.CTkFont(family=UI_FONT, size=13), state="disabled",
            fg_color=SECONDARY_BG, text_color=ACCENT, hover_color=SECONDARY_HOVER,
            command=self._open_viewer)
        self.view_btn.pack(side="left")

        self.export_btn = ctk.CTkButton(
            btn_row, text=_("gui.export_full"), width=120, height=32,
            font=ctk.CTkFont(family=UI_FONT, size=13),
            fg_color=SECONDARY_BG, text_color=ACCENT, hover_color=SECONDARY_HOVER,
            command=self._start_export)
        self.export_btn.pack(side="left", padx=(8, 0))

        self.open_btn = ctk.CTkButton(
            btn_row, text=_("gui.open_backup_dir"), width=120, height=32,
            font=ctk.CTkFont(family=UI_FONT, size=13), state="disabled",
            fg_color=SECONDARY_BG, text_color=ACCENT, hover_color=SECONDARY_HOVER,
            command=self._open_backup_dir)
        self.open_btn.pack(side="left", padx=(8, 0))

        ctk.CTkButton(
            btn_row, text=_("gui.open_log"), width=80, height=32,
            font=ctk.CTkFont(family=UI_FONT, size=13),
            fg_color="transparent", text_color=("gray10", "gray90"),
            hover_color=("gray85", "gray25"),
            command=self._open_log).pack(side="left", padx=(8, 0))

        ctk.CTkButton(
            btn_row, text=_("gui.quit"), width=60, height=32,
            font=ctk.CTkFont(family=UI_FONT, size=13),
            fg_color="transparent", text_color=("gray10", "gray90"),
            hover_color=("gray85", "gray25"),
            command=self.root.quit).pack(side="right")
        row += 1

        # 日志行占据所有剩余垂直空间
        self.main_frame.grid_rowconfigure(row, weight=1)

        # ---- 日志 ----
        log_frame = ctk.CTkFrame(self.main_frame, fg_color=CARD_BG, corner_radius=10)
        log_frame.grid(row=row, column=0, sticky="nsew", pady=(0, 4))
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(log_frame, text=_("gui.log_title"),
                      font=ctk.CTkFont(family=UI_FONT, size=13, weight="bold"),
                      text_color=ACCENT).grid(
            row=0, column=0, sticky="w", padx=14, pady=(12, 4))

        self.log_text = ctk.CTkTextbox(log_frame, wrap="word",
                                        font=ctk.CTkFont(family="Consolas", size=12))
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 12))

    # ---------- 语言切换 ----------

    def _toggle_language(self) -> None:
        """切换中/英语言，重建 UI。偏好仅在备份成功后持久化。"""
        new_lang = "en" if get_language() == "zh" else "zh"
        load_locale(new_lang)
        self.main_frame.destroy()
        self._build_ui()
        self._diagnose()
        self._load_schedule_config()
        self._update_backup_status()

    # ---------- 环境诊断 ----------

    def _diagnose(self) -> None:
        t0 = time.monotonic()
        log.info("_diagnose 开始")
        lines = []

        t = time.monotonic()
        r = paths.report()
        log.debug("paths.report() 完成 (%.3fs)", time.monotonic() - t)

        if r.get("claude_desktop_installed"):
            lines.append(_("gui.desktop_detected"))
        else:
            lines.append(_("gui.desktop_not_detected"))

        t = time.monotonic()
        cs = cookies.describe_cookie_state()
        log.debug("cookies.describe_cookie_state() 完成 (%.3fs)", time.monotonic() - t)
        if cs.get("cookies_readable"):
            has_sk = cs.get("has_session_key")
            status = _("gui.cookie_has_key") if has_sk else _("gui.cookie_no_key")
            lines.append(_("gui.cookie_readable", status=status))
        else:
            lines.append(_("gui.cookie_unreadable", error=cs.get('error', _("gui.unknown"))))

        proj = paths.claude_cli_projects_dir_optional()
        if proj:
            t = time.monotonic()
            counts = cli_exporter.count_sessions()
            log.debug("cli_exporter.count_sessions() 完成 (%.3fs)", time.monotonic() - t)
            lines.append(_("gui.cc_detected", count=counts['real']))
            self.cc_status_label.configure(text=_("gui.cc_detected", count=counts['real']))
            self._populate_cc_projects(counts)
        else:
            lines.append(_("gui.cc_not_detected"))
            self.cc_status_label.configure(text=_("gui.cc_not_detected"))

        self.env_label.configure(text="  |  ".join(lines))
        self._update_backup_status()
        log.info("_diagnose 完成 (%.3fs)", time.monotonic() - t0)

    def _update_backup_status(self) -> None:
        backup_dir = Path(self.backup_dir_var.get()).expanduser()
        manifest = mf.load_manifest(backup_dir)
        s = mf.summary(manifest)
        log.debug("_update_backup_status: conv=%d, session=%d, real=%d",
                  s["conversation_count"], s["session_count"], s["real_session_count"])

        if s["conversation_count"] > 0:
            self.ai_status_label.configure(
                text=_("gui.backup_status", count=s['conversation_count']) + "  "
                     + _("gui.last_backup", time=manifest.get('last_backup_time', '-')))
        else:
            self.ai_status_label.configure(text=_("gui.not_backed_up"))

        if s["real_session_count"] > 0:
            self.cc_status_label.configure(
                text=_("gui.backup_status_sessions", count=s['real_session_count']) + "  "
                     + _("gui.last_backup", time=manifest.get('last_backup_time', '-')))

        has_backup = s["conversation_count"] > 0 or s["real_session_count"] > 0
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
            self.cc_projects_text.grid_forget()
            self.cc_expand_btn.configure(text=_("gui.expand_projects"))
            self.cc_projects_visible = False
        else:
            # 动态高度：每行约 20px，最少 100px（~5 行），最多 200px
            n = max(100, min(len(self._cc_project_vars) * 20, 200))
            self.cc_projects_text.configure(height=n)
            self.cc_projects_text.grid(row=4, column=0, sticky="ew",
                                        padx=(38, 14), pady=(0, 6))
            self._refresh_project_list()
            self.cc_expand_btn.configure(text=_("gui.collapse_projects"))
            self.cc_projects_visible = True

    def _refresh_project_list(self) -> None:
        """刷新项目列表显示（☑/☐ + 项目名），勾选标记用主题色区分。"""
        self.cc_projects_text.configure(state="normal")
        self.cc_projects_text.delete("1.0", "end")
        for name, var in self._cc_project_vars:
            if var.get():
                self.cc_projects_text.insert("end", "☑  ", "checked")
            else:
                self.cc_projects_text.insert("end", "☐  ", "unchecked")
            self.cc_projects_text.insert("end", f"{name}\n")
        self.cc_projects_text.configure(state="disabled")

    def _on_project_click(self, event: tkinter.Event) -> None:
        """点击项目行切换 BooleanVar 并刷新显示。"""
        index = self.cc_projects_text.index(f"@{event.x},{event.y}")
        line_num = int(index.split(".")[0])
        if 1 <= line_num <= len(self._cc_project_vars):
            _name, var = self._cc_project_vars[line_num - 1]
            var.set(not var.get())
            self._refresh_project_list()
        return "break"

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
        self._log(_("gui.log_start_backup", dir=str(backup_dir), modes=modes))

        def worker():
            try:
                run_incremental(backup_dir, modes, self._log)
            except Exception as e:
                log.error("增量备份失败: %s", e, exc_info=True)
                self._log(_("gui.log_fatal_error", error=str(e)))
            finally:
                self._log(_("gui.log_backup_done"))
                self.root.after(0, self._on_done)

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def _start_export(self) -> None:
        modes = self._collect_modes()
        if not modes:
            return

        d = filedialog.askdirectory(title=_("gui.export_dir_title"))
        if not d:
            return
        output = Path(d) / "ClaudeDataBackup"
        self._last_output_dir = output

        self._set_buttons_busy(True)
        self._clear_log()
        self._log(_("gui.log_start_export", dir=str(output), modes=modes))

        def worker():
            try:
                run(output, modes, self._log)
            except Exception as e:
                log.error("一次性导出失败: %s", e, exc_info=True)
                self._log(_("gui.log_fatal_error", error=str(e)))
            finally:
                self._log(_("gui.log_export_done"))
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
            messagebox.showerror(_("gui.msgbox_error"), _("gui.msgbox_no_source"))
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
        self._load_schedule_config()
        save_language_preference(cfg.get_backup_dir())

    def _on_export_done(self, output: Path) -> None:
        self._on_done()
        self._open_dir(output)

    def _set_buttons_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.backup_btn.configure(state=state)
        self.export_btn.configure(state=state)
        self.open_btn.configure(state="disabled" if busy else "normal")
        self.view_btn.configure(state="disabled" if busy else "normal")
        # 自动备份控件
        for attr in ("auto_checkbox", "auto_time_cb", "auto_close_cb",
                     "auto_interval_entry", "auto_debounce_entry"):
            if hasattr(self, attr) and getattr(self, attr).winfo_exists():
                getattr(self, attr).configure(state=state)

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
        messagebox.showwarning(_("gui.msgbox_warning"), _("gui.msgbox_no_chat"))

    def _open_backup_dir(self) -> None:
        path = Path(self.backup_dir_var.get()).expanduser()
        if not path.exists():
            messagebox.showwarning(_("gui.msgbox_warning"), _("gui.msgbox_no_backup_dir"))
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

    # ─── 自动备份回调 ──────────────────────────────────

    def _load_schedule_config(self):
        """从 schedule.json 加载配置并更新 UI。"""
        from .scheduler import ScheduleConfig, schedule_config_path
        from .autobackup_daemon import is_daemon_running, read_status
        config = ScheduleConfig.load(schedule_config_path())
        self.auto_enabled_var.set(config.enabled)
        self.auto_time_var.set(
            config.time_trigger.type in ("periodic", "daily", "weekly", "monthly"))
        self.auto_close_var.set(config.condition_triggers.on_claude_close)
        total_mins = config.time_trigger.interval_minutes
        self.auto_interval_h_var.set(str(total_mins // 60))
        self.auto_interval_m_var.set(str(total_mins % 60))
        self.auto_debounce_var.set(str(config.min_interval_minutes))
        self._update_auto_status(config)

        # 配置启用了但 daemon 没跑 → 自动拉起
        if config.enabled and not is_daemon_running():
            self.root.after(1000, lambda c=config: self._apply_schedule_install(c))

    def _save_schedule_config(self):
        """从 UI 控件读取值，保存到 schedule.json。"""
        from .scheduler import (ScheduleConfig, TimeTrigger, ConditionTriggers,
                                schedule_config_path)
        enabled = self.auto_enabled_var.get()
        has_time = self.auto_time_var.get()
        on_close = self.auto_close_var.get()

        try:
            h = int(self.auto_interval_h_var.get())
        except ValueError:
            h = 24
        try:
            m = int(self.auto_interval_m_var.get())
        except ValueError:
            m = 0
        total_minutes = max(h * 60 + m, 1)

        try:
            min_interval = int(self.auto_debounce_var.get())
        except ValueError:
            min_interval = 1

        config = ScheduleConfig(
            enabled=enabled,
            mode="abc",
            backup_dir=str(cfg.get_backup_dir()),
            time_trigger=TimeTrigger(
                type="periodic" if has_time else "daily",
                interval_minutes=total_minutes,
            ),
            condition_triggers=ConditionTriggers(
                on_claude_close=on_close,
            ),
            min_interval_minutes=min_interval,
        )
        config.save(schedule_config_path())
        self._update_auto_status(config)
        return config

    def _update_auto_status(self, config=None):
        from .scheduler import ScheduleConfig, schedule_config_path, get_next_run_time
        from .autobackup_daemon import is_daemon_running, read_status
        if config is None:
            config = ScheduleConfig.load(schedule_config_path())

        parts = []
        if is_daemon_running():
            parts.append("● " + _("gui.auto_daemon_running"))
        else:
            parts.append("○ " + _("gui.auto_daemon_stopped"))

        if config.enabled:
            st = read_status()
            if st and st.get("last_backup"):
                parts.append(" | " + _("gui.auto_status_last",
                                       time=st["last_backup"]))
            next_run = get_next_run_time(config)
            if next_run:
                from datetime import datetime
                parts.append(" | " + _("gui.auto_status_next",
                                       time=datetime.fromtimestamp(next_run).strftime("%H:%M")))
        else:
            parts.append(" | " + _("gui.auto_status_inactive"))

        self.auto_status_label.configure(text="  ".join(parts))

    def _poll_auto_status(self):
        """定时刷新 daemon 状态。"""
        self._update_auto_status()
        self.root.after(5000, self._poll_auto_status)

    def _on_auto_enabled_toggle(self):
        config = self._save_schedule_config()
        self._apply_schedule_install(config)
        # 立即刷新状态（不等 5s 轮询）
        self.root.after(1500, self._update_auto_status)

    def _on_auto_trigger_changed(self, _choice=None):
        self._save_schedule_config()

    def _on_auto_interval_changed(self, _event=None):
        self._save_schedule_config()

    def _on_auto_debounce_changed(self, _event=None):
        self._save_schedule_config()

    def _apply_schedule_install(self, config):
        """根据配置安装或卸载 daemon。"""
        if config.enabled:
            if paths.detect_platform() == "mac":
                from .scheduler_mac import install as plat_install
                plat_install(config, config.time_trigger.interval_minutes)
            elif paths.detect_platform() == "win":
                from .scheduler_win import install as plat_install
                plat_install(config, config.time_trigger.interval_minutes)
        else:
            if paths.detect_platform() == "mac":
                from .scheduler_mac import uninstall as plat_uninstall
                plat_uninstall()
            elif paths.detect_platform() == "win":
                from .scheduler_win import uninstall as plat_uninstall
                plat_uninstall()

    def _open_log(self) -> None:
        """打开日志文件所在目录，选中日志文件。"""
        lp = log_path()
        if not lp.parent.exists():
            messagebox.showwarning(_("gui.msgbox_warning"), _("gui.msgbox_no_log_dir"))
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
    init_language(cfg.get_backup_dir())
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
