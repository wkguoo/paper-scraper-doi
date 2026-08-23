# -*- coding: utf-8 -*-
"""Windows-friendly Tkinter UI for the ScienceDirect paper scraper."""

from __future__ import annotations

import os
import queue
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from tkinter import StringVar, Text, Tk, filedialog, messagebox
from tkinter import ttk

from doi_batch_utils import (
    collect_failure_table_rows,
    read_run_events,
)
from windows_paths import chrome_bin

APP_DIR = Path(__file__).resolve().parent
BATCH_SCRIPT = APP_DIR / "paper_batch.py"
SETTINGS_FILE = APP_DIR / "results" / "_ui_settings.json"
BATCH_ACTIONS = ("start", "resume", "zotero")
LOG_DRAIN_LIMIT = 200
LOG_MAX_LINES = 5000


class PaperScraperUI:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("Paper Download UI · 推荐：统一批次")
        self.settings = self._load_settings_data()
        self.root.geometry(self.settings.get("geometry") or "1180x800")
        self.root.minsize(980, 680)

        self.process: subprocess.Popen[str] | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.started_at: float | None = None

        self.output_var = StringVar(value=self.settings.get("output_dir") or str(APP_DIR / "results"))
        self.batch_action_var = StringVar(value=self.settings.get("batch_action") or "start")
        self.batch_input_file_var = StringVar(value=self.settings.get("batch_input_file") or "")
        self.batch_run_dir_var = StringVar(value=self.settings.get("batch_run_dir") or "")
        self.batch_run_name_var = StringVar(value="")
        self.batch_login_wait_var = StringVar(value=str(self.settings.get("batch_login_wait") or "0"))
        self.batch_library_id_var = StringVar(value=str(self.settings.get("batch_library_id") or "1"))
        self.batch_wait_seconds_var = StringVar(value=str(self.settings.get("batch_wait_seconds") or "0"))

        self.status_var = StringVar(value="就绪")
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
        self.last_student_handoff_dir: Path | None = None
        self.last_paper_index_path: Path | None = None
        self.last_failure_next_steps_path: Path | None = None
        self.last_event_count = 0

        self._build_ui()
        self._bind_updates()
        self._refresh_command_preview()
        self._refresh_task_summary()
        self._drain_log_queue()
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
                "geometry": geometry,
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
            text="统一入口：paper_batch start（OA → 机构授权 → Zotero 回退）",
            style="Step.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.notebook = ttk.Notebook(root_frame)
        self.notebook.grid(row=2, column=0, sticky="nsew", pady=(10, 8))

        self.batch_tab = ttk.Frame(self.notebook, padding=10)
        self.run_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.batch_tab, text="统一批次（推荐）")
        self.notebook.add(self.run_tab, text="运行日志")

        self._build_batch_tab(self.batch_tab)
        self._build_run_tab(self.run_tab)
        try:
            active_tab = int(self.settings.get("active_tab", 0))
            self.notebook.select(active_tab if active_tab in (0, 1) else 0)
        except Exception:
            self.notebook.select(self.batch_tab)

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

        right = ttk.LabelFrame(body, text="2 输出与运行", padding=10)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        ttk.Label(right, text="输出根目录（start）").grid(row=0, column=0, sticky="w")
        ttk.Entry(right, textvariable=self.output_var).grid(row=1, column=0, sticky="ew", pady=(2, 8))
        ttk.Button(right, text="选择输出目录", command=self.choose_output_dir).grid(row=2, column=0, sticky="ew", pady=(0, 8))

        ttk.Label(right, text="可选批次名称（run-name）").grid(row=3, column=0, sticky="w")
        ttk.Entry(right, textvariable=self.batch_run_name_var).grid(row=4, column=0, sticky="ew", pady=(2, 8))

        ttk.Label(right, text="登录等待秒数（start，可选）").grid(row=5, column=0, sticky="w")
        ttk.Entry(right, textvariable=self.batch_login_wait_var, width=12).grid(row=6, column=0, sticky="w", pady=(2, 8))

        ttk.Label(right, text="Zotero library-id（start 自动桥接 / zotero）").grid(row=7, column=0, sticky="w")
        ttk.Entry(right, textvariable=self.batch_library_id_var, width=12).grid(row=8, column=0, sticky="w", pady=(2, 8))

        ttk.Label(right, text="等待 Zotero 结果秒数（start/zotero，0=只排队）").grid(row=9, column=0, sticky="w")
        ttk.Entry(right, textvariable=self.batch_wait_seconds_var, width=12).grid(row=10, column=0, sticky="w", pady=(2, 8))

        ttk.Label(
            right,
            text=(
                "start：OA + 机构，失败默认进 Zotero 并自动排队桥接；"
                "resume：兼容旧批次的一次人工重试；"
                "zotero：确认后重跑或手动排队桥接。"
            ),
            foreground="#555555",
            wraplength=420,
        ).grid(row=11, column=0, sticky="ew", pady=(8, 0))

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
        self.open_summary_button.grid(row=1, column=3, sticky="ew", pady=(8, 0))
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

    def _bind_updates(self) -> None:
        for var in (
            self.output_var,
            self.batch_action_var,
            self.batch_input_file_var,
            self.batch_run_dir_var,
            self.batch_run_name_var,
            self.batch_login_wait_var,
            self.batch_library_id_var,
            self.batch_wait_seconds_var,
        ):
            var.trace_add("write", self._on_parameter_changed)

    def _on_parameter_changed(self, *_args: object) -> None:
        self._refresh_command_preview()
        self._refresh_task_summary()
        self._save_settings()

    def _on_batch_text_changed(self, *_args: object) -> None:
        self.root.after_idle(self._on_parameter_changed)

    def _refresh_task_summary(self) -> None:
        action = self.batch_action_var.get().strip() or "start"
        output_dir = self.output_var.get().strip() or "(默认 results)"
        run_dir = self.batch_run_dir_var.get().strip() or "未选择"
        if action == "start":
            source = self.batch_input_file_var.get().strip() or ("粘贴内容" if self._get_batch_text() else "未选择")
            library_id = self.batch_library_id_var.get().strip() or "1"
            wait_seconds = self.batch_wait_seconds_var.get().strip() or "0"
            summary = (
                f"统一批次 start：输入={source}；输出根目录={output_dir}；"
                f"流程=OA→机构→失败自动 Zotero；library-id={library_id}；wait-seconds={wait_seconds}。"
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

    def _get_preflight_items(self) -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = [("warn", warning) for warning in self.startup_warnings]
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

    def _validate_inputs(self) -> bool:
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

    def _build_command(self, materialize_paste: bool = False) -> list[str]:
        return self._build_paper_batch_command(materialize_paste=materialize_paste)

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

    def _get_batch_text(self) -> str:
        if not hasattr(self, "batch_text"):
            return ""
        return self.batch_text.get("1.0", "end").strip()

    def clear_batch_text(self) -> None:
        if hasattr(self, "batch_text"):
            self.batch_text.delete("1.0", "end")
        self._refresh_command_preview()
        self._refresh_task_summary()
    def run_scraper(self) -> None:
        if self.process is not None:
            messagebox.showinfo("正在运行", "当前任务还没有结束。")
            return
        if not self._validate_inputs():
            return
        self._launch_command(self._build_command(materialize_paste=True))

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
        self._poll_run_events_once()
        self.root.after(100, self._drain_log_queue)

    def _reset_result_summary(self) -> None:
        self.last_run_output_dir = None
        self.last_failed_report_path = None
        self.last_pdf_report_path = None
        self.last_summary_path = None
        self.last_summary_json_path = None
        self.last_events_path = None
        self.last_student_handoff_dir = None
        self.last_paper_index_path = None
        self.last_failure_next_steps_path = None
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
            if self.last_run_output_dir:
                run_dir = self.last_run_output_dir
                self.result_summary_var.set(
                    "统一批次已结束。"
                    f"运行目录：{run_dir}；"
                    f"交付目录：{run_dir / '结果'}；"
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
            parts.append(
                "已生成重试输入: {count} 条，排除 {excluded} 条".format(
                    count=data.get("retry_input_count", 0),
                    excluded=data.get("retry_input_excluded_count", 0),
                )
            )
        student_handoff_dir = getattr(self, "last_student_handoff_dir", None)
        if student_handoff_dir:
            parts.append(f"研究生入口: {student_handoff_dir}")
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
        button_paths = (
            (self.open_run_output_button, self.last_run_output_dir),
            (self.open_failed_report_button, self.last_failed_report_path),
            (self.open_pdf_report_button, self.last_pdf_report_path),
            (self.open_summary_button, self.last_summary_path),
        )
        for button, path in button_paths:
            button.configure(state="normal" if path and Path(path).exists() else "disabled")
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

    def stop_scraper(self) -> None:
        if self.process is None:
            return
        if not messagebox.askyesno("确认停止", "确定要停止当前任务吗？已生成的结果文件不会被删除。"):
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

    def clear_log(self) -> None:
        self.log_text.delete("1.0", "end")

    def _log(self, text: str) -> None:
        self.log_text.insert("end", text + "\n")
        end_line = int(self.log_text.index("end-1c").split(".")[0])
        if end_line > LOG_MAX_LINES:
            self.log_text.delete("1.0", f"{end_line - LOG_MAX_LINES}.0")
        self.log_text.see("end")


def main() -> None:
    if not BATCH_SCRIPT.exists():
        messagebox.showerror("文件缺失", "找不到必要脚本：paper_batch.py")
        return

    root = Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    PaperScraperUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
