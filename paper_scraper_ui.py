# -*- coding: utf-8 -*-
"""Windows-friendly Tkinter UI for the ScienceDirect paper scraper."""

from __future__ import annotations

import os
import queue
import csv
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from tkinter import BooleanVar, StringVar, Text, Tk, filedialog, messagebox
from tkinter import ttk


APP_DIR = Path(__file__).resolve().parent
SD_SCRIPT = APP_DIR / "sd_scraper.py"
PREVIEW_LIMIT = 200
LOG_DRAIN_LIMIT = 200
LOG_MAX_LINES = 5000


class PaperScraperUI:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("ScienceDirect Paper Scraper")
        self.root.geometry("1020x720")
        self.root.minsize(920, 650)

        self.process: subprocess.Popen[str] | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.preview_queue: queue.Queue[tuple] = queue.Queue()
        self.started_at: float | None = None

        self.mode_var = StringVar(value="keyword")
        self.query_var = StringVar(value="")
        self.journal_var = StringVar(value="")
        self.author_var = StringVar(value="")
        self.issn_var = StringVar(value="")
        self.date_var = StringVar(value="")
        self.count_var = StringVar(value="50")
        self.sort_var = StringVar(value="relevance")
        self.article_type_var = StringVar(value="")
        self.format_var = StringVar(value="xlsx")
        self.output_var = StringVar(value=str(APP_DIR / "results"))
        self.filename_var = StringVar(value="")
        self.input_file_var = StringVar(value="")
        self.doi_column_var = StringVar(value="")
        self.sheet_var = StringVar(value="")
        self.cookies_file_var = StringVar(value="")

        self.browser_cookies_var = BooleanVar(value=True)
        self.open_login_var = BooleanVar(value=False)
        self.download_pdf_var = BooleanVar(value=False)
        self.open_access_var = BooleanVar(value=False)

        self.status_var = StringVar(value="就绪")
        self.preview_status_var = StringVar(value="未预览")
        self.command_var = StringVar(value="")

        self._build_ui()
        self._bind_updates()
        self._refresh_command_preview()
        self._drain_log_queue()
        self._drain_preview_queue()

    def _build_ui(self) -> None:
        root_frame = ttk.Frame(self.root, padding=12)
        root_frame.pack(fill="both", expand=True)
        root_frame.columnconfigure(0, weight=1)
        root_frame.rowconfigure(2, weight=1)

        title = ttk.Label(root_frame, text="ScienceDirect 论文抓取集成界面", font=("Microsoft YaHei UI", 16, "bold"))
        title.grid(row=0, column=0, sticky="w")

        main = ttk.Frame(root_frame)
        main.grid(row=1, column=0, sticky="ew", pady=(10, 8))
        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)

        left = ttk.LabelFrame(main, text="检索参数", padding=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        right = ttk.LabelFrame(main, text="输出与登录", padding=10)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        self._build_search_fields(left)
        self._build_output_fields(right)

        preview = ttk.LabelFrame(root_frame, text="命令预览与运行日志", padding=8)
        preview.grid(row=2, column=0, sticky="nsew")
        preview.rowconfigure(1, weight=1)
        preview.columnconfigure(0, weight=1)

        command_entry = ttk.Entry(preview, textvariable=self.command_var, state="readonly")
        command_entry.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        self.log_text = Text(preview, height=18, wrap="word", font=("Consolas", 10))
        self.log_text.grid(row=1, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(preview, orient="vertical", command=self.log_text.yview)
        yscroll.grid(row=1, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=yscroll.set)

        footer = ttk.Frame(root_frame)
        footer.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        footer.columnconfigure(0, weight=1)

        ttk.Label(footer, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        self.run_button = ttk.Button(footer, text="开始运行", command=self.run_scraper)
        self.run_button.grid(row=0, column=1, padx=(8, 0))
        self.stop_button = ttk.Button(footer, text="停止", command=self.stop_scraper, state="disabled")
        self.stop_button.grid(row=0, column=2, padx=(8, 0))
        self.continue_button = ttk.Button(footer, text="登录完成，继续", command=self.send_enter, state="disabled")
        self.continue_button.grid(row=0, column=3, padx=(8, 0))
        ttk.Button(footer, text="打开输出目录", command=self.open_output_dir).grid(row=0, column=4, padx=(8, 0))
        ttk.Button(footer, text="清空日志", command=self.clear_log).grid(row=0, column=5, padx=(8, 0))

    def _build_search_fields(self, frame: ttk.Frame) -> None:
        for i in range(4):
            frame.columnconfigure(i, weight=1)

        ttk.Label(frame, text="检索模式").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            frame,
            textvariable=self.mode_var,
            values=["keyword", "journal", "journal_keyword", "author", "issn", "advanced", "doi_batch"],
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

        ttk.Label(frame, text="直接粘贴 DOI 或表格内容").grid(row=8, column=0, columnspan=4, sticky="w", pady=(12, 0))
        self.paste_text = Text(frame, height=12, wrap="none", font=("Consolas", 9))
        self.paste_text.grid(row=9, column=0, columnspan=4, sticky="ew", pady=(2, 6))

        self.preview_button = ttk.Button(frame, text="预览解析", command=self.preview_doi_input)
        self.preview_button.grid(row=10, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(frame, text="清空粘贴", command=self.clear_paste_text).grid(row=10, column=1, sticky="ew", padx=(0, 8))
        ttk.Label(frame, textvariable=self.preview_status_var, foreground="#555555").grid(
            row=10, column=2, columnspan=2, sticky="w"
        )

    def _build_output_fields(self, frame: ttk.Frame) -> None:
        for i in range(3):
            frame.columnconfigure(i, weight=1)

        ttk.Label(frame, text="输出目录").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.output_var).grid(row=1, column=0, columnspan=2, sticky="ew", padx=(0, 8), pady=(2, 8))
        ttk.Button(frame, text="选择", command=self.choose_output_dir).grid(row=1, column=2, sticky="ew", pady=(2, 8))

        ttk.Label(frame, text="DOI 批量输入表").grid(row=2, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.input_file_var).grid(row=3, column=0, columnspan=2, sticky="ew", padx=(0, 8), pady=(2, 8))
        ttk.Button(frame, text="选择", command=self.choose_input_file).grid(row=3, column=2, sticky="ew", pady=(2, 8))

        ttk.Label(frame, text="Excel 工作表名").grid(row=4, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.sheet_var).grid(row=5, column=0, sticky="ew", padx=(0, 8), pady=(2, 8))

        ttk.Label(frame, text="DOI 列名").grid(row=4, column=1, sticky="w")
        ttk.Entry(frame, textvariable=self.doi_column_var).grid(row=5, column=1, sticky="ew", padx=(0, 8), pady=(2, 8))

        ttk.Label(frame, text="Cookie JSON 文件").grid(row=6, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.cookies_file_var).grid(row=7, column=0, columnspan=2, sticky="ew", padx=(0, 8), pady=(2, 8))
        ttk.Button(frame, text="选择", command=self.choose_cookies_file).grid(row=7, column=2, sticky="ew", pady=(2, 8))

        ttk.Label(frame, text="自定义文件名").grid(row=8, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.filename_var).grid(row=9, column=0, columnspan=3, sticky="ew", pady=(2, 8))

        ttk.Checkbutton(frame, text="从本机 Chrome 读取 Cookie", variable=self.browser_cookies_var).grid(
            row=10, column=0, columnspan=3, sticky="w", pady=(4, 2)
        )
        ttk.Checkbutton(frame, text="先弹出 Chrome 手动登录", variable=self.open_login_var).grid(
            row=11, column=0, columnspan=3, sticky="w", pady=2
        )
        ttk.Checkbutton(frame, text="检索后下载 PDF", variable=self.download_pdf_var).grid(
            row=12, column=0, columnspan=3, sticky="w", pady=2
        )

        tips = (
            "使用建议：先在普通 Chrome 中登录学校/机构账号，再勾选 Cookie。\n"
            "PDF 下载是否成功取决于机构权限、Cookie 状态和出版商访问限制。"
        )
        ttk.Label(frame, text=tips, foreground="#555555", wraplength=420).grid(
            row=13, column=0, columnspan=3, sticky="ew", pady=(10, 0)
        )

        ttk.Label(frame, text="预览解析结果").grid(row=14, column=0, columnspan=3, sticky="w", pady=(12, 0))
        self.preview_text = Text(frame, height=12, wrap="none", font=("Consolas", 9))
        self.preview_text.grid(row=15, column=0, columnspan=3, sticky="ew", pady=(2, 0))

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
            var.trace_add("write", lambda *_args: self._refresh_command_preview())

    def _validate_inputs(self) -> bool:
        if (
            self.mode_var.get() == "doi_batch"
            and not self.input_file_var.get().strip()
            and not self._get_pasted_text()
        ):
            messagebox.showerror("参数错误", "DOI 批量下载模式需要选择输入表格，或在粘贴框中粘贴 DOI。")
            return False
        try:
            count = int(self.count_var.get().strip())
            if count <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("参数错误", "最大数量必须是正整数，例如 50。")
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
            self.command_var.set(" ".join(self._quote_for_preview(part) for part in cmd))
        except Exception as exc:
            self.command_var.set(f"命令预览生成失败: {exc}")

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

    def _get_pasted_text(self) -> str:
        if not hasattr(self, "paste_text"):
            return ""
        return self.paste_text.get("1.0", "end").strip()

    @staticmethod
    def _extract_doi_from_text(text: str) -> str:
        match = re.search(r"10\.\d{4,9}/[^\s,;\"'<>\]\)\}]+", text.strip(), flags=re.I)
        if not match:
            return ""
        doi = re.split(r"[\]\)\}\s<>,;]+", match.group(0), maxsplit=1)[0]
        return doi.strip().strip(".;,")

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
        self.preview_text.delete("1.0", "end")
        self.preview_status_var.set("未预览")
        self._refresh_command_preview()

    def preview_doi_input(self) -> None:
        if self.mode_var.get() != "doi_batch":
            messagebox.showinfo("预览解析", "预览解析仅用于 doi_batch 模式。")
            return
        if not self.input_file_var.get().strip() and not self._get_pasted_text():
            messagebox.showerror("预览解析", "请先选择 DOI 表格，或粘贴 DOI 内容。")
            return

        self.preview_button.configure(state="disabled")
        self.preview_status_var.set("正在后台解析预览...")
        self.preview_text.delete("1.0", "end")
        threading.Thread(target=self._preview_worker, daemon=True).start()

    def _preview_worker(self) -> None:
        try:
            if self.input_file_var.get().strip():
                rows, total = self._preview_from_file(Path(self.input_file_var.get().strip()))
            else:
                rows, total = self._preview_from_paste()
            self.preview_queue.put(("ok", rows, total))
        except Exception as exc:
            self.preview_queue.put(("error", str(exc), 0))

    def _preview_from_paste(self) -> tuple[list[dict], int]:
        rows = []
        total = 0
        for line_no, line in enumerate(self._get_pasted_text().splitlines(), start=1):
            doi = self._extract_doi_from_text(line)
            if not doi:
                continue
            total += 1
            if len(rows) < PREVIEW_LIMIT:
                rows.append({"row_number": line_no, "doi": doi, "title": ""})
        return rows, total

    def _preview_from_file(self, path: Path) -> tuple[list[dict], int]:
        ext = path.suffix.lower()
        if ext == ".csv":
            return self._preview_csv(path)
        if ext in {".txt", ".md", ".markdown", ".tsv"}:
            return self._preview_text_file(path)
        if ext in {".xlsx", ".xlsm"}:
            return self._preview_xlsx(path)
        raise ValueError("仅支持 .csv、.xlsx、.xlsm、.txt、.md、.markdown、.tsv 文件")

    def _find_doi_column(self, headers: list[str]) -> str:
        requested = self.doi_column_var.get().strip()
        if requested:
            if requested in headers:
                return requested
            lowered = {h.lower(): h for h in headers}
            if requested.lower() in lowered:
                return lowered[requested.lower()]
            raise ValueError(f"找不到 DOI 列：{requested}")
        candidates = {"doi", "doi号", "doi號"}
        for header in headers:
            if header.strip().lower() in candidates:
                return header
        raise ValueError(f"未识别 DOI 列。请填写 DOI 列名。现有列：{', '.join(headers)}")

    def _preview_csv(self, path: Path) -> tuple[list[dict], int]:
        last_error = None
        for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk", "cp936"):
            try:
                rows = []
                total = 0
                with path.open("r", newline="", encoding=encoding) as f:
                    reader = csv.DictReader(f)
                    headers = [h or "" for h in (reader.fieldnames or [])]
                    doi_col = self._find_doi_column(headers)
                    for row_number, row in enumerate(reader, start=2):
                        doi = self._extract_doi_from_text(str(row.get(doi_col, "")))
                        if not doi:
                            continue
                        total += 1
                        if len(rows) < PREVIEW_LIMIT:
                            rows.append({
                                "row_number": row_number,
                                "doi": doi,
                                "title": str(row.get("title") or row.get("标题") or ""),
                            })
                return rows, total
            except UnicodeDecodeError as exc:
                last_error = exc
        raise ValueError(f"无法识别 CSV 编码：{last_error}")

    def _preview_text_file(self, path: Path) -> tuple[list[dict], int]:
        last_error = None
        for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk", "cp936"):
            try:
                rows = []
                total = 0
                with path.open("r", encoding=encoding) as f:
                    for line_no, line in enumerate(f, start=1):
                        doi = self._extract_doi_from_text(line)
                        if not doi:
                            continue
                        total += 1
                        if len(rows) < PREVIEW_LIMIT:
                            rows.append({"row_number": line_no, "doi": doi, "title": ""})
                return rows, total
            except UnicodeDecodeError as exc:
                last_error = exc
        raise ValueError(f"无法识别文本编码：{last_error}")

    def _preview_xlsx(self, path: Path) -> tuple[list[dict], int]:
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        sheet_name = self.sheet_var.get().strip()
        if sheet_name and sheet_name not in wb.sheetnames:
            raise ValueError(f"找不到工作表：{sheet_name}。可用工作表：{', '.join(wb.sheetnames)}")
        ws = wb[sheet_name] if sheet_name else wb[wb.sheetnames[0]]
        iterator = ws.iter_rows(values_only=True)
        headers_raw = next(iterator, None)
        if not headers_raw:
            return [], 0
        headers = [str(h).strip() if h is not None else "" for h in headers_raw]
        doi_col = self._find_doi_column(headers)
        doi_index = headers.index(doi_col)
        title_index = next((i for i, h in enumerate(headers) if h.lower() == "title" or h == "标题"), None)

        rows = []
        total = 0
        for row_number, values in enumerate(iterator, start=2):
            value = values[doi_index] if doi_index < len(values) else ""
            doi = self._extract_doi_from_text(str(value or ""))
            if not doi:
                continue
            total += 1
            if len(rows) < PREVIEW_LIMIT:
                title = ""
                if title_index is not None and title_index < len(values):
                    title = str(values[title_index] or "")
                rows.append({"row_number": row_number, "doi": doi, "title": title})
        return rows, total

    def _drain_preview_queue(self) -> None:
        try:
            while True:
                item = self.preview_queue.get_nowait()
                kind = item[0]
                if kind == "ok":
                    rows, total = item[1], item[2]
                    self.preview_text.delete("1.0", "end")
                    self.preview_text.insert("end", "row\tdoi\ttitle\n")
                    for row in rows:
                        title = row.get("title", "").replace("\t", " ")[:80]
                        self.preview_text.insert("end", f"{row['row_number']}\t{row['doi']}\t{title}\n")
                    more = "" if total <= PREVIEW_LIMIT else f"，仅显示前 {PREVIEW_LIMIT} 条"
                    self.preview_status_var.set(f"识别到 {total} 条 DOI{more}")
                    self.preview_button.configure(state="normal")
                elif kind == "error":
                    self.preview_status_var.set("预览失败")
                    self.preview_button.configure(state="normal")
                    messagebox.showerror("预览解析失败", item[1])
        except queue.Empty:
            pass
        self.root.after(150, self._drain_preview_queue)

    def run_scraper(self) -> None:
        if self.process is not None:
            messagebox.showinfo("正在运行", "当前任务还没有结束。")
            return
        if not self._validate_inputs():
            return

        cmd = self._build_command(materialize_paste=True)
        output_dir = self.output_var.get().strip()
        if output_dir:
            Path(output_dir).mkdir(parents=True, exist_ok=True)

        self.clear_log()
        self._log("启动任务：")
        self._log(self.command_var.get())
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
                else:
                    self._log(item.rstrip("\n"))
        except queue.Empty:
            pass
        self.root.after(100, self._drain_log_queue)

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
