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
    collect_retry_input_rows,
    extract_doi_from_text,
    preview_doi_input as preview_doi_data,
    write_retry_input_csv,
)
from windows_paths import chrome_bin

APP_DIR = Path(__file__).resolve().parent
SD_SCRIPT = APP_DIR / "sd_scraper.py"
SETTINGS_FILE = APP_DIR / "results" / "_ui_settings.json"
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
        self.root.title("ScienceDirect Paper Scraper")
        self.settings = self._load_settings_data()
        self.root.geometry(self.settings.get("geometry") or "1180x800")
        self.root.minsize(980, 680)

        self.process: subprocess.Popen[str] | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.preview_queue: queue.Queue[tuple] = queue.Queue()
        self.started_at: float | None = None

        self.mode_var = StringVar(value="doi_batch")
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
        self.cookies_file_var = StringVar(value=self.settings.get("cookies_file") or "")

        self.browser_cookies_var = BooleanVar(value=bool(self.settings.get("browser_cookies", False)))
        self.open_login_var = BooleanVar(value=bool(self.settings.get("open_login", False)))
        self.download_pdf_var = BooleanVar(value=bool(self.settings.get("download_pdf", True)))
        self.open_access_var = BooleanVar(value=False)

        self.status_var = StringVar(value="就绪")
        self.preview_status_var = StringVar(value="未预览")
        self.command_var = StringVar(value="")
        self.summary_var = StringVar(value="")
        self.warning_var = StringVar(value="")
        self.result_summary_var = StringVar(value="任务尚未运行。")
        self.startup_warnings = self._run_startup_checks()
        self.last_run_output_dir: Path | None = None
        self.last_failed_report_path: Path | None = None
        self.last_pdf_report_path: Path | None = None
        self.last_summary_path: Path | None = None
        self.ui_ready = False

        self._build_ui()
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
            warnings.append("未在常见位置检测到 Chrome；PDF 下载可能无法自动打开调试 Chrome。")
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
        ttk.Label(header, text="ScienceDirect 论文抓取集成界面", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="推荐流程：1 数据来源  →  2 权限与输出  →  3 预览检查  →  4 开始运行",
            style="Step.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.notebook = ttk.Notebook(root_frame)
        self.notebook.grid(row=2, column=0, sticky="nsew", pady=(10, 8))

        self.doi_tab = ttk.Frame(self.notebook, padding=10)
        self.search_tab = ttk.Frame(self.notebook, padding=10)
        self.run_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.doi_tab, text="DOI 批量下载")
        self.notebook.add(self.search_tab, text="文献检索")
        self.notebook.add(self.run_tab, text="运行日志")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self._build_doi_tab(self.doi_tab)
        self._build_search_tab(self.search_tab)
        self._build_run_tab(self.run_tab)
        try:
            self.notebook.select(int(self.settings.get("active_tab", 0)))
        except Exception:
            self.notebook.select(self.doi_tab)

        footer = ttk.Frame(root_frame)
        footer.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        footer.columnconfigure(0, weight=1)

        ttk.Label(footer, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        self.run_button = ttk.Button(footer, text="开始运行", command=self.run_scraper, style="Primary.TButton")
        self.run_button.grid(row=0, column=1, padx=(8, 0))
        self.stop_button = ttk.Button(footer, text="停止", command=self.stop_scraper, state="disabled")
        self.stop_button.grid(row=0, column=2, padx=(8, 0))
        self.continue_button = ttk.Button(footer, text="登录完成，继续", command=self.send_enter, state="disabled")
        self.continue_button.grid(row=0, column=3, padx=(8, 0))
        ttk.Button(footer, text="打开输出目录", command=self.open_output_dir).grid(row=0, column=4, padx=(8, 0))
        ttk.Button(footer, text="清空日志", command=self.clear_log).grid(row=0, column=5, padx=(8, 0))

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

    def _build_run_tab(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(5, weight=1)

        ttk.Label(frame, text="4 运行前检查", font=("Microsoft YaHei UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(frame, textvariable=self.summary_var, wraplength=1020).grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(frame, textvariable=self.warning_var, style="Warning.TLabel", wraplength=1020).grid(
            row=2, column=0, sticky="ew", pady=(4, 8)
        )
        command_entry = ttk.Entry(frame, textvariable=self.command_var, state="readonly")
        command_entry.grid(row=3, column=0, sticky="ew", pady=(0, 8))

        result = ttk.LabelFrame(frame, text="结果摘要", padding=10)
        result.grid(row=4, column=0, sticky="ew", pady=(0, 8))
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

        self.log_text = Text(frame, height=18, width=120, wrap="word", font=("Consolas", 10))
        self.log_text.grid(row=5, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.log_text.yview)
        yscroll.grid(row=5, column=1, sticky="ns")
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

        tips = (
            "支持 .xlsx/.xlsm/.csv/.txt/.md/.markdown/.tsv。文件优先；未选择文件时使用粘贴内容。"
        )
        ttk.Label(frame, text=tips, foreground="#555555", wraplength=520).grid(
            row=7, column=0, columnspan=3, sticky="ew", pady=(10, 0)
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

        ttk.Checkbutton(frame, text="检索后下载 PDF", variable=self.download_pdf_var).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(4, 2)
        )

        ttk.Label(frame, text="高级登录方式", foreground="#444444").grid(
            row=7, column=0, columnspan=3, sticky="w", pady=(8, 0)
        )
        ttk.Checkbutton(frame, text="从本机 Chrome 读取 Cookie", variable=self.browser_cookies_var).grid(
            row=8, column=0, columnspan=3, sticky="w", pady=2
        )
        ttk.Checkbutton(frame, text="先弹出 Chrome 手动登录", variable=self.open_login_var).grid(
            row=9, column=0, columnspan=3, sticky="w", pady=2
        )

        if compact:
            text = "推荐：优先选择 Cookie Editor 导出的 cookies.json。PDF 下载依赖机构权限和 Cookie 有效性。"
            wrap = 500
        else:
            text = (
                "推荐：优先选择 Cookie JSON。未提供 Cookie 文件时，可使用本机 Chrome Cookie；"
                "手动登录会等待你在 Chrome 中完成机构登录。"
            )
            wrap = 420
        ttk.Label(frame, text=text, foreground="#555555", wraplength=wrap).grid(
            row=10, column=0, columnspan=3, sticky="ew", pady=(8, 0)
        )

    def _bind_updates(self) -> None:
        for var in (
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
            self.cookies_file_var,
            self.browser_cookies_var,
            self.open_login_var,
            self.download_pdf_var,
            self.open_access_var,
        ):
            var.trace_add("write", self._on_parameter_changed)

    def _on_parameter_changed(self, *_args: object) -> None:
        self._refresh_command_preview()
        self._refresh_task_summary()
        self._save_settings()

    def _on_paste_text_changed(self, *_args: object) -> None:
        self.root.after_idle(self._on_parameter_changed)

    def _on_tab_changed(self, _event: object) -> None:
        selected = self.notebook.select()
        if selected == str(self.doi_tab):
            if self.mode_var.get() != "doi_batch":
                self.mode_var.set("doi_batch")
        elif selected == str(self.search_tab):
            if self.mode_var.get() == "doi_batch":
                self.mode_var.set("keyword")
        self._refresh_task_summary()
        if self.ui_ready:
            self._save_settings()

    def _refresh_task_summary(self) -> None:
        mode = self.mode_var.get()
        output_dir = self.output_var.get().strip() or "(默认 results)"
        cookie_path = self.cookies_file_var.get().strip()
        if cookie_path:
            cookie_source = check_cookie_json(cookie_path).message
        elif self.browser_cookies_var.get():
            cookie_source = "本机 Chrome Cookie"
        elif self.open_login_var.get():
            cookie_source = "手动登录 Chrome"
        else:
            cookie_source = "未选择 Cookie"
        pdf_text = "下载 PDF" if self.download_pdf_var.get() else "仅保存元数据/解析结果"

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
        items: list[tuple[str, str]] = [("warn", warning) for warning in self.startup_warnings]
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

        cookie_path = self.cookies_file_var.get().strip()
        if not self.download_pdf_var.get():
            items.append(("ok", "PDF 下载未开启，仅保存解析结果"))
        elif cookie_path:
            cookie_check = check_cookie_json(cookie_path)
            level = "ok" if cookie_check.is_usable else "warn"
            items.append((level, cookie_check.message))
        elif self.browser_cookies_var.get():
            items.append(("warn", "未选择 Cookie JSON；将尝试从本机 Chrome 读取 Cookie"))
        elif self.open_login_var.get():
            items.append(("warn", "未选择 Cookie JSON；运行时将等待手动登录 Chrome"))
        else:
            items.append(("warn", "下载 PDF 通常需要 Cookie JSON 或已登录的 Chrome"))
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
                "当前开启了 PDF 下载，但没有选择 Cookie JSON，也没有启用 Chrome Cookie/手动登录。\n\n仍要继续运行吗？",
            )
        ):
            return False
        return True

    def _build_command(self, materialize_paste: bool = False) -> list[str]:
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
            self._append_value(cmd, "--cookies", self.cookies_file_var.get())
            if not self.cookies_file_var.get().strip() and self.browser_cookies_var.get() and self.download_pdf_var.get():
                cmd.append("--browser-cookies")
            if self.open_login_var.get():
                cmd.append("--open-browser-login")
            if self.download_pdf_var.get():
                cmd.append("--download-pdfs")
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

    def clear_paste_text(self) -> None:
        self.paste_text.delete("1.0", "end")
        self._clear_preview_rows()
        self.preview_status_var.set("未预览")
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
                    self.preview_button.configure(state="normal")
                elif kind == "error":
                    self.preview_status_var.set("预览失败")
                    self.preview_button.configure(state="normal")
                    messagebox.showerror("预览解析失败", item[1])
        except queue.Empty:
            pass
        self.root.after(150, self._drain_preview_queue)

    def _clear_preview_rows(self) -> None:
        if not hasattr(self, "preview_tree"):
            return
        for item_id in self.preview_tree.get_children():
            self.preview_tree.delete(item_id)

    def run_scraper(self) -> None:
        if self.process is not None:
            messagebox.showinfo("正在运行", "当前任务还没有结束。")
            return
        if not self._validate_inputs():
            return

        cmd = self._build_command(materialize_paste=True)
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
        self.run_button.configure(state="disabled")
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
                    self.run_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self.continue_button.configure(state="disabled")
                    self.status_var.set("已结束")
                    self._refresh_result_summary()
                else:
                    line = item.rstrip("\n")
                    self._capture_report_paths(line)
                    self._log(line)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_log_queue)

    def _reset_result_summary(self) -> None:
        self.last_run_output_dir = None
        self.last_failed_report_path = None
        self.last_pdf_report_path = None
        self.last_summary_path = None
        self.result_summary_var.set("任务运行中，结束后会在这里显示报告摘要。")
        self._update_result_buttons()

    def _capture_report_paths(self, line: str) -> None:
        if "DOI 失败报告已保存 ->" in line:
            self.last_failed_report_path = self._extract_report_path_from_log(line)
        elif "PDF 下载明细已保存 ->" in line:
            self.last_pdf_report_path = self._extract_report_path_from_log(line)
        elif "任务摘要已保存 ->" in line:
            self.last_summary_path = self._extract_report_path_from_log(line)
            if self.last_summary_path:
                self.last_run_output_dir = self.last_summary_path.parent

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

    def _refresh_result_summary(self) -> None:
        if not self.last_run_output_dir and self.last_summary_path:
            self.last_run_output_dir = self.last_summary_path.parent

        if not self.last_summary_path or not self.last_summary_path.exists():
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
        if failure_reasons:
            parts.append("主要失败原因: " + "；".join(failure_reasons[:5]))
        self.result_summary_var.set("；".join(parts))
        self._update_result_buttons()

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
        return values, failure_reasons

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

    def create_retry_input_from_reports(self) -> None:
        rows = collect_retry_input_rows(self.last_pdf_report_path, self.last_failed_report_path)
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
