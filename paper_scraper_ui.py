# -*- coding: utf-8 -*-
"""Windows-friendly Tkinter UI for the ScienceDirect paper scraper."""

from __future__ import annotations

import os
import queue
import csv
import importlib.util
import json
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from tkinter import BooleanVar, StringVar, Text, Tk, filedialog, messagebox
from tkinter import ttk

from doi_batch_utils import (
    check_cookie_json,
    collect_failure_table_rows,
    collect_retry_input_rows,
    extract_doi_from_text,
    find_resume_candidates,
    preview_doi_input as preview_doi_data,
    read_run_events,
    write_retry_input_csv,
    write_retry_input_from_reports,
)
from windows_paths import chrome_bin

APP_DIR = Path(__file__).resolve().parent
SD_SCRIPT = APP_DIR / "sd_scraper.py"
SD_SKILL_SCRIPT = APP_DIR / "sd_institutional_skill.py"
OA_SCRIPT = APP_DIR / "paper_skill.py"
BATCH_SCRIPT = APP_DIR / "paper_batch.py"
SETTINGS_FILE = APP_DIR / "results" / "_ui_settings.json"
BATCH_ACTIONS = ("start", "resume", "zotero")
PREVIEW_LIMIT = 200
LOG_DRAIN_LIMIT = 200
LOG_MAX_LINES = 5000
PREVIEW_STATUS_LABELS = {
    "valid": "有效",
    "empty": "空 DOI",
    "invalid": "格式异常",
    "duplicate": "重复",
}


class PaperScraperUI:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("Paper Download UI · 推荐：统一批次")
        self.settings = self._load_settings_data()
        self.root.geometry(self.settings.get("geometry") or "1180x800")
        self.root.minsize(980, 680)

        self.process: subprocess.Popen[str] | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.preview_queue: queue.Queue[tuple] = queue.Queue()
        self.started_at: float | None = None

        self.mode_var = StringVar(value="doi_batch")
        self.workflow_var = StringVar(value=self.settings.get("workflow") or "paper_batch")
        self.query_var = StringVar(value="")
        self.journal_var = StringVar(value="")
        self.author_var = StringVar(value="")
        self.issn_var = StringVar(value="")
        self.date_var = StringVar(value="")
        self.count_var = StringVar(value="50")
        self.sort_var = StringVar(value="relevance")
        self.article_type_var = StringVar(value="")
        self.format_var = StringVar(value="xlsx")
        self.output_var = StringVar(value=self.settings.get("output_dir") or str(APP_DIR / "results"))
        self.filename_var = StringVar(value="")
        self.input_file_var = StringVar(value="")
        self.doi_column_var = StringVar(value="")
        self.sheet_var = StringVar(value="")
        self.resume_from_var = StringVar(value="")
        self.cookies_file_var = StringVar(value=self.settings.get("cookies_file") or "")
        self.oa_input_file_var = StringVar(value="")
        self.oa_email_var = StringVar(value=self.settings.get("oa_email") or "")
        self.oa_limit_var = StringVar(value="")
        self.batch_action_var = StringVar(value=self.settings.get("batch_action") or "start")
        self.batch_input_file_var = StringVar(value=self.settings.get("batch_input_file") or "")
        self.batch_run_dir_var = StringVar(value=self.settings.get("batch_run_dir") or "")
        self.batch_run_name_var = StringVar(value="")
        self.batch_login_wait_var = StringVar(value=str(self.settings.get("batch_login_wait") or "0"))
        self.batch_library_id_var = StringVar(value=str(self.settings.get("batch_library_id") or "1"))
        self.batch_wait_seconds_var = StringVar(value=str(self.settings.get("batch_wait_seconds") or "0"))

        self.browser_cookies_var = BooleanVar(value=bool(self.settings.get("browser_cookies", False)))
        self.open_login_var = BooleanVar(value=bool(self.settings.get("open_login", False)))
        self.download_pdf_var = BooleanVar(value=bool(self.settings.get("download_pdf", True)))
        self.download_supplements_var = BooleanVar(value=bool(self.settings.get("download_supplements", True)))
        self.open_access_var = BooleanVar(value=False)
        self.oa_dry_run_var = BooleanVar(value=False)
        self.oa_overwrite_var = BooleanVar(value=False)

        self.status_var = StringVar(value="就绪")
        self.preview_status_var = StringVar(value="未预览")
        self.command_var = StringVar(value="")
        self.summary_var = StringVar(value="")
        self.warning_var = StringVar(value="")
        self.progress_var = StringVar(value="进度：未开始")
        self.current_task_var = StringVar(value="当前任务：无")
        self.progress_counts_var = StringVar(value="计数：无")
        self.failure_filter_var = StringVar(value="全部")
        self.result_summary_var = StringVar(value="任务尚未运行。")
        self.startup_warnings = self._run_startup_checks()
        self.last_run_output_dir: Path | None = None
        self.last_failed_report_path: Path | None = None
        self.last_pdf_report_path: Path | None = None
        self.last_summary_path: Path | None = None
        self.last_summary_json_path: Path | None = None
        self.last_events_path: Path | None = None
        self.last_retry_input_path: Path | None = None
        self.last_student_handoff_dir: Path | None = None
        self.last_paper_index_path: Path | None = None
        self.last_failure_next_steps_path: Path | None = None
        self.last_preflight_merged_input_path: Path | None = None
        self.last_event_count = 0
        self.auto_retry_after_run = False
        self.last_smart_wizard_summary = ""
        self.ui_ready = False
        self.download_supplements_checkbuttons: list[ttk.Checkbutton] = []

        self._build_ui()
        self._sync_download_supplements_state()
        self.ui_ready = True
        self._bind_updates()
        self._refresh_command_preview()
        self._refresh_task_summary()
        self._drain_log_queue()
        self._drain_preview_queue()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _load_settings_data(self) -> dict:
        try:
            if SETTINGS_FILE.exists():
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {}

    def _save_settings(self) -> None:
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            width = self.root.winfo_width()
            height = self.root.winfo_height()
            geometry = self.root.geometry() if width >= 980 and height >= 680 else "1180x800"
            data = {
                "output_dir": self.output_var.get().strip(),
                "cookies_file": self.cookies_file_var.get().strip(),
                "geometry": geometry,
                "browser_cookies": bool(self.browser_cookies_var.get()),
                "open_login": bool(self.open_login_var.get()),
                "download_pdf": bool(self.download_pdf_var.get()),
                "download_supplements": bool(self.download_supplements_var.get()),
                "oa_email": self.oa_email_var.get().strip(),
                "workflow": self.workflow_var.get().strip(),
                "batch_action": self.batch_action_var.get().strip(),
                "batch_input_file": self.batch_input_file_var.get().strip(),
                "batch_run_dir": self.batch_run_dir_var.get().strip(),
                "batch_login_wait": self.batch_login_wait_var.get().strip(),
                "batch_library_id": self.batch_library_id_var.get().strip(),
                "batch_wait_seconds": self.batch_wait_seconds_var.get().strip(),
                "active_tab": self.notebook.index(self.notebook.select()) if hasattr(self, "notebook") else 0,
            }
            SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _run_startup_checks(self) -> list[str]:
        warnings: list[str] = []
        venv_python = APP_DIR / ".venv" / "Scripts" / "python.exe"
        if not venv_python.exists():
            warnings.append("未检测到 .venv；双击启动脚本会尝试自动创建并安装依赖。")
        for module_name, package_name in (
            ("curl_cffi", "curl_cffi"),
            ("browser_cookie3", "browser-cookie3"),
            ("openpyxl", "openpyxl"),
            ("websocket", "websocket-client"),
        ):
            if importlib.util.find_spec(module_name) is None:
                warnings.append(f"当前解释器未检测到 {package_name}；请通过启动脚本或 requirements.txt 安装。")
        chrome_path = chrome_bin()
        if not Path(chrome_path).exists() and shutil.which(chrome_path) is None:
            warnings.append("未在常见位置检测到 Edge/Chrome/Chromium；PDF 下载可能无法自动打开调试浏览器。")
        return warnings

    def _on_close(self) -> None:
        self._save_settings()
        self.root.destroy()

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 16, "bold"))
        style.configure("Step.TLabel", foreground="#444444")
        style.configure("Warning.TLabel", foreground="#9A3412")
        style.configure("Primary.TButton", font=("Microsoft YaHei UI", 10, "bold"))

        root_frame = ttk.Frame(self.root, padding=12)
        root_frame.pack(fill="both", expand=True)
        root_frame.columnconfigure(0, weight=1)
        root_frame.rowconfigure(2, weight=1)

        header = ttk.Frame(root_frame)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="论文下载集成界面", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="默认入口：统一批次（paper_batch）  start（失败自动排队 Zotero）· 其它页签仅兼容旧流程",
            style="Step.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.notebook = ttk.Notebook(root_frame)
        self.notebook.grid(row=2, column=0, sticky="nsew", pady=(10, 8))

        self.batch_tab = ttk.Frame(self.notebook, padding=10)
        self.doi_tab = ttk.Frame(self.notebook, padding=10)
        self.search_tab = ttk.Frame(self.notebook, padding=10)
        self.oa_tab = ttk.Frame(self.notebook, padding=10)
        self.run_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.batch_tab, text="统一批次（推荐）")
        self.notebook.add(self.doi_tab, text="DOI 批量下载（兼容）")
        self.notebook.add(self.search_tab, text="文献检索（兼容）")
        self.notebook.add(self.oa_tab, text="OA 资源辅助获取（兼容）")
        self.notebook.add(self.run_tab, text="运行日志")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self._build_batch_tab(self.batch_tab)
        self._build_doi_tab(self.doi_tab)
        self._build_search_tab(self.search_tab)
        self._build_oa_tab(self.oa_tab)
        self._build_run_tab(self.run_tab)
        try:
            self.notebook.select(int(self.settings.get("active_tab", 0)))
        except Exception:
            self.notebook.select(self.batch_tab)

        footer = ttk.Frame(root_frame)
        footer.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        footer.columnconfigure(0, weight=1)

        ttk.Label(footer, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        self.smart_run_button = ttk.Button(
            footer,
            text="智能准备并运行",
            command=self.run_smart_doi_wizard,
            style="Primary.TButton",
        )
        self.smart_run_button.grid(row=0, column=1, padx=(8, 0))
        self.run_button = ttk.Button(footer, text="开始运行", command=self.run_scraper, style="Primary.TButton")
        self.run_button.grid(row=0, column=2, padx=(8, 0))
        self.stop_button = ttk.Button(footer, text="停止", command=self.stop_scraper, state="disabled")
        self.stop_button.grid(row=0, column=3, padx=(8, 0))
        self.continue_button = ttk.Button(footer, text="登录完成，继续", command=self.send_enter, state="disabled")
        self.continue_button.grid(row=0, column=4, padx=(8, 0))
        ttk.Button(footer, text="打开输出目录", command=self.open_output_dir).grid(row=0, column=5, padx=(8, 0))
        ttk.Button(footer, text="清空日志", command=self.clear_log).grid(row=0, column=6, padx=(8, 0))

    def _build_batch_tab(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        ttk.Label(
            frame,
            text="默认入口 · 统一批次：OA → 机构授权 → 一次人工重试 → Zotero（paper_batch.py）",
            font=("Microsoft YaHei UI", 11, "bold"),
        ).grid(row=0, column=0, sticky="w")

        body = ttk.Frame(frame)
        body.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(body, text="1 操作与输入", padding=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.columnconfigure(1, weight=1)
        left.rowconfigure(5, weight=1)

        ttk.Label(left, text="子命令").grid(row=0, column=0, sticky="w")
        action_combo = ttk.Combobox(
            left,
            textvariable=self.batch_action_var,
            values=list(BATCH_ACTIONS),
            state="readonly",
            width=16,
        )
        action_combo.grid(row=0, column=1, sticky="w", pady=(0, 8))
        action_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_parameter_changed())

        ttk.Label(left, text="文献清单（start）").grid(row=1, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.batch_input_file_var).grid(row=1, column=1, sticky="ew", pady=(0, 4))
        ttk.Button(left, text="选择文件", command=self.choose_batch_input_file).grid(
            row=1, column=2, sticky="ew", padx=(6, 0), pady=(0, 4)
        )

        ttk.Label(left, text="或粘贴 DOI / 题名 / 推荐列表").grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self.batch_text = Text(left, height=12, width=52, wrap="word", font=("Consolas", 9))
        self.batch_text.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=(2, 6))
        self.batch_text.bind("<KeyRelease>", self._on_batch_text_changed)
        self.batch_text.bind("<<Paste>>", self._on_batch_text_changed)
        ttk.Button(left, text="清空粘贴", command=self.clear_batch_text).grid(row=4, column=0, sticky="ew")

        ttk.Label(left, text="已有批次目录（resume / zotero）").grid(row=5, column=0, sticky="nw", pady=(8, 0))
        ttk.Entry(left, textvariable=self.batch_run_dir_var).grid(row=5, column=1, sticky="ew", pady=(8, 0))
        ttk.Button(left, text="选择目录", command=self.choose_batch_run_dir).grid(
            row=5, column=2, sticky="ew", padx=(6, 0), pady=(8, 0)
        )

        right = ttk.LabelFrame(body, text="2 权限与输出", padding=10)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        ttk.Label(right, text="输出根目录（start）").grid(row=0, column=0, sticky="w")
        ttk.Entry(right, textvariable=self.output_var).grid(row=1, column=0, sticky="ew", pady=(2, 8))
        ttk.Button(right, text="选择输出目录", command=self.choose_output_dir).grid(row=2, column=0, sticky="ew", pady=(0, 8))

        ttk.Label(right, text="可选批次名称（run-name）").grid(row=3, column=0, sticky="w")
        ttk.Entry(right, textvariable=self.batch_run_name_var).grid(row=4, column=0, sticky="ew", pady=(2, 8))

        ttk.Label(right, text="邮箱（Unpaywall / 礼貌访问，强烈建议填写）").grid(row=5, column=0, sticky="w")
        ttk.Entry(right, textvariable=self.oa_email_var).grid(row=6, column=0, sticky="ew", pady=(2, 8))

        ttk.Label(right, text="Cookie JSON（机构权限，可选）").grid(row=7, column=0, sticky="w")
        ttk.Entry(right, textvariable=self.cookies_file_var).grid(row=8, column=0, sticky="ew", pady=(2, 4))
        ttk.Button(right, text="选择 Cookie 文件", command=self.choose_cookies_file).grid(row=9, column=0, sticky="ew", pady=(0, 8))

        ttk.Label(right, text="登录等待秒数（start，可选）").grid(row=10, column=0, sticky="w")
        ttk.Entry(right, textvariable=self.batch_login_wait_var, width=12).grid(row=11, column=0, sticky="w", pady=(2, 8))

        ttk.Label(right, text="Zotero library-id（start 自动桥接 / zotero）").grid(row=12, column=0, sticky="w")
        ttk.Entry(right, textvariable=self.batch_library_id_var, width=12).grid(row=13, column=0, sticky="w", pady=(2, 8))

        ttk.Label(right, text="等待 Zotero 结果秒数（start/zotero，0=只排队）").grid(row=14, column=0, sticky="w")
        ttk.Entry(right, textvariable=self.batch_wait_seconds_var, width=12).grid(row=15, column=0, sticky="w", pady=(2, 8))

        ttk.Label(
            right,
            text=(
                "start：OA + 机构，失败默认进 Zotero 并自动排队桥接；"
                "resume：兼容旧批次的一次人工重试；"
                "zotero：确认后重跑或手动排队桥接。"
            ),
            foreground="#555555",
            wraplength=420,
        ).grid(row=16, column=0, sticky="ew", pady=(8, 0))

        hint = ttk.LabelFrame(frame, text="说明", padding=10)
        hint.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(
            hint,
            text=(
                "新任务请只用本页。默认无需 resume：机构失败会写入 zotero_fallback 并由 start 自动排队。"
                "保持你要用的 Zotero 打开（桥接跟随当前打开的实例，不固定测试配置）；"
                "若提示确认，在插件中点一次后可用子命令 zotero 继续。"
                "日志出现「运行目录：…」后会自动填回「已有批次目录」。"
            ),
            wraplength=1020,
            foreground="#444444",
        ).grid(row=0, column=0, sticky="w")

    def _build_doi_tab(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(0, weight=1)

        source = ttk.LabelFrame(frame, text="1 数据来源", padding=10)
        source.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        source.columnconfigure(0, weight=1)
        self._build_doi_source_fields(source)

        right = ttk.Frame(frame)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        options = ttk.LabelFrame(right, text="2 权限与输出", padding=10)
        options.grid(row=0, column=0, sticky="ew")
        self._build_common_options(options, compact=True)

        preview = ttk.LabelFrame(right, text="3 预览检查", padding=10)
        preview.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(1, weight=1)
        ttk.Label(preview, textvariable=self.preview_status_var, foreground="#555555").grid(row=0, column=0, sticky="w")
        self.preview_tree = ttk.Treeview(
            preview,
            columns=("row", "status", "doi", "title", "reason"),
            show="headings",
            height=9,
        )
        for column, heading, width, anchor in (
            ("row", "行号", 58, "center"),
            ("status", "状态", 82, "center"),
            ("doi", "标准化 DOI", 210, "w"),
            ("title", "标题", 180, "w"),
            ("reason", "说明", 120, "w"),
        ):
            self.preview_tree.heading(column, text=heading)
            self.preview_tree.column(column, width=width, anchor=anchor, stretch=column in {"doi", "title", "reason"})
        self.preview_tree.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        yscroll = ttk.Scrollbar(preview, orient="vertical", command=self.preview_tree.yview)
        yscroll.grid(row=1, column=1, sticky="ns", pady=(6, 0))
        xscroll = ttk.Scrollbar(preview, orient="horizontal", command=self.preview_tree.xview)
        xscroll.grid(row=2, column=0, sticky="ew")
        self.preview_tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)

        preflight = ttk.LabelFrame(right, text="4 运行前体检（本地）", padding=10)
        preflight.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        preflight.columnconfigure(0, weight=1)
        self.preflight_text = Text(preflight, height=5, width=58, wrap="word", font=("Consolas", 9))
        self.preflight_text.grid(row=0, column=0, sticky="ew")
        self.preflight_text.configure(state="disabled")

    def _build_search_tab(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(0, weight=3)
        frame.columnconfigure(1, weight=2)
        frame.rowconfigure(0, weight=1)

        search = ttk.LabelFrame(frame, text="1 检索条件", padding=10)
        search.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._build_search_fields(search)

        options = ttk.LabelFrame(frame, text="2 权限与输出", padding=10)
        options.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self._build_common_options(options, compact=False)

    def _build_oa_tab(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(0, weight=3)
        frame.columnconfigure(1, weight=2)
        frame.rowconfigure(0, weight=1)

        source = ttk.LabelFrame(frame, text="1 OA 资源数据来源", padding=10)
        source.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        source.columnconfigure(0, weight=1)
        source.columnconfigure(1, weight=1)
        source.columnconfigure(2, weight=0)
        source.rowconfigure(3, weight=1)

        ttk.Label(source, text="输入文件").grid(row=0, column=0, sticky="w")
        ttk.Entry(source, textvariable=self.oa_input_file_var).grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=(0, 8), pady=(2, 8)
        )
        ttk.Button(source, text="选择", command=self.choose_oa_input_file).grid(row=1, column=2, sticky="ew", pady=(2, 8))

        ttk.Label(source, text="或直接粘贴 DOI、标题、推荐文献列表").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(8, 0)
        )
        self.oa_text = Text(source, height=16, width=72, wrap="word", font=("Consolas", 9))
        self.oa_text.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=(2, 6))
        self.oa_text.bind("<KeyRelease>", self._on_oa_text_changed)
        self.oa_text.bind("<<Paste>>", self._on_oa_text_changed)

        ttk.Button(source, text="清空粘贴", command=self.clear_oa_text).grid(row=4, column=0, sticky="ew", padx=(0, 8))
        ttk.Label(
            source,
            text="支持 .txt/.md/.markdown/.csv。该模式仅辅助查找公开开放获取 PDF 候选资源，不使用机构 Cookie。",
            foreground="#555555",
            wraplength=620,
        ).grid(row=5, column=0, columnspan=3, sticky="ew", pady=(10, 0))

        options = ttk.LabelFrame(frame, text="2 输出与 OA 参数", padding=10)
        options.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        for i in range(3):
            options.columnconfigure(i, weight=1)

        ttk.Label(options, text="输出目录").grid(row=0, column=0, sticky="w")
        ttk.Entry(options, textvariable=self.output_var).grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=(0, 8), pady=(2, 8)
        )
        ttk.Button(options, text="选择", command=self.choose_output_dir).grid(row=1, column=2, sticky="ew", pady=(2, 8))

        ttk.Label(options, text="邮箱（用于 Unpaywall/Crossref 礼貌访问，可选）").grid(
            row=2, column=0, columnspan=3, sticky="w"
        )
        ttk.Entry(options, textvariable=self.oa_email_var).grid(row=3, column=0, columnspan=3, sticky="ew", pady=(2, 8))

        ttk.Label(options, text="测试限制数量（可选）").grid(row=4, column=0, sticky="w")
        ttk.Entry(options, textvariable=self.oa_limit_var).grid(row=5, column=0, sticky="ew", padx=(0, 8), pady=(2, 8))

        ttk.Checkbutton(options, text="Dry-run：只解析，不下载 PDF", variable=self.oa_dry_run_var).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(4, 2)
        )
        ttk.Checkbutton(options, text="覆盖已存在 PDF", variable=self.oa_overwrite_var).grid(
            row=7, column=0, columnspan=3, sticky="w", pady=2
        )
        ttk.Label(
            options,
            text="OA 资源辅助获取不会读取 Cookie JSON、不会打开机构登录浏览器。",
            foreground="#555555",
            wraplength=420,
        ).grid(row=8, column=0, columnspan=3, sticky="ew", pady=(12, 0))

    def _build_run_tab(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(7, weight=1)

        ttk.Label(frame, text="4 运行前检查", font=("Microsoft YaHei UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(frame, textvariable=self.summary_var, wraplength=1020).grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(frame, textvariable=self.warning_var, style="Warning.TLabel", wraplength=1020).grid(
            row=2, column=0, sticky="ew", pady=(4, 8)
        )
        command_entry = ttk.Entry(frame, textvariable=self.command_var, state="readonly")
        command_entry.grid(row=3, column=0, sticky="ew", pady=(0, 8))

        progress = ttk.LabelFrame(frame, text="实时进度", padding=10)
        progress.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        progress.columnconfigure(0, weight=1)
        ttk.Label(progress, textvariable=self.progress_var).grid(row=0, column=0, sticky="w")
        ttk.Label(progress, textvariable=self.current_task_var, wraplength=1020).grid(row=1, column=0, sticky="ew", pady=(4, 0))
        ttk.Label(progress, textvariable=self.progress_counts_var).grid(row=2, column=0, sticky="w", pady=(4, 0))

        result = ttk.LabelFrame(frame, text="结果摘要", padding=10)
        result.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        result.columnconfigure(0, weight=1)
        ttk.Label(result, textvariable=self.result_summary_var, wraplength=1020).grid(
            row=0, column=0, columnspan=6, sticky="ew"
        )
        self.open_run_output_button = ttk.Button(result, text="打开本次输出目录", command=self.open_last_output_dir, state="disabled")
        self.open_run_output_button.grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=(8, 0))
        self.open_failed_report_button = ttk.Button(result, text="打开失败 DOI 表", command=self.open_failed_report, state="disabled")
        self.open_failed_report_button.grid(row=1, column=1, sticky="ew", padx=(0, 6), pady=(8, 0))
        self.open_pdf_report_button = ttk.Button(result, text="打开 PDF 报告", command=self.open_pdf_report, state="disabled")
        self.open_pdf_report_button.grid(row=1, column=2, sticky="ew", padx=(0, 6), pady=(8, 0))
        self.open_summary_button = ttk.Button(result, text="打开任务摘要", command=self.open_run_summary, state="disabled")
        self.open_summary_button.grid(row=1, column=3, sticky="ew", padx=(0, 6), pady=(8, 0))
        self.retry_failed_button = ttk.Button(result, text="生成重试输入 CSV", command=self.create_retry_input_from_reports, state="disabled")
        self.retry_failed_button.grid(row=1, column=4, sticky="ew", pady=(8, 0))
        self.open_student_handoff_button = ttk.Button(
            result,
            text="打开研究生查看入口",
            command=self.open_student_handoff,
            state="disabled",
        )
        self.open_student_handoff_button.grid(row=2, column=0, columnspan=2, sticky="ew", padx=(0, 6), pady=(8, 0))
        self.open_failure_next_steps_button = ttk.Button(
            result,
            text="打开失败下一步表",
            command=self.open_failure_next_steps,
            state="disabled",
        )
        self.open_failure_next_steps_button.grid(row=2, column=2, columnspan=2, sticky="ew", padx=(0, 6), pady=(8, 0))
        self.use_preflight_input_button = ttk.Button(
            result,
            text="使用预检合并表",
            command=self.use_preflight_merged_input,
            state="disabled",
        )
        self.use_preflight_input_button.grid(row=2, column=4, sticky="ew", pady=(8, 0))

        failure = ttk.LabelFrame(frame, text="失败项", padding=10)
        failure.grid(row=6, column=0, sticky="ew", pady=(0, 8))
        failure.columnconfigure(1, weight=1)
        ttk.Label(failure, text="筛选").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.failure_filter_combo = ttk.Combobox(
            failure,
            textvariable=self.failure_filter_var,
            values=["全部", "解析失败", "PDF失败", "跳过"],
            state="readonly",
            width=12,
        )
        self.failure_filter_combo.grid(row=0, column=1, sticky="w")
        self.failure_filter_combo.bind("<<ComboboxSelected>>", lambda _event: self._load_failure_table())
        self.retry_selected_button = ttk.Button(
            failure,
            text="生成选中项重试 CSV",
            command=lambda: self.create_retry_input_from_reports(selected_only=True),
            state="disabled",
        )
        self.retry_selected_button.grid(row=0, column=2, sticky="e", padx=(8, 0))
        self.failure_tree = ttk.Treeview(
            failure,
            columns=("kind", "doi", "title", "reason"),
            show="headings",
            height=5,
            selectmode="extended",
        )
        for column, heading, width in (
            ("kind", "类型", 90),
            ("doi", "DOI", 230),
            ("title", "标题", 260),
            ("reason", "原因", 320),
        ):
            self.failure_tree.heading(column, text=heading)
            self.failure_tree.column(column, width=width, stretch=column in {"title", "reason"})
        self.failure_tree.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))

        self.log_text = Text(frame, height=18, width=120, wrap="word", font=("Consolas", 10))
        self.log_text.grid(row=7, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.log_text.yview)
        yscroll.grid(row=7, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=yscroll.set)

    def _build_search_fields(self, frame: ttk.Frame) -> None:
        for i in range(4):
            frame.columnconfigure(i, weight=1)

        ttk.Label(frame, text="检索模式").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            frame,
            textvariable=self.mode_var,
            values=["keyword", "journal", "journal_keyword", "author", "issn", "advanced"],
            state="readonly",
        ).grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(2, 8))

        ttk.Label(frame, text="最大数量").grid(row=0, column=1, sticky="w")
        ttk.Entry(frame, textvariable=self.count_var).grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(2, 8))

        ttk.Label(frame, text="排序").grid(row=0, column=2, sticky="w")
        ttk.Combobox(
            frame,
            textvariable=self.sort_var,
            values=["relevance", "date"],
            state="readonly",
        ).grid(row=1, column=2, sticky="ew", padx=(0, 8), pady=(2, 8))

        ttk.Label(frame, text="导出格式").grid(row=0, column=3, sticky="w")
        ttk.Combobox(
            frame,
            textvariable=self.format_var,
            values=["xlsx", "csv", "json", "all"],
            state="readonly",
        ).grid(row=1, column=3, sticky="ew", pady=(2, 8))

        ttk.Label(frame, text="关键词").grid(row=2, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.query_var).grid(row=3, column=0, columnspan=4, sticky="ew", pady=(2, 8))

        ttk.Label(frame, text="期刊名称").grid(row=4, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.journal_var).grid(row=5, column=0, columnspan=2, sticky="ew", padx=(0, 8), pady=(2, 8))

        ttk.Label(frame, text="作者").grid(row=4, column=2, sticky="w")
        ttk.Entry(frame, textvariable=self.author_var).grid(row=5, column=2, columnspan=2, sticky="ew", pady=(2, 8))

        ttk.Label(frame, text="年份范围").grid(row=6, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.date_var).grid(row=7, column=0, sticky="ew", padx=(0, 8), pady=(2, 8))

        ttk.Label(frame, text="ISSN").grid(row=6, column=1, sticky="w")
        ttk.Entry(frame, textvariable=self.issn_var).grid(row=7, column=1, sticky="ew", padx=(0, 8), pady=(2, 8))

        ttk.Label(frame, text="文章类型").grid(row=6, column=2, sticky="w")
        ttk.Combobox(
            frame,
            textvariable=self.article_type_var,
            values=["", "FLA", "REV", "SCO", "EDB", "ERR", "COR"],
            state="readonly",
        ).grid(row=7, column=2, sticky="ew", padx=(0, 8), pady=(2, 8))

        ttk.Checkbutton(frame, text="仅开放获取", variable=self.open_access_var).grid(
            row=7, column=3, sticky="w", pady=(2, 8)
        )

        tips = (
            "提示：关键词支持 AND/OR/NOT；年份范围示例 2020-2024。"
            "如果已有 DOI 表格，建议回到“DOI 批量下载”页。"
        )
        ttk.Label(frame, text=tips, foreground="#555555", wraplength=640).grid(
            row=8, column=0, columnspan=4, sticky="ew", pady=(12, 0)
        )

    def _build_doi_source_fields(self, frame: ttk.Frame) -> None:
        for i in range(3):
            frame.columnconfigure(i, weight=1)

        ttk.Label(frame, text="DOI 批量输入表").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.input_file_var).grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=(0, 8), pady=(2, 8)
        )
        ttk.Button(frame, text="选择", command=self.choose_input_file).grid(row=1, column=2, sticky="ew", pady=(2, 8))

        ttk.Label(frame, text="Excel 工作表名").grid(row=2, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.sheet_var).grid(row=3, column=0, sticky="ew", padx=(0, 8), pady=(2, 8))

        ttk.Label(frame, text="DOI 列名").grid(row=2, column=1, sticky="w")
        ttk.Entry(frame, textvariable=self.doi_column_var).grid(row=3, column=1, sticky="ew", padx=(0, 8), pady=(2, 8))

        ttk.Label(frame, text="直接粘贴 DOI 或表格内容").grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.paste_text = Text(frame, height=10, width=56, wrap="none", font=("Consolas", 9))
        self.paste_text.grid(row=5, column=0, columnspan=3, sticky="nsew", pady=(2, 6))
        self.paste_text.bind("<KeyRelease>", self._on_paste_text_changed)
        self.paste_text.bind("<<Paste>>", self._on_paste_text_changed)
        frame.rowconfigure(5, weight=1)

        self.preview_button = ttk.Button(frame, text="预览解析", command=self.preview_doi_input)
        self.preview_button.grid(row=6, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(frame, text="清空粘贴", command=self.clear_paste_text).grid(row=6, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(frame, text="生成 DOI 模板", command=self.create_doi_template).grid(row=6, column=2, sticky="ew")
        self.beginner_preflight_button = ttk.Button(frame, text="生成新手预检报告", command=self.run_beginner_preflight)
        self.beginner_preflight_button.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(8, 0))

        tips = (
            "三步式：先预检/预览，确认 DOI 后正式下载，结束后打开研究生查看入口。"
            "支持 .xlsx/.xlsm/.csv/.txt/.md/.markdown/.tsv。"
        )
        ttk.Label(frame, text=tips, foreground="#555555", wraplength=520).grid(
            row=8, column=0, columnspan=3, sticky="ew", pady=(10, 0)
        )

    def _build_common_options(self, frame: ttk.Frame, compact: bool) -> None:
        for i in range(3):
            frame.columnconfigure(i, weight=1)

        ttk.Label(frame, text="输出目录").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.output_var).grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=(0, 8), pady=(2, 8)
        )
        ttk.Button(frame, text="选择", command=self.choose_output_dir).grid(row=1, column=2, sticky="ew", pady=(2, 8))

        ttk.Label(frame, text="Cookie JSON 文件").grid(row=2, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.cookies_file_var).grid(
            row=3, column=0, columnspan=2, sticky="ew", padx=(0, 8), pady=(2, 8)
        )
        ttk.Button(frame, text="选择", command=self.choose_cookies_file).grid(row=3, column=2, sticky="ew", pady=(2, 8))

        ttk.Label(frame, text="自定义文件名").grid(row=4, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.filename_var).grid(row=5, column=0, columnspan=3, sticky="ew", pady=(2, 8))


        next_row = 8
        if compact:
            ttk.Label(frame, text="历史结果目录（断点恢复）").grid(row=8, column=0, sticky="w")
            ttk.Entry(frame, textvariable=self.resume_from_var).grid(
                row=9, column=0, columnspan=2, sticky="ew", padx=(0, 8), pady=(2, 8)
            )
            ttk.Button(frame, text="选择", command=self.choose_resume_dir).grid(row=9, column=2, sticky="ew", pady=(2, 8))
            next_row = 10

        ttk.Checkbutton(frame, text="检索后下载 PDF", variable=self.download_pdf_var).grid(
            row=next_row, column=0, columnspan=3, sticky="w", pady=(4, 2)
        )
        supplement_checkbutton = ttk.Checkbutton(frame, text="同时下载补充材料", variable=self.download_supplements_var)
        supplement_checkbutton.grid(row=next_row + 1, column=0, columnspan=3, sticky="w", pady=2)
        self.download_supplements_checkbuttons.append(supplement_checkbutton)

        ttk.Label(frame, text="高级登录方式", foreground="#444444").grid(
            row=next_row + 2, column=0, columnspan=3, sticky="w", pady=(8, 0)
        )
        ttk.Checkbutton(frame, text="从本机浏览器读取 Cookie", variable=self.browser_cookies_var).grid(
            row=next_row + 3, column=0, columnspan=3, sticky="w", pady=2
        )
        ttk.Checkbutton(frame, text="先弹出浏览器手动登录", variable=self.open_login_var).grid(
            row=next_row + 4, column=0, columnspan=3, sticky="w", pady=2
        )

        if compact:
            text = "推荐：优先选择 Cookie Editor 导出的 cookies.json。PDF 和补充材料下载依赖机构权限和 Cookie 有效性。"
            wrap = 500
        else:
            text = (
                "推荐：优先选择 Cookie JSON。未提供 Cookie 文件时，可使用本机浏览器 Cookie；"
                "手动登录会等待你在调试浏览器中完成机构登录。"
            )
            wrap = 420
        ttk.Label(frame, text=text, foreground="#555555", wraplength=wrap).grid(
            row=next_row + 5, column=0, columnspan=3, sticky="ew", pady=(8, 0)
        )

    def _bind_updates(self) -> None:
        for var in (
            self.workflow_var,
            self.mode_var,
            self.query_var,
            self.journal_var,
            self.author_var,
            self.issn_var,
            self.date_var,
            self.count_var,
            self.sort_var,
            self.article_type_var,
            self.format_var,
            self.output_var,
            self.filename_var,
            self.input_file_var,
            self.doi_column_var,
            self.sheet_var,
            self.resume_from_var,
            self.cookies_file_var,
            self.oa_input_file_var,
            self.oa_email_var,
            self.oa_limit_var,
            self.batch_action_var,
            self.batch_input_file_var,
            self.batch_run_dir_var,
            self.batch_run_name_var,
            self.batch_login_wait_var,
            self.batch_library_id_var,
            self.batch_wait_seconds_var,
            self.browser_cookies_var,
            self.open_login_var,
            self.download_pdf_var,
            self.download_supplements_var,
            self.open_access_var,
            self.oa_dry_run_var,
            self.oa_overwrite_var,
        ):
            var.trace_add("write", self._on_parameter_changed)

    def _on_parameter_changed(self, *_args: object) -> None:
        self._sync_download_supplements_state()
        self._refresh_command_preview()
        self._refresh_task_summary()
        self._save_settings()

    def _sync_download_supplements_state(self) -> None:
        state = ["!disabled"] if self.download_pdf_var.get() else ["disabled"]
        for checkbutton in getattr(self, "download_supplements_checkbuttons", []):
            checkbutton.state(state)

    def _on_paste_text_changed(self, *_args: object) -> None:
        self.root.after_idle(self._on_parameter_changed)

    def _on_oa_text_changed(self, *_args: object) -> None:
        self.root.after_idle(self._on_parameter_changed)

    def _on_batch_text_changed(self, *_args: object) -> None:
        self.root.after_idle(self._on_parameter_changed)

    def _on_tab_changed(self, _event: object) -> None:
        selected = self.notebook.select()
        if selected == str(self.batch_tab):
            self.workflow_var.set("paper_batch")
        elif selected == str(self.doi_tab):
            self.workflow_var.set("sciencedirect")
            if self.mode_var.get() != "doi_batch":
                self.mode_var.set("doi_batch")
        elif selected == str(self.search_tab):
            self.workflow_var.set("sciencedirect")
            if self.mode_var.get() == "doi_batch":
                self.mode_var.set("keyword")
        elif selected == str(self.oa_tab):
            self.workflow_var.set("legal_oa")
        self._refresh_task_summary()
        if self.ui_ready:
            self._save_settings()

    def _refresh_task_summary(self) -> None:
        if self.workflow_var.get() == "paper_batch":
            action = self.batch_action_var.get().strip() or "start"
            output_dir = self.output_var.get().strip() or "(默认 results)"
            run_dir = self.batch_run_dir_var.get().strip() or "未选择"
            if action == "start":
                source = self.batch_input_file_var.get().strip() or ("粘贴内容" if self._get_batch_text() else "未选择")
                email = self.oa_email_var.get().strip() or "未填写（Unpaywall 将跳过）"
                cookie = self.cookies_file_var.get().strip() or "未选择 Cookie"
                library_id = self.batch_library_id_var.get().strip() or "1"
                wait_seconds = self.batch_wait_seconds_var.get().strip() or "0"
                summary = (
                    f"统一批次 start：输入={source}；输出根目录={output_dir}；"
                    f"邮箱={email}；Cookie={cookie}；流程=OA→机构→失败自动 Zotero；"
                    f"library-id={library_id}；wait-seconds={wait_seconds}。"
                )
            elif action == "resume":
                summary = f"统一批次 resume（兼容）：run-dir={run_dir}；仅重试一次登录/验证码失败项。"
            else:
                library_id = self.batch_library_id_var.get().strip() or "1"
                wait_seconds = self.batch_wait_seconds_var.get().strip() or "0"
                summary = (
                    f"统一批次 zotero：run-dir={run_dir}；library-id={library_id}；"
                    f"wait-seconds={wait_seconds}。"
                )
            self.summary_var.set(summary)
            preflight_items = self._get_preflight_items()
            warnings = [message for level, message in preflight_items if level != "ok"]
            self.warning_var.set("；".join(warnings))
            self._refresh_preflight_panel(preflight_items)
            return

        if self.workflow_var.get() == "legal_oa":
            output_dir = self.output_var.get().strip() or "(默认 results)"
            input_text = self.oa_input_file_var.get().strip() or ("粘贴内容" if self._get_oa_text() else "未选择")
            action = "仅解析" if self.oa_dry_run_var.get() else "尝试下载公开开放获取 PDF"
            limit = self.oa_limit_var.get().strip() or "不限制"
            summary = f"OA 资源辅助获取：输入={input_text}；输出={output_dir}；任务={action}；限制数量={limit}；不使用 Cookie/机构登录。"
            self.summary_var.set(summary)
            preflight_items = self._get_preflight_items()
            warnings = [message for level, message in preflight_items if level != "ok"]
            self.warning_var.set("；".join(warnings))
            self._refresh_preflight_panel(preflight_items)
            return

        mode = self.mode_var.get()
        output_dir = self.output_var.get().strip() or "(默认 results)"
        cookie_path = self.cookies_file_var.get().strip()
        if cookie_path:
            cookie_source = check_cookie_json(cookie_path).message
        elif self.browser_cookies_var.get():
            cookie_source = "本机浏览器 Cookie"
        elif self.open_login_var.get():
            cookie_source = "手动登录浏览器"
        else:
            cookie_source = "未选择 Cookie"
        if self.download_pdf_var.get():
            pdf_text = "下载 PDF+补充材料" if self.download_supplements_var.get() else "下载 PDF"
        else:
            pdf_text = "仅保存元数据/解析结果"

        if mode == "doi_batch":
            input_text = self.input_file_var.get().strip() or ("粘贴内容" if self._get_pasted_text() else "未选择")
            doi_col = self.doi_column_var.get().strip() or "自动识别"
            summary = f"DOI 批量：输入={input_text}；DOI列={doi_col}；输出={output_dir}；权限={cookie_source}；任务={pdf_text}。"
        else:
            fields = []
            if self.query_var.get().strip():
                fields.append(f"关键词={self.query_var.get().strip()}")
            if self.journal_var.get().strip():
                fields.append(f"期刊={self.journal_var.get().strip()}")
            if self.author_var.get().strip():
                fields.append(f"作者={self.author_var.get().strip()}")
            if self.issn_var.get().strip():
                fields.append(f"ISSN={self.issn_var.get().strip()}")
            if self.date_var.get().strip():
                fields.append(f"年份={self.date_var.get().strip()}")
            condition = "；".join(fields) if fields else "未填写检索条件"
            summary = f"文献检索：模式={mode}；{condition}；输出={output_dir}；权限={cookie_source}；任务={pdf_text}。"
        self.summary_var.set(summary)

        preflight_items = self._get_preflight_items()
        warnings = [message for level, message in preflight_items if level != "ok"]
        self.warning_var.set("；".join(warnings))
        self._refresh_preflight_panel(preflight_items)

    def _get_preflight_items(self) -> list[tuple[str, str]]:
        if self.workflow_var.get() == "paper_batch":
            items: list[tuple[str, str]] = list(("warn", warning) for warning in self.startup_warnings)
            if not BATCH_SCRIPT.exists():
                items.append(("error", f"找不到统一批次脚本: {BATCH_SCRIPT}"))
            action = self.batch_action_var.get().strip() or "start"
            if action not in BATCH_ACTIONS:
                items.append(("error", f"未知子命令: {action}"))
            if action == "start":
                input_path = self.batch_input_file_var.get().strip()
                pasted = self._get_batch_text()
                if input_path:
                    if Path(input_path).exists():
                        items.append(("ok", f"批次输入文件存在: {input_path}"))
                    else:
                        items.append(("error", f"批次输入文件不存在: {input_path}"))
                elif pasted:
                    items.append(("ok", "已填写批次粘贴内容"))
                else:
                    items.append(("error", "start 需要选择文献清单或粘贴内容"))
                output_dir = Path(self.output_var.get().strip() or APP_DIR / "results")
                if output_dir.exists():
                    if output_dir.is_dir() and os.access(output_dir, os.W_OK):
                        items.append(("ok", f"输出目录可写: {output_dir}"))
                    else:
                        items.append(("error", f"输出目录不可写: {output_dir}"))
                elif output_dir.parent.exists() and os.access(output_dir.parent, os.W_OK):
                    items.append(("warn", f"输出目录不存在，运行时会尝试创建: {output_dir}"))
                else:
                    items.append(("error", f"输出目录父目录不可写或不存在: {output_dir.parent}"))
                if not self.oa_email_var.get().strip():
                    items.append(("warn", "未填写邮箱：Unpaywall OA 查询将跳过，公开 OA 候选命中率会下降"))
                cookie_path = self.cookies_file_var.get().strip()
                if cookie_path:
                    items.append(("ok", check_cookie_json(cookie_path).message))
                else:
                    items.append(("warn", "未选择 Cookie：非 OA 的机构下载可能需要浏览器登录"))
            else:
                run_dir = self.batch_run_dir_var.get().strip()
                if not run_dir:
                    items.append(("error", f"{action} 需要填写已有批次目录 --run-dir"))
                elif not Path(run_dir).is_dir():
                    items.append(("error", f"批次目录不存在: {run_dir}"))
                else:
                    items.append(("ok", f"批次目录存在: {run_dir}"))
                    state_path = Path(run_dir) / "working" / "batch_state.json"
                    if state_path.is_file():
                        items.append(("ok", "检测到 batch_state.json"))
                    else:
                        items.append(("warn", "未检测到 working/batch_state.json，请确认目录是否为完整批次"))
                if action == "zotero":
                    library_id = self.batch_library_id_var.get().strip() or "1"
                    if not library_id.isdigit() or int(library_id) <= 0:
                        items.append(("error", "library-id 必须是正整数"))
                    wait_seconds = self.batch_wait_seconds_var.get().strip() or "0"
                    if not wait_seconds.isdigit() or not (0 <= int(wait_seconds) <= 86400):
                        items.append(("error", "wait-seconds 必须是 0–86400 的整数"))
            return items

        if self.workflow_var.get() == "legal_oa":
            items = []
            input_path = self.oa_input_file_var.get().strip()
            pasted_text = self._get_oa_text()
            if input_path:
                if Path(input_path).exists():
                    items.append(("ok", f"OA 输入文件存在: {input_path}"))
                else:
                    items.append(("error", f"OA 输入文件不存在: {input_path}"))
            elif pasted_text:
                items.append(("ok", "已填写 OA 粘贴内容"))
            else:
                items.append(("error", "OA 资源辅助获取需要选择输入文件或粘贴论文列表"))

            output_dir = Path(self.output_var.get().strip() or APP_DIR / "results")
            if output_dir.exists():
                if output_dir.is_dir() and os.access(output_dir, os.W_OK):
                    items.append(("ok", f"输出目录可写: {output_dir}"))
                else:
                    items.append(("error", f"输出目录不可写: {output_dir}"))
            elif output_dir.parent.exists() and os.access(output_dir.parent, os.W_OK):
                items.append(("warn", f"输出目录不存在，运行时会尝试创建: {output_dir}"))
            else:
                items.append(("error", f"输出目录父目录不可写或不存在: {output_dir.parent}"))
            items.append(("ok", "OA 资源辅助获取不使用 Cookie 或机构登录"))
            return items

        items = [("warn", warning) for warning in self.startup_warnings]
        if self.mode_var.get() == "doi_batch":
            input_path = self.input_file_var.get().strip()
            pasted_text = self._get_pasted_text()
            if input_path:
                if Path(input_path).exists():
                    items.append(("ok", f"输入文件存在: {input_path}"))
                else:
                    items.append(("error", f"输入文件不存在: {input_path}"))
            elif pasted_text:
                doi_count = sum(1 for line in pasted_text.splitlines() if extract_doi_from_text(line))
                if doi_count:
                    items.append(("ok", f"粘贴内容可识别 {doi_count} 条 DOI"))
                else:
                    items.append(("error", "粘贴内容中未识别到 DOI"))
            else:
                items.append(("error", "需要先选择 DOI 文件或粘贴 DOI 内容"))

            output_dir = Path(self.output_var.get().strip() or APP_DIR / "results")
            if output_dir.exists():
                if output_dir.is_dir() and os.access(output_dir, os.W_OK):
                    items.append(("ok", f"输出目录可写: {output_dir}"))
                else:
                    items.append(("error", f"输出目录不可写: {output_dir}"))
            elif output_dir.parent.exists() and os.access(output_dir.parent, os.W_OK):
                items.append(("warn", f"输出目录不存在，运行时会尝试创建: {output_dir}"))
            else:
                items.append(("error", f"输出目录父目录不可写或不存在: {output_dir.parent}"))

            resume_dir = self.resume_from_var.get().strip()
            if resume_dir:
                if Path(resume_dir).is_dir():
                    items.append(("ok", f"断点恢复目录存在: {resume_dir}"))
                else:
                    items.append(("error", f"断点恢复目录不存在: {resume_dir}"))

        cookie_path = self.cookies_file_var.get().strip()
        if not self.download_pdf_var.get():
            items.append(("ok", "PDF 下载未开启，仅保存解析结果"))
        elif cookie_path:
            cookie_check = check_cookie_json(cookie_path)
            level = "ok" if cookie_check.is_usable else "warn"
            items.append((level, cookie_check.message))
        elif self.browser_cookies_var.get():
            items.append(("warn", "未选择 Cookie JSON；将尝试从本机浏览器读取 Cookie"))
        elif self.open_login_var.get():
            items.append(("warn", "未选择 Cookie JSON；运行时将等待手动登录浏览器"))
        else:
            items.append(("warn", "下载 PDF 通常需要 Cookie JSON 或已登录的 Edge/浏览器"))
        return items

    def _refresh_preflight_panel(self, items: list[tuple[str, str]]) -> None:
        if not hasattr(self, "preflight_text"):
            return
        labels = {"ok": "OK", "warn": "WARN", "error": "BLOCK"}
        lines = [f"[{labels.get(level, level.upper())}] {message}" for level, message in items]
        self.preflight_text.configure(state="normal")
        self.preflight_text.delete("1.0", "end")
        self.preflight_text.insert("end", "\n".join(lines) if lines else "[OK] 未发现本地体检问题")
        self.preflight_text.configure(state="disabled")

    def _validate_inputs(self) -> bool:
        if self.workflow_var.get() == "paper_batch":
            if not BATCH_SCRIPT.exists():
                messagebox.showerror("文件缺失", f"找不到必要脚本：\n{BATCH_SCRIPT}")
                return False
            action = self.batch_action_var.get().strip() or "start"
            if action not in BATCH_ACTIONS:
                messagebox.showerror("参数错误", f"未知统一批次子命令：{action}")
                return False
            if action == "start":
                input_path = self.batch_input_file_var.get().strip()
                if not input_path and not self._get_batch_text():
                    messagebox.showerror("参数错误", "start 需要选择文献清单，或粘贴 DOI/题名列表。")
                    return False
                if input_path and not Path(input_path).exists():
                    messagebox.showerror("参数错误", f"输入文件不存在：\n{input_path}")
                    return False
                wait_text = self.batch_login_wait_var.get().strip() or "0"
                try:
                    if int(wait_text) < 0:
                        raise ValueError
                except ValueError:
                    messagebox.showerror("参数错误", "登录等待秒数必须是非负整数。")
                    return False
                try:
                    output_dir = Path(self.output_var.get().strip() or APP_DIR / "results")
                    output_dir.mkdir(parents=True, exist_ok=True)
                    probe = output_dir / ".write_test.tmp"
                    probe.write_text("ok", encoding="utf-8")
                    probe.unlink(missing_ok=True)
                except Exception as exc:
                    messagebox.showerror("输出目录不可写", str(exc))
                    return False
            else:
                run_dir = self.batch_run_dir_var.get().strip()
                if not run_dir:
                    messagebox.showerror("参数错误", f"{action} 需要填写已有批次目录。")
                    return False
                if not Path(run_dir).is_dir():
                    messagebox.showerror("参数错误", f"批次目录不存在：\n{run_dir}")
                    return False
                if action == "zotero":
                    library_id = self.batch_library_id_var.get().strip() or "1"
                    wait_seconds = self.batch_wait_seconds_var.get().strip() or "0"
                    try:
                        if int(library_id) <= 0:
                            raise ValueError
                    except ValueError:
                        messagebox.showerror("参数错误", "library-id 必须是正整数。")
                        return False
                    try:
                        if not (0 <= int(wait_seconds) <= 86400):
                            raise ValueError
                    except ValueError:
                        messagebox.showerror("参数错误", "wait-seconds 必须是 0–86400 的整数。")
                        return False
            return True

        if self.workflow_var.get() == "legal_oa":
            input_path = self.oa_input_file_var.get().strip()
            if not input_path and not self._get_oa_text():
                messagebox.showerror("参数错误", "OA 资源辅助获取需要选择输入文件，或粘贴论文列表。")
                return False
            if input_path and not Path(input_path).exists():
                messagebox.showerror("参数错误", f"输入文件不存在：\n{input_path}")
                return False
            limit = self.oa_limit_var.get().strip()
            if limit:
                try:
                    if int(limit) <= 0:
                        raise ValueError
                except ValueError:
                    messagebox.showerror("参数错误", "测试限制数量必须是正整数，例如 20。")
                    return False
            try:
                output_dir = Path(self.output_var.get().strip() or APP_DIR / "results")
                output_dir.mkdir(parents=True, exist_ok=True)
                probe = output_dir / ".write_test.tmp"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink(missing_ok=True)
            except Exception as exc:
                messagebox.showerror("输出目录不可写", str(exc))
                return False
            return True

        if (
            self.mode_var.get() == "doi_batch"
            and not self.input_file_var.get().strip()
            and not self._get_pasted_text()
        ):
            messagebox.showerror("参数错误", "DOI 批量下载模式需要选择输入表格，或在粘贴框中粘贴 DOI。")
            return False
        if self.mode_var.get() == "doi_batch":
            input_path = self.input_file_var.get().strip()
            if input_path and not Path(input_path).exists():
                messagebox.showerror("参数错误", f"输入文件不存在：\n{input_path}")
                return False
            resume_dir = self.resume_from_var.get().strip()
            if resume_dir and not Path(resume_dir).is_dir():
                messagebox.showerror("参数错误", f"断点恢复目录不存在：\n{resume_dir}")
                return False
            if not input_path and self._get_pasted_text() and not any(
                extract_doi_from_text(line) for line in self._get_pasted_text().splitlines()
            ):
                messagebox.showerror("参数错误", "粘贴内容中没有识别到 DOI。")
                return False
        try:
            count = int(self.count_var.get().strip())
            if count <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("参数错误", "最大数量必须是正整数，例如 50。")
            return False
        mode = self.mode_var.get()
        if mode == "keyword" and not self.query_var.get().strip():
            messagebox.showerror("参数错误", "关键词检索需要填写关键词。")
            return False
        if mode == "journal" and not self.journal_var.get().strip():
            messagebox.showerror("参数错误", "期刊浏览需要填写期刊名称。")
            return False
        if mode == "journal_keyword" and (
            not self.journal_var.get().strip() or not self.query_var.get().strip()
        ):
            messagebox.showerror("参数错误", "期刊+关键词检索需要同时填写期刊名称和关键词。")
            return False
        if mode == "author" and not self.author_var.get().strip():
            messagebox.showerror("参数错误", "作者检索需要填写作者姓名。")
            return False
        if mode == "issn" and not self.issn_var.get().strip():
            messagebox.showerror("参数错误", "ISSN 检索需要填写 ISSN。")
            return False
        if mode == "advanced" and not any(
            var.get().strip()
            for var in (
                self.query_var,
                self.journal_var,
                self.author_var,
                self.issn_var,
                self.date_var,
                self.article_type_var,
            )
        ) and not self.open_access_var.get():
            messagebox.showerror("参数错误", "高级检索至少需要填写一个检索条件或筛选项。")
            return False
        try:
            output_dir = Path(self.output_var.get().strip() or APP_DIR / "results")
            output_dir.mkdir(parents=True, exist_ok=True)
            probe = output_dir / ".write_test.tmp"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except Exception as exc:
            messagebox.showerror("输出目录不可写", str(exc))
            return False
        cookie_path = self.cookies_file_var.get().strip()
        if self.download_pdf_var.get() and cookie_path:
            cookie_check = check_cookie_json(cookie_path)
            if not cookie_check.is_usable and not messagebox.askyesno(
                "Cookie 检查提示",
                f"{cookie_check.message}\n\n仍要继续运行吗？PDF 下载可能失败。",
            ):
                return False
        if (
            self.download_pdf_var.get()
            and not cookie_path
            and not self.browser_cookies_var.get()
            and not self.open_login_var.get()
            and not messagebox.askyesno(
                "缺少 Cookie",
                "当前开启了 PDF 下载，但没有选择 Cookie JSON，也没有启用浏览器 Cookie/手动登录。\n\n仍要继续运行吗？",
            )
        ):
            return False
        return True

    def _build_command(self, materialize_paste: bool = False, auto_retry_input: bool = False) -> list[str]:
        if self.workflow_var.get() == "paper_batch":
            return self._build_paper_batch_command(materialize_paste=materialize_paste)

        if self.workflow_var.get() == "legal_oa":
            cmd = [sys.executable, "-u", str(OA_SCRIPT)]
            input_path = self.oa_input_file_var.get().strip()
            if input_path:
                self._append_value(cmd, "--input", input_path)
            elif self._get_oa_text():
                if materialize_paste:
                    self._append_value(cmd, "--input", str(self._write_pasted_oa_text()))
                else:
                    self._append_value(cmd, "--text", "<粘贴内容将在运行时传入>")
            self._append_value(cmd, "--out", self.output_var.get())
            self._append_value(cmd, "--email", self.oa_email_var.get())
            self._append_value(cmd, "--limit", self.oa_limit_var.get())
            if self.oa_dry_run_var.get():
                cmd.append("--dry-run")
            if self.oa_overwrite_var.get():
                cmd.append("--overwrite")
            return cmd

        cmd = [sys.executable, "-u", str(SD_SCRIPT)]

        self._append_value(cmd, "-m", self.mode_var.get())
        if self.mode_var.get() == "doi_batch":
            input_path = self.input_file_var.get().strip()
            if not input_path and self._get_pasted_text():
                input_path = str(self._write_pasted_doi_csv()) if materialize_paste else "<粘贴内容将在运行时生成CSV>"
            self._append_value(cmd, "--input", input_path)
            self._append_value(cmd, "--doi-column", self.doi_column_var.get() or ("doi" if self._get_pasted_text() and not self.input_file_var.get().strip() else ""))
            input_ext = Path(input_path).suffix.lower()
            if input_ext in {".xlsx", ".xlsm"}:
                self._append_value(cmd, "--sheet", self.sheet_var.get())
            self._append_value(cmd, "--output", self.output_var.get())
            self._append_value(cmd, "--filename", self.filename_var.get())
            self._append_value(cmd, "--resume-from", self.resume_from_var.get())
            self._append_value(cmd, "--cookies", self.cookies_file_var.get())
            if not self.cookies_file_var.get().strip() and self.browser_cookies_var.get() and self.download_pdf_var.get():
                cmd.append("--browser-cookies")
            if self.open_login_var.get():
                cmd.append("--open-browser-login")
            if self.download_pdf_var.get():
                cmd.append("--download-pdfs")
                if not self.download_supplements_var.get():
                    cmd.append("--no-download-supplements")
            if auto_retry_input:
                cmd.append("--auto-retry-input")
            return cmd

        self._append_value(cmd, "-q", self.query_var.get())
        self._append_value(cmd, "-j", self.journal_var.get())
        self._append_value(cmd, "-a", self.author_var.get())
        self._append_value(cmd, "--issn", self.issn_var.get())
        self._append_value(cmd, "--date", self.date_var.get())
        self._append_value(cmd, "-n", self.count_var.get())
        self._append_value(cmd, "--sort", self.sort_var.get())
        self._append_value(cmd, "--type", self.article_type_var.get())
        self._append_value(cmd, "--format", self.format_var.get())
        self._append_value(cmd, "--output", self.output_var.get())
        self._append_value(cmd, "--filename", self.filename_var.get())
        self._append_value(cmd, "--cookies", self.cookies_file_var.get())

        if self.open_access_var.get():
            cmd.append("--open-access")
        if not self.cookies_file_var.get().strip() and self.browser_cookies_var.get():
            cmd.append("--browser-cookies")
        if self.open_login_var.get():
            cmd.append("--open-browser-login")
        if self.download_pdf_var.get():
            cmd.append("--download-pdfs")
            if not self.download_supplements_var.get():
                cmd.append("--no-download-supplements")

        return cmd

    def _build_paper_batch_command(self, materialize_paste: bool = False) -> list[str]:
        action = self.batch_action_var.get().strip() or "start"
        cmd = [sys.executable, "-u", str(BATCH_SCRIPT), action]
        if action == "start":
            input_path = self.batch_input_file_var.get().strip()
            if input_path:
                self._append_value(cmd, "--input", input_path)
            elif self._get_batch_text():
                if materialize_paste:
                    self._append_value(cmd, "--text", self._get_batch_text())
                else:
                    self._append_value(cmd, "--text", "<粘贴内容将在运行时传入>")
            self._append_value(cmd, "--out", self.output_var.get().strip() or str(APP_DIR / "results"))
            self._append_value(cmd, "--run-name", self.batch_run_name_var.get())
            self._append_value(cmd, "--email", self.oa_email_var.get())
            self._append_value(cmd, "--cookies", self.cookies_file_var.get())
            wait_text = self.batch_login_wait_var.get().strip()
            if wait_text and wait_text != "0":
                self._append_value(cmd, "--login-wait-seconds", wait_text)
            library_id = self.batch_library_id_var.get().strip() or "1"
            self._append_value(cmd, "--library-id", library_id)
            wait_seconds = self.batch_wait_seconds_var.get().strip() or "0"
            if wait_seconds and wait_seconds != "0":
                self._append_value(cmd, "--wait-seconds", wait_seconds)
            return cmd

        self._append_value(cmd, "--run-dir", self.batch_run_dir_var.get())
        if action == "zotero":
            library_id = self.batch_library_id_var.get().strip() or "1"
            wait_seconds = self.batch_wait_seconds_var.get().strip() or "0"
            self._append_value(cmd, "--library-id", library_id)
            if wait_seconds and wait_seconds != "0":
                self._append_value(cmd, "--wait-seconds", wait_seconds)
        return cmd

    def _build_beginner_preflight_command(self, materialize_paste: bool = False) -> list[str]:
        cmd = [sys.executable, "-u", str(SD_SKILL_SCRIPT)]
        input_path = self.input_file_var.get().strip()
        pasted_text = self._get_pasted_text()
        if input_path:
            self._append_value(cmd, "--input", input_path)
            input_ext = Path(input_path).suffix.lower()
            if input_ext in {".xlsx", ".xlsm"}:
                self._append_value(cmd, "--sheet", self.sheet_var.get())
        elif pasted_text:
            if materialize_paste:
                self._append_value(cmd, "--text", pasted_text)
            else:
                self._append_value(cmd, "--text", "<粘贴内容将在运行时传入>")
        self._append_value(cmd, "--out", self.output_var.get())
        self._append_value(cmd, "--doi-column", self.doi_column_var.get())
        cmd.extend(["--beginner", "--preflight"])
        return cmd

    @staticmethod
    def _append_value(cmd: list[str], flag: str, value: str) -> None:
        value = value.strip()
        if value:
            cmd += [flag, value]

    def _refresh_command_preview(self) -> None:
        try:
            cmd = self._build_command(materialize_paste=False)
            self.command_var.set(self._format_command(cmd))
        except Exception as exc:
            self.command_var.set(f"命令预览生成失败: {exc}")

    def _format_command(self, cmd: list[str]) -> str:
        return " ".join(self._quote_for_preview(part) for part in cmd)

    @staticmethod
    def _quote_for_preview(part: str) -> str:
        if not part:
            return '""'
        if any(ch.isspace() for ch in part):
            return '"' + part.replace('"', '\\"') + '"'
        return part

    def choose_output_dir(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_var.get() or str(APP_DIR))
        if selected:
            self.output_var.set(selected)

    def choose_input_file(self) -> None:
        selected = filedialog.askopenfilename(
            initialdir=str(APP_DIR),
            filetypes=[
                ("支持的输入文件", "*.xlsx *.xlsm *.csv *.tsv *.txt *.md *.markdown"),
                ("Excel 文件", "*.xlsx *.xlsm"),
                ("表格文本", "*.csv *.tsv"),
                ("纯文本/Markdown", "*.txt *.md *.markdown"),
                ("所有文件", "*.*"),
            ],
        )
        if selected:
            self.input_file_var.set(selected)
            self.preview_status_var.set("已选择文件，建议点击预览解析")

    def choose_oa_input_file(self) -> None:
        selected = filedialog.askopenfilename(
            initialdir=str(APP_DIR),
            filetypes=[
                ("OA 资源输入文件", "*.txt *.md *.markdown *.csv"),
                ("纯文本/Markdown", "*.txt *.md *.markdown"),
                ("CSV 文件", "*.csv"),
                ("所有文件", "*.*"),
            ],
        )
        if selected:
            self.oa_input_file_var.set(selected)

    def choose_batch_input_file(self) -> None:
        selected = filedialog.askopenfilename(
            initialdir=str(APP_DIR),
            filetypes=[
                ("支持的输入文件", "*.xlsx *.xlsm *.csv *.tsv *.txt *.md *.markdown"),
                ("Excel 文件", "*.xlsx *.xlsm"),
                ("表格文本", "*.csv *.tsv"),
                ("纯文本/Markdown", "*.txt *.md *.markdown"),
                ("所有文件", "*.*"),
            ],
        )
        if selected:
            self.batch_input_file_var.set(selected)
            if self.batch_action_var.get().strip() != "start":
                self.batch_action_var.set("start")

    def choose_batch_run_dir(self) -> None:
        selected = filedialog.askdirectory(
            initialdir=self.batch_run_dir_var.get().strip()
            or self.output_var.get().strip()
            or str(APP_DIR / "results")
        )
        if selected:
            self.batch_run_dir_var.set(selected)

    def choose_cookies_file(self) -> None:
        selected = filedialog.askopenfilename(
            initialdir=str(APP_DIR),
            filetypes=[
                ("Cookie JSON", "*.json"),
                ("所有文件", "*.*"),
            ],
        )
        if selected:
            self.cookies_file_var.set(selected)
            self.browser_cookies_var.set(False)

    def choose_resume_dir(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_var.get() or str(APP_DIR))
        if selected:
            self.resume_from_var.set(selected)

    def create_doi_template(self) -> None:
        selected = filedialog.asksaveasfilename(
            initialdir=self.output_var.get() or str(APP_DIR),
            initialfile="doi_batch_template.xlsx",
            defaultextension=".xlsx",
            filetypes=[("Excel 文件", "*.xlsx"), ("所有文件", "*.*")],
        )
        if not selected:
            return
        try:
            from openpyxl import Workbook

            wb = Workbook()
            ws = wb.active
            ws.title = "papers"
            ws.append(["title", "authors", "year", "doi"])
            ws.append(["Example title", "Zhang; Li", "2024", "10.xxxx/xxxxx"])
            wb.save(selected)
            self.input_file_var.set(selected)
            self.preview_status_var.set("已生成 DOI 模板，请填写后再预览解析")
            messagebox.showinfo("模板已生成", f"DOI 模板已保存：\n{selected}")
        except Exception as exc:
            messagebox.showerror("生成模板失败", str(exc))

    def _get_pasted_text(self) -> str:
        if not hasattr(self, "paste_text"):
            return ""
        return self.paste_text.get("1.0", "end").strip()

    def _get_oa_text(self) -> str:
        if not hasattr(self, "oa_text"):
            return ""
        return self.oa_text.get("1.0", "end").strip()

    def _get_batch_text(self) -> str:
        if not hasattr(self, "batch_text"):
            return ""
        return self.batch_text.get("1.0", "end").strip()

    @staticmethod
    def _extract_doi_from_text(text: str) -> str:
        return extract_doi_from_text(text)

    def _write_pasted_doi_csv(self) -> Path:
        text = self._get_pasted_text()
        out_dir = APP_DIR / "results" / "_ui_inputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"pasted_doi_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        rows = []
        for line in text.splitlines():
            doi = self._extract_doi_from_text(line)
            if doi:
                rows.append({"doi": doi, "title": ""})

        if not rows:
            raise ValueError("粘贴内容中没有识别到 DOI")

        with out_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["doi", "title"])
            writer.writeheader()
            writer.writerows(rows)
        return out_path

    def _write_pasted_oa_text(self) -> Path:
        text = self._get_oa_text()
        if not text:
            raise ValueError("OA 资源粘贴内容为空")
        out_dir = APP_DIR / "results" / "_ui_inputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"pasted_oa_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        out_path.write_text(text, encoding="utf-8")
        return out_path

    def clear_paste_text(self) -> None:
        self.paste_text.delete("1.0", "end")
        self._clear_preview_rows()
        self.preview_status_var.set("未预览")
        self._refresh_command_preview()
        self._refresh_task_summary()

    def clear_oa_text(self) -> None:
        if hasattr(self, "oa_text"):
            self.oa_text.delete("1.0", "end")
        self._refresh_command_preview()
        self._refresh_task_summary()

    def clear_batch_text(self) -> None:
        if hasattr(self, "batch_text"):
            self.batch_text.delete("1.0", "end")
        self._refresh_command_preview()
        self._refresh_task_summary()

    def preview_doi_input(self) -> None:
        if self.mode_var.get() != "doi_batch":
            messagebox.showinfo("预览解析", "预览解析仅用于 doi_batch 模式。")
            return
        if not self.input_file_var.get().strip() and not self._get_pasted_text():
            messagebox.showerror("预览解析", "请先选择 DOI 表格，或粘贴 DOI 内容。")
            return

        self.preview_button.configure(state="disabled")
        self.preview_status_var.set("正在后台解析预览...")
        self._clear_preview_rows()
        threading.Thread(target=self._preview_worker, daemon=True).start()

    def _preview_worker(self) -> None:
        try:
            if self.input_file_var.get().strip():
                preview = preview_doi_data(
                    input_path=Path(self.input_file_var.get().strip()),
                    doi_column=self.doi_column_var.get().strip() or None,
                    sheet_name=self.sheet_var.get().strip() or None,
                    limit=PREVIEW_LIMIT,
                )
            else:
                preview = preview_doi_data(
                    pasted_text=self._get_pasted_text(),
                    doi_column=self.doi_column_var.get().strip() or None,
                    sheet_name=self.sheet_var.get().strip() or None,
                    limit=PREVIEW_LIMIT,
                )
            self.preview_queue.put(("ok", preview))
        except Exception as exc:
            self.preview_queue.put(("error", str(exc)))

    def _drain_preview_queue(self) -> None:
        try:
            while True:
                item = self.preview_queue.get_nowait()
                kind = item[0]
                if kind == "ok":
                    preview = item[1]
                    self._apply_doi_preview(preview)
                    self.preview_button.configure(state="normal")
                elif kind == "error":
                    self.preview_status_var.set("预览失败")
                    self.preview_button.configure(state="normal")
                    messagebox.showerror("预览解析失败", item[1])
        except queue.Empty:
            pass
        self.root.after(150, self._drain_preview_queue)

    def _apply_doi_preview(self, preview: object) -> None:
        self._clear_preview_rows()
        for row in preview.rows:
            title = row.title.replace("\t", " ")[:120]
            self.preview_tree.insert(
                "",
                "end",
                values=(
                    row.row_number,
                    PREVIEW_STATUS_LABELS.get(row.status, row.status),
                    row.doi,
                    title,
                    row.reason,
                ),
            )
        more = "" if preview.total_rows <= PREVIEW_LIMIT else f"，仅显示前 {PREVIEW_LIMIT} 行"
        detail = []
        if preview.doi_column:
            detail.append(f"列/方式: {preview.doi_column}")
        if preview.encoding:
            detail.append(f"编码: {preview.encoding}")
        if preview.sheet_name:
            detail.append(f"工作表: {preview.sheet_name}")
        counts = {
            key: preview.status_counts.get(key, 0)
            for key in ("valid", "duplicate", "empty", "invalid")
        }
        detail.append(
            "总行 {total}；有效 {valid}；重复 {duplicate}；空值 {empty}；异常 {invalid}".format(
                total=preview.total_rows,
                **counts,
            )
        )
        suffix = "；" + "，".join(detail) if detail else ""
        self.preview_status_var.set(f"识别到 {preview.total_doi} 条有效 DOI{more}{suffix}")

    def _clear_preview_rows(self) -> None:
        if not hasattr(self, "preview_tree"):
            return
        for item_id in self.preview_tree.get_children():
            self.preview_tree.delete(item_id)

    def run_smart_doi_wizard(self) -> None:
        if self.process is not None:
            messagebox.showinfo("正在运行", "当前任务还没有结束。")
            return
        if self.workflow_var.get() == "paper_batch":
            messagebox.showinfo(
                "智能准备并运行",
                "统一批次请直接点击“开始运行”。\n\n"
                "推荐：子命令选 start，填写清单后运行；失败项会自动排队 Zotero。"
                "若插件要求确认，在 Zotero 点一次后可用 zotero 子命令继续。",
            )
            return
        if self.workflow_var.get() == "legal_oa":
            messagebox.showinfo("智能准备并运行", "智能准备并运行仅用于 ScienceDirect DOI 批量下载。OA 资源辅助获取请直接点击“开始运行”。")
            return
        try:
            can_run, summary = self._prepare_smart_doi_wizard()
        except Exception as exc:
            messagebox.showerror("智能向导失败", str(exc))
            return
        self.last_smart_wizard_summary = summary
        if not can_run:
            messagebox.showerror("智能向导发现阻塞项", summary)
            return
        if messagebox.askyesno("智能准备并运行", summary + "\n\n确认后将开始运行。"):
            self.run_scraper(auto_retry_input=True)

    def _prepare_smart_doi_wizard(self) -> tuple[bool, str]:
        if self.mode_var.get() != "doi_batch":
            self.mode_var.set("doi_batch")

        input_path = self.input_file_var.get().strip()
        pasted_text = self._get_pasted_text()
        if not input_path and not pasted_text:
            return False, "需要先选择 DOI 文件，或粘贴 DOI 内容。"
        if input_path and not Path(input_path).exists():
            return False, f"输入文件不存在：{input_path}"

        if input_path:
            preview = preview_doi_data(
                input_path=Path(input_path),
                doi_column=self.doi_column_var.get().strip() or None,
                sheet_name=self.sheet_var.get().strip() or None,
                limit=PREVIEW_LIMIT,
            )
        else:
            preview = preview_doi_data(
                pasted_text=pasted_text,
                doi_column=self.doi_column_var.get().strip() or None,
                sheet_name=self.sheet_var.get().strip() or None,
                limit=PREVIEW_LIMIT,
            )
        self._apply_doi_preview(preview)
        if preview.doi_column and preview.doi_column != "逐行扫描" and not self.doi_column_var.get().strip():
            self.doi_column_var.set(preview.doi_column)
        if preview.total_doi <= 0:
            return False, "未识别到有效 DOI，请先检查输入文件或粘贴内容。"

        output_dir = Path(self.output_var.get().strip() or APP_DIR / "results")
        output_ok, output_message = self._check_output_dir_for_wizard(output_dir)
        if not output_ok:
            return False, output_message

        cookie_message = self._prepare_wizard_cookie_strategy()
        current_dois = {
            row.doi for row in preview.rows
            if getattr(row, "status", "") == "valid" and getattr(row, "doi", "")
        }
        resume_message = self._prepare_wizard_resume(output_dir, input_path, current_dois)
        self._refresh_command_preview()
        self._refresh_task_summary()

        counts = {
            key: preview.status_counts.get(key, 0)
            for key in ("valid", "duplicate", "empty", "invalid")
        }
        expected_output = self._expected_output_dir_text(output_dir)
        lines = [
            "智能向导已完成本地检查：",
            f"输入来源: {input_path or '粘贴内容'}",
            f"总行数: {preview.total_rows}",
            "有效 DOI: {valid}；重复: {duplicate}；空值: {empty}；异常: {invalid}".format(**counts),
            f"DOI 列/方式: {preview.doi_column or '自动识别'}",
            f"Cookie/权限: {cookie_message}",
            f"浏览器登录窗口: {'是' if self.open_login_var.get() else '否'}",
            f"断点恢复: {self.resume_from_var.get().strip() or '未启用'}",
            f"恢复建议: {resume_message}",
            f"预计输出目录: {expected_output}",
            "任务结束后: 自动生成可重试 DOI CSV，并填回 DOI 输入框；不会自动开始重试。",
        ]
        return True, "\n".join(lines)

    @staticmethod
    def _check_output_dir_for_wizard(output_dir: Path) -> tuple[bool, str]:
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            probe = output_dir / ".write_test.tmp"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except Exception as exc:
            return False, f"输出目录不可写：{exc}"
        return True, f"输出目录可写: {output_dir}"

    def _prepare_wizard_cookie_strategy(self) -> str:
        if not self.download_pdf_var.get():
            return "PDF 下载未开启"
        cookie_path = self.cookies_file_var.get().strip()
        if cookie_path:
            cookie_check = check_cookie_json(cookie_path)
            if cookie_check.is_usable:
                self.browser_cookies_var.set(False)
                self.open_login_var.set(False)
                return cookie_check.message
            self.cookies_file_var.set("")
            self.browser_cookies_var.set(False)
            self.open_login_var.set(True)
            return f"{cookie_check.message}；已改用浏览器登录引导"
        if not self.browser_cookies_var.get():
            self.open_login_var.set(True)
            return "未选择 Cookie JSON；已启用浏览器登录引导"
        return "未选择 Cookie JSON；将尝试从本机浏览器读取 Cookie"

    def _prepare_wizard_resume(self, output_dir: Path, input_path: str, current_dois: set[str]) -> str:
        if self.resume_from_var.get().strip():
            return "已使用当前填写的历史结果目录"
        candidates = find_resume_candidates(
            output_dir,
            input_path=Path(input_path) if input_path else None,
            current_dois=current_dois,
        )
        if not candidates:
            return "未发现可用历史结果目录"
        best = candidates[0]
        if best.input_match or best.overlap_ratio >= 0.5:
            self.resume_from_var.set(best.path)
            return best.reason
        return f"发现历史结果但相似度不足，未自动启用: {best.path}"

    def _expected_output_dir_text(self, output_root: Path) -> str:
        filename = self.filename_var.get().strip()
        if filename:
            return str(output_root / filename)
        return str(output_root / "doi_batch_时间戳")

    def run_beginner_preflight(self) -> None:
        if self.process is not None:
            messagebox.showinfo("正在运行", "当前任务还没有结束。")
            return
        if self.workflow_var.get() in {"legal_oa", "paper_batch"}:
            messagebox.showinfo(
                "新手预检",
                "新手预检仅用于 ScienceDirect DOI 批量下载。统一批次请直接使用 start / resume / zotero。",
            )
            return
        if self.mode_var.get() != "doi_batch":
            self.mode_var.set("doi_batch")
        if not SD_SKILL_SCRIPT.exists():
            messagebox.showerror("文件缺失", "找不到必要脚本：sd_institutional_skill.py")
            return
        input_path = self.input_file_var.get().strip()
        pasted_text = self._get_pasted_text()
        if not input_path and not pasted_text:
            messagebox.showerror("新手预检", "请先选择 DOI 表格，或粘贴 DOI、题名或推荐文献列表。")
            return
        if input_path and not Path(input_path).exists():
            messagebox.showerror("新手预检", f"输入文件不存在：\n{input_path}")
            return
        output_dir = Path(self.output_var.get().strip() or APP_DIR / "results")
        output_ok, output_message = self._check_output_dir_for_wizard(output_dir)
        if not output_ok:
            messagebox.showerror("新手预检", output_message)
            return
        self.auto_retry_after_run = False
        cmd = self._build_beginner_preflight_command(materialize_paste=True)
        self._launch_command(cmd)

    def run_scraper(self, auto_retry_input: bool = False) -> None:
        if self.process is not None:
            messagebox.showinfo("正在运行", "当前任务还没有结束。")
            return
        if not self._validate_inputs():
            return

        self.auto_retry_after_run = bool(
            auto_retry_input and self.workflow_var.get() == "sciencedirect" and self.mode_var.get() == "doi_batch"
        )
        cmd = self._build_command(materialize_paste=True, auto_retry_input=self.auto_retry_after_run)
        self._launch_command(cmd)

    def _launch_command(self, cmd: list[str]) -> None:
        self.command_var.set(self._format_command(cmd))
        self._refresh_task_summary()
        self._reset_result_summary()
        output_dir = self.output_var.get().strip()
        if output_dir:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
        self.clear_log()
        self._log("启动任务：")
        self._log(self._format_command(cmd))
        self._log("")

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["PYTHONUNBUFFERED"] = "1"

        try:
            self.process = subprocess.Popen(
                cmd,
                cwd=str(APP_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                bufsize=1,
            )
        except Exception as exc:
            self.process = None
            messagebox.showerror("启动失败", str(exc))
            return

        self.started_at = time.time()
        self.smart_run_button.configure(state="disabled")
        self.run_button.configure(state="disabled")
        if hasattr(self, "beginner_preflight_button"):
            self.beginner_preflight_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.continue_button.configure(state="normal")
        self.status_var.set("运行中")
        self.notebook.select(self.run_tab)

        threading.Thread(target=self._read_process_output, daemon=True).start()

    def _read_process_output(self) -> None:
        assert self.process is not None
        assert self.process.stdout is not None

        for line in self.process.stdout:
            self.log_queue.put(line)

        return_code = self.process.wait()
        elapsed = ""
        if self.started_at is not None:
            elapsed = f"，耗时 {time.time() - self.started_at:.1f} 秒"
        self.log_queue.put(f"\n任务结束，退出码 {return_code}{elapsed}\n")
        self.log_queue.put("__PROCESS_DONE__")

    def _drain_log_queue(self) -> None:
        try:
            drained = 0
            while drained < LOG_DRAIN_LIMIT:
                item = self.log_queue.get_nowait()
                drained += 1
                if item == "__PROCESS_DONE__":
                    self.process = None
                    self.smart_run_button.configure(state="normal")
                    self.run_button.configure(state="normal")
                    if hasattr(self, "beginner_preflight_button"):
                        self.beginner_preflight_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self.continue_button.configure(state="disabled")
                    self.status_var.set("已结束")
                    self._refresh_result_summary()
                    self._handle_auto_retry_after_completion()
                else:
                    line = item.rstrip("\n")
                    self._capture_report_paths(line)
                    self._log(line)
        except queue.Empty:
            pass
        self._poll_run_events_once()
        self.root.after(100, self._drain_log_queue)

    def _reset_result_summary(self) -> None:
        self.last_run_output_dir = None
        self.last_failed_report_path = None
        self.last_pdf_report_path = None
        self.last_summary_path = None
        self.last_summary_json_path = None
        self.last_events_path = None
        self.last_retry_input_path = None
        self.last_student_handoff_dir = None
        self.last_paper_index_path = None
        self.last_failure_next_steps_path = None
        self.last_preflight_merged_input_path = None
        self.last_event_count = 0
        self.result_summary_var.set("任务运行中，结束后会在这里显示报告摘要。")
        self.progress_var.set("进度：运行中")
        self.current_task_var.set("当前任务：等待结构化事件")
        self.progress_counts_var.set("计数：无")
        self._load_failure_table()
        self._update_result_buttons()

    def _capture_report_paths(self, line: str) -> None:
        if line.startswith("运行目录：") or line.startswith("运行目录:"):
            run_dir = self._extract_colon_path_from_log(line)
            if run_dir is not None:
                self.last_run_output_dir = run_dir
                self.batch_run_dir_var.set(str(run_dir))
        elif line.startswith("最终 PDF 目录：") or line.startswith("最终 PDF 目录:"):
            pdf_dir = self._extract_colon_path_from_log(line)
            if pdf_dir is not None and self.last_run_output_dir is None:
                self.last_run_output_dir = pdf_dir.parent
        elif "结构化事件 ->" in line:
            self.last_events_path = self._extract_report_path_from_log(line)
            self.last_event_count = 0
            if self.last_events_path:
                self.last_run_output_dir = self.last_events_path.parent
        elif "DOI 失败报告已保存 ->" in line:
            self.last_failed_report_path = self._extract_report_path_from_log(line)
        elif "PDF 下载明细已保存 ->" in line:
            self.last_pdf_report_path = self._extract_report_path_from_log(line)
        elif "PDF 明细:" in line or "PDF report:" in line:
            self.last_pdf_report_path = self._extract_colon_path_from_log(line)
        elif "任务摘要已保存 ->" in line:
            self.last_summary_path = self._extract_report_path_from_log(line)
            if self.last_summary_path:
                self.last_run_output_dir = self.last_summary_path.parent
        elif "任务摘要:" in line or "Run summary:" in line:
            self.last_summary_path = self._extract_colon_path_from_log(line)
            if self.last_summary_path:
                self.last_run_output_dir = self.last_summary_path.parent
        elif "JSON 摘要已保存 ->" in line:
            self.last_summary_json_path = self._extract_report_path_from_log(line)
            if self.last_summary_json_path:
                self.last_run_output_dir = self.last_summary_json_path.parent
        elif "JSON 摘要:" in line or "Run summary JSON:" in line:
            self.last_summary_json_path = self._extract_colon_path_from_log(line)
            if self.last_summary_json_path:
                self.last_run_output_dir = self.last_summary_json_path.parent
        elif "DOI failure report:" in line:
            self.last_failed_report_path = self._extract_colon_path_from_log(line)
        elif "重试输入已保存 ->" in line:
            self.last_retry_input_path = self._extract_report_path_from_log(line)
        elif "研究生查看入口 ->" in line or "研究生查看入口:" in line:
            self.last_student_handoff_dir = self._extract_report_path_from_log(line) or self._extract_colon_path_from_log(line)
        elif "Manifest CSV:" in line:
            manifest_path = self._extract_colon_path_from_log(line)
            if manifest_path:
                self.last_run_output_dir = manifest_path.parents[1] if len(manifest_path.parents) > 1 else manifest_path.parent

    @staticmethod
    def _extract_report_path_from_log(line: str) -> Path | None:
        if "->" not in line:
            return None
        path_text = line.split("->", 1)[1].strip()
        for marker in ("  （", " （", "\t"):
            path_text = path_text.split(marker, 1)[0].strip()
        if not path_text:
            return None
        return Path(path_text.strip('"'))

    @staticmethod
    def _extract_colon_path_from_log(line: str) -> Path | None:
        text = str(line or "").strip()
        # Prefer Chinese fullwidth colon so Windows drive letters (C:\) stay intact.
        if "：" in text:
            path_text = text.split("：", 1)[1].strip()
        elif ": " in text:
            path_text = text.split(": ", 1)[1].strip()
        elif ":" in text:
            # Fallback: drop only the label before the first colon when the rest
            # still looks like a Windows absolute path (e.g. "label:C:\path").
            label, remainder = text.split(":", 1)
            remainder = remainder.strip()
            if re.match(r"^[A-Za-z]:[\\/]", remainder):
                path_text = remainder
            elif re.match(r"^[A-Za-z]$", label.strip()) and remainder.startswith(("\\", "/")):
                path_text = f"{label.strip()}:{remainder}"
            else:
                path_text = remainder
        else:
            return None
        path_text = path_text.strip().strip('"')
        if not path_text:
            return None
        return Path(path_text)

    def _refresh_result_summary(self) -> None:
        if not self.last_run_output_dir and self.last_summary_path:
            self.last_run_output_dir = self.last_summary_path.parent

        if self.last_summary_json_path and self.last_summary_json_path.exists():
            self._refresh_result_summary_from_json(self.last_summary_json_path)
            self._load_failure_table()
            self._update_result_buttons()
            return

        if not self.last_summary_path or not self.last_summary_path.exists():
            if self.workflow_var.get() == "legal_oa" and self.last_run_output_dir:
                self.result_summary_var.set(
                    f"OA 资源辅助获取任务已结束；请查看输出目录中的 metadata\\manifest.csv 和 failed\\duplicates.csv：{self.last_run_output_dir}"
                )
                self._update_result_buttons()
                return
            if self.workflow_var.get() == "paper_batch" and self.last_run_output_dir:
                run_dir = self.last_run_output_dir
                self.result_summary_var.set(
                    "统一批次已结束。"
                    f"运行目录：{run_dir}；"
                    f"PDF：{run_dir / 'pdfs'}；"
                    f"报告：{run_dir / 'reports'}；"
                    f"人工重试：{run_dir / 'working' / 'manual_retry.csv'}；"
                    f"Zotero 回退：{run_dir / 'working' / 'zotero_fallback.csv'}。"
                    "默认已自动排队 Zotero；若需确认或继续，将运行目录填入「已有批次目录」后执行 zotero。"
                )
                self._update_result_buttons()
                return
            self.result_summary_var.set("任务已结束，但没有捕获到 run_summary.txt。请查看运行日志确认输出位置。")
            self._update_result_buttons()
            return

        values, failure_reasons = self._read_run_summary(self.last_summary_path)
        parts = [
            f"识别 DOI: {values.get('识别 DOI 数', '未知')}",
            f"成功解析: {values.get('成功解析数', '未知')}",
            f"解析失败: {values.get('解析失败数', '未知')}",
            f"PDF 成功: {values.get('PDF 成功', '未知')}",
            f"PDF 失败: {values.get('PDF 失败', '未知')}",
            f"PDF 跳过: {values.get('PDF 跳过', '未知')}",
        ]
        if self._should_show_supplement_summary_from_values(values):
            parts.extend([
                f"补充材料成功: {values.get('补充材料成功', '0')}",
                f"补充材料失败: {values.get('补充材料失败', '0')}",
                f"补充材料跳过: {values.get('补充材料跳过', '0')}",
                f"补充材料未发现: {values.get('补充材料未发现', '0')}",
            ])
        if failure_reasons:
            parts.append("主要失败原因: " + "；".join(failure_reasons[:5]))
        self.result_summary_var.set("；".join(parts))
        self._load_failure_table()
        self._update_result_buttons()

    def _refresh_result_summary_from_json(self, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        self.last_run_output_dir = Path(data.get("output_dir") or path.parent)
        if data.get("failed_path") and not self.last_failed_report_path:
            self.last_failed_report_path = Path(str(data["failed_path"]))
        if data.get("pdf_report_path") and not self.last_pdf_report_path:
            self.last_pdf_report_path = Path(str(data["pdf_report_path"]))
        if data.get("event_path") and not self.last_events_path:
            self.last_events_path = Path(str(data["event_path"]))
        if data.get("paper_index_path"):
            self.last_paper_index_path = Path(str(data["paper_index_path"]))
            self.last_student_handoff_dir = self.last_paper_index_path.parent
        if data.get("student_readme_path") and not self.last_student_handoff_dir:
            self.last_student_handoff_dir = Path(str(data["student_readme_path"])).parent
        if data.get("failure_next_steps_path"):
            self.last_failure_next_steps_path = Path(str(data["failure_next_steps_path"]))
        input_path = str(data.get("input_path") or "")
        if input_path and Path(input_path).name.lower() == "merged_doi_input.csv":
            self.last_preflight_merged_input_path = Path(input_path)
        reasons = data.get("failure_reasons") or {}
        reason_text = []
        if isinstance(reasons, dict):
            reason_text = [
                f"{reason}: {count}"
                for reason, count in sorted(reasons.items(), key=lambda item: (-int(item[1]), str(item[0])))[:5]
            ]
        parts = [
            f"识别 DOI: {data.get('total_doi', '未知')}",
            f"成功解析: {data.get('resolved_count', '未知')}",
            f"解析失败: {data.get('resolve_failed_count', '未知')}",
            f"PDF 成功: {data.get('pdf_success', '未知')}",
            f"PDF 失败: {data.get('pdf_failed', '未知')}",
            f"PDF 跳过: {data.get('pdf_skipped', '未知')}",
        ]
        if self._should_show_supplement_summary_from_json(data):
            parts.extend([
                f"补充材料成功: {data.get('supplement_success', 0)}",
                f"补充材料失败: {data.get('supplement_failed', 0)}",
                f"补充材料跳过: {data.get('supplement_skipped', 0)}",
                f"补充材料未发现: {data.get('supplement_not_found', 0)}",
            ])
        if data.get("retry_input_path"):
            self.last_retry_input_path = Path(str(data["retry_input_path"]))
            parts.append(
                "已生成重试输入: {count} 条，排除 {excluded} 条".format(
                    count=data.get("retry_input_count", 0),
                    excluded=data.get("retry_input_excluded_count", 0),
                )
            )
        student_handoff_dir = getattr(self, "last_student_handoff_dir", None)
        preflight_merged_input = getattr(self, "last_preflight_merged_input_path", None)
        if student_handoff_dir:
            parts.append(f"研究生入口: {student_handoff_dir}")
        if preflight_merged_input and preflight_merged_input.exists():
            parts.append("可使用预检合并表进入正式下载")
        if reason_text:
            parts.append("主要失败原因: " + "；".join(reason_text))
        self.result_summary_var.set("；".join(parts))

    @staticmethod
    def _read_run_summary(path: Path) -> tuple[dict[str, str], list[str]]:
        values: dict[str, str] = {}
        failure_reasons: list[str] = []
        section = ""
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line == "解析失败原因:":
                section = "failures"
                continue
            if line == "PDF 下载:":
                section = "pdf"
                continue
            if line == "补充材料下载:":
                section = "supplements"
                continue
            if line == "输出文件:":
                section = "outputs"
                continue
            for prefix in ("识别 DOI 数", "成功解析数", "解析失败数"):
                if line.startswith(prefix + ":"):
                    values[prefix] = line.split(":", 1)[1].strip()
            if section == "failures" and line.startswith("- ") and line != "- 无":
                failure_reasons.append(line[2:])
            elif section == "pdf" and line.startswith("- "):
                label, _, value = line[2:].partition(":")
                label_map = {"成功": "PDF 成功", "失败": "PDF 失败", "跳过": "PDF 跳过"}
                if label.strip() in label_map:
                    values[label_map[label.strip()]] = value.strip()
            elif section == "supplements" and line.startswith("- "):
                label, _, value = line[2:].partition(":")
                label_map = {
                    "成功": "补充材料成功",
                    "失败": "补充材料失败",
                    "跳过": "补充材料跳过",
                    "未发现": "补充材料未发现",
                }
                if label.strip() in label_map:
                    values[label_map[label.strip()]] = value.strip()
            elif section == "outputs" and line.startswith("- "):
                label, _, value = line[2:].partition(":")
                if label.strip() in {"Supplement 下载报告", "补充材料下载报告"}:
                    values["Supplement 下载报告"] = value.strip()
        return values, failure_reasons

    @classmethod
    def _should_show_supplement_summary_from_json(cls, data: dict) -> bool:
        if data.get("supplement_report_path"):
            return True
        if cls._truthy_summary_value(data.get("supplement_requested")):
            return True
        if cls._truthy_summary_value(data.get("supplements_requested")):
            return True
        if cls._truthy_summary_value(data.get("download_supplements")):
            return True
        return any(
            cls._summary_count(data.get(key)) > 0
            for key in (
                "supplement_success",
                "supplement_failed",
                "supplement_skipped",
                "supplement_not_found",
            )
        )

    @classmethod
    def _should_show_supplement_summary_from_values(cls, values: dict[str, str]) -> bool:
        report_path = values.get("Supplement 下载报告", "").strip()
        if report_path and report_path not in {"未生成", "无", "None", "none"}:
            return True
        return any(
            cls._summary_count(values.get(key)) > 0
            for key in (
                "补充材料成功",
                "补充材料失败",
                "补充材料跳过",
                "补充材料未发现",
            )
        )

    @staticmethod
    def _summary_count(value: object) -> int:
        try:
            return int(str(value or "0").strip())
        except ValueError:
            return 0

    @staticmethod
    def _truthy_summary_value(value: object) -> bool:
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "是"}

    def _update_result_buttons(self) -> None:
        if not hasattr(self, "retry_failed_button"):
            return
        button_paths = (
            (self.open_run_output_button, self.last_run_output_dir),
            (self.open_failed_report_button, self.last_failed_report_path),
            (self.open_pdf_report_button, self.last_pdf_report_path),
            (self.open_summary_button, self.last_summary_path),
        )
        for button, path in button_paths:
            button.configure(state="normal" if path and Path(path).exists() else "disabled")
        has_retry_source = any(
            path and Path(path).exists()
            for path in (self.last_pdf_report_path, self.last_failed_report_path)
        )
        self.retry_failed_button.configure(state="normal" if has_retry_source else "disabled")
        if hasattr(self, "retry_selected_button"):
            has_selection = bool(getattr(self, "failure_tree", None) and self.failure_tree.get_children())
            self.retry_selected_button.configure(state="normal" if has_retry_source and has_selection else "disabled")
        if hasattr(self, "open_student_handoff_button"):
            self.open_student_handoff_button.configure(
                state="normal"
                if self.last_student_handoff_dir and self.last_student_handoff_dir.exists()
                else "disabled"
            )
        if hasattr(self, "open_failure_next_steps_button"):
            self.open_failure_next_steps_button.configure(
                state="normal"
                if self.last_failure_next_steps_path and self.last_failure_next_steps_path.exists()
                else "disabled"
            )
        if hasattr(self, "use_preflight_input_button"):
            self.use_preflight_input_button.configure(
                state="normal"
                if self.last_preflight_merged_input_path and self.last_preflight_merged_input_path.exists()
                else "disabled"
            )

    def _poll_run_events_once(self) -> None:
        if not self.last_events_path or not self.last_events_path.exists():
            return
        try:
            events = read_run_events(self.last_events_path)
        except Exception as exc:
            self.current_task_var.set(f"当前任务：读取结构化事件失败：{exc}")
            return
        for event in events[self.last_event_count:]:
            self._apply_run_event(event)
        self.last_event_count = len(events)

    def _apply_run_event(self, event: dict[str, object]) -> None:
        stage = str(event.get("stage") or "")
        status = str(event.get("status") or "")
        doi = str(event.get("doi") or "")
        title = str(event.get("title") or "")
        reason = str(event.get("reason") or "")
        counts = event.get("counts") if isinstance(event.get("counts"), dict) else {}
        stage_label = {"resolve": "解析", "pdf": "PDF", "resume": "断点恢复"}.get(stage, stage or "任务")
        status_label = {
            "start": "开始",
            "running": "进行中",
            "success": "成功",
            "failed": "失败",
            "skipped": "跳过",
            "blocked": "等待/受阻",
            "complete": "完成",
            "loaded": "已读取",
        }.get(status, status or "更新")
        subject = title or doi or reason or "(无标题)"
        self.current_task_var.set(f"当前任务：{stage_label} {status_label} - {subject}")
        if counts:
            pieces = [f"{key}={value}" for key, value in counts.items()]
            self.progress_counts_var.set("计数：" + "；".join(pieces))
            current = counts.get("current")
            total = counts.get("total") or counts.get("pdf_total")
            if current and total:
                self.progress_var.set(f"进度：{stage_label} {current}/{total}")
            elif status == "complete":
                self.progress_var.set(f"进度：{stage_label}完成")

    def _load_failure_table(self) -> None:
        if not hasattr(self, "failure_tree"):
            return
        for item_id in self.failure_tree.get_children():
            self.failure_tree.delete(item_id)
        filter_value = self.failure_filter_var.get()
        rows = collect_failure_table_rows(self.last_pdf_report_path, self.last_failed_report_path)
        for row in rows:
            if filter_value != "全部" and row["kind"] != filter_value:
                continue
            self.failure_tree.insert(
                "",
                "end",
                values=(row["kind"], row["doi"], row["title"], row["reason"]),
            )

    def _selected_failure_dois(self) -> set[str]:
        if not hasattr(self, "failure_tree"):
            return set()
        selected: set[str] = set()
        for item_id in self.failure_tree.selection():
            values = self.failure_tree.item(item_id, "values")
            if len(values) >= 2 and values[1]:
                selected.add(str(values[1]))
        return selected

    def _handle_auto_retry_after_completion(self) -> None:
        if not self.auto_retry_after_run:
            return
        self.auto_retry_after_run = False

        retry_path = self.last_retry_input_path if self.last_retry_input_path and self.last_retry_input_path.exists() else None
        retry_count = self._count_retry_csv_rows(retry_path) if retry_path else 0
        excluded_count = 0
        if not retry_path:
            output_dir = self.last_run_output_dir or Path(self.output_var.get().strip() or APP_DIR / "results")
            result = write_retry_input_from_reports(
                self.last_pdf_report_path,
                self.last_failed_report_path,
                output_dir,
            )
            excluded_count = result.excluded_count
            if result.path:
                retry_path = Path(result.path)
                retry_count = result.row_count
                self.last_retry_input_path = retry_path

        if not retry_path:
            if excluded_count:
                self._append_result_summary(f"未生成重试输入；不可重试/已排除 {excluded_count} 条")
            return

        self.input_file_var.set(str(retry_path))
        self.preview_status_var.set(f"已自动生成重试输入 {retry_count} 条，建议点击预览解析")
        self.notebook.select(self.doi_tab)
        message = f"已生成重试输入: {retry_count} 条"
        if excluded_count:
            message += f"，排除 {excluded_count} 条"
        self._append_result_summary(message)

    @staticmethod
    def _count_retry_csv_rows(path: Path | None) -> int:
        if not path or not path.exists():
            return 0
        with path.open("r", newline="", encoding="utf-8-sig") as f:
            return sum(1 for _row in csv.DictReader(f))

    def _append_result_summary(self, text: str) -> None:
        current = self.result_summary_var.get().strip()
        self.result_summary_var.set((current + "；" if current else "") + text)

    def stop_scraper(self) -> None:
        if self.process is None:
            return
        if not messagebox.askyesno("确认停止", "确定要停止当前检索任务吗？已生成的结果文件不会被删除。"):
            return
        self.process.terminate()
        self._log("\n已请求停止任务。")

    def send_enter(self) -> None:
        if self.process is None or self.process.stdin is None:
            return
        try:
            self.process.stdin.write("\n")
            self.process.stdin.flush()
            self._log("\n已发送 Enter，继续执行。")
        except Exception as exc:
            messagebox.showerror("发送失败", str(exc))

    def open_output_dir(self) -> None:
        path = Path(self.output_var.get().strip() or APP_DIR)
        path.mkdir(parents=True, exist_ok=True)
        self._open_path(path)

    def open_last_output_dir(self) -> None:
        path = self.last_run_output_dir or (self.last_summary_path.parent if self.last_summary_path else None)
        if not path:
            messagebox.showinfo("打开输出目录", "尚未捕获到本次任务输出目录。")
            return
        self._open_path(path)

    def open_failed_report(self) -> None:
        self._open_report_path(self.last_failed_report_path, "失败 DOI 表")

    def open_pdf_report(self) -> None:
        self._open_report_path(self.last_pdf_report_path, "PDF 下载报告")

    def open_run_summary(self) -> None:
        self._open_report_path(self.last_summary_path, "任务摘要")

    def open_student_handoff(self) -> None:
        path = self.last_student_handoff_dir
        if not path or not path.exists():
            messagebox.showinfo("研究生查看入口", "尚未找到研究生查看入口。")
            return
        self._open_path(path)

    def open_failure_next_steps(self) -> None:
        self._open_report_path(self.last_failure_next_steps_path, "失败下一步表")

    def use_preflight_merged_input(self) -> None:
        path = self.last_preflight_merged_input_path
        if not path or not path.exists():
            messagebox.showinfo("使用预检合并表", "尚未找到预检生成的 merged_doi_input.csv。")
            return
        self.input_file_var.set(str(path))
        self.doi_column_var.set("doi")
        self.preview_status_var.set("已填入预检合并表，建议点击预览解析后再正式下载")
        self.notebook.select(self.doi_tab)
        self._refresh_command_preview()
        self._refresh_task_summary()

    def _open_report_path(self, path: Path | None, label: str) -> None:
        if not path or not path.exists():
            messagebox.showinfo(label, f"尚未找到{label}。")
            return
        self._open_path(path)

    @staticmethod
    def _open_path(path: Path) -> None:
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc))

    def create_retry_input_from_reports(self, selected_only: bool = False) -> None:
        selected_dois = self._selected_failure_dois() if selected_only else None
        if selected_only and not selected_dois:
            messagebox.showinfo("生成重试输入", "请先在失败项表格中选择至少一条 DOI。")
            return
        rows = collect_retry_input_rows(
            self.last_pdf_report_path,
            self.last_failed_report_path,
            selected_dois=selected_dois,
        )
        if not rows:
            messagebox.showinfo("生成重试输入", "当前报告中没有可重试的失败 DOI。")
            return
        output_dir = self.last_run_output_dir or Path(self.output_var.get().strip() or APP_DIR / "results")
        try:
            retry_path = write_retry_input_csv(rows, output_dir)
        except Exception as exc:
            messagebox.showerror("生成重试输入失败", str(exc))
            return
        self.input_file_var.set(str(retry_path))
        self.preview_status_var.set(f"已生成重试输入 {len(rows)} 条，建议点击预览解析")
        self.notebook.select(self.doi_tab)
        self._refresh_task_summary()
        messagebox.showinfo("生成重试输入", f"已生成重试 DOI 输入表：\n{retry_path}")

    def clear_log(self) -> None:
        self.log_text.delete("1.0", "end")

    def _log(self, text: str) -> None:
        self.log_text.insert("end", text + "\n")
        end_line = int(self.log_text.index("end-1c").split(".")[0])
        if end_line > LOG_MAX_LINES:
            self.log_text.delete("1.0", f"{end_line - LOG_MAX_LINES}.0")
        self.log_text.see("end")


def main() -> None:
    if not SD_SCRIPT.exists():
        messagebox.showerror("文件缺失", "找不到必要脚本：sd_scraper.py")
        return

    root = Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    PaperScraperUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
