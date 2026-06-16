# ScienceDirect Paper Scraper

Windows-friendly ScienceDirect metadata scraper and PDF downloader with a Tkinter UI.

## Attribution

This tool is modified from [GAO-pooh/paper-scraper](https://github.com/GAO-pooh/paper-scraper/tree/main). This local version keeps the ScienceDirect workflow, adds a Windows UI, DOI batch processing, Cookie JSON support, and Windows CSV encoding handling.

## Start UI

```powershell
.\start_paper_scraper_ui.bat
```

On first launch, the script creates `.venv` and installs `requirements.txt`. If initialization fails, the window stays open with the error message.

## Recommended Workflow: DOI Batch PDF Download

1. Open the default `DOI 批量下载` tab.
2. In `1 数据来源`, choose a DOI table such as `lookup_preview.csv`, `papers.txt`, or `papers.md`, or paste DOI/table text directly.
3. Fill `Excel 工作表名` or `DOI 列名` only when automatic detection is not enough.
4. In `2 权限与输出`, choose the output directory and the Cookie Editor export file in `Cookie JSON 文件`.
5. Keep `检索后下载 PDF` checked; use Chrome Cookie or manual login only when you are not using Cookie JSON.
6. Click `预览解析` and check the DOI count, detected column/method, and first 200 preview rows in `3 预览检查`.
7. Click the fixed bottom `开始运行` button. The UI switches to `运行日志` while the task runs.

Do not enable local Chrome cookie reading when using an exported `cookies.json`.

Supported input formats include `.xlsx`, `.xlsm`, `.csv`, `.tsv`, `.txt`, `.md`, and `.markdown`. Text and Markdown files are scanned line by line for DOI values and do not need a header.

You can also paste DOI lines or an Excel-copied table into `直接粘贴 DOI 或表格内容`. The UI previews only the first 200 rows and counts all detected DOI values to avoid freezing on large batches.

The UI remembers the recent output directory, Cookie file, window size, and common login options in `results/_ui_settings.json`.

Command-line equivalent:

```powershell
.\.venv\Scripts\python.exe sd_scraper.py -m doi_batch --input "papers.csv" --doi-column "doi" --cookies "cookies.json" --download-pdfs
```

Outputs are written to `results\doi_batch_timestamp\`, including `doi_batch_resolved.xlsx`, `doi_batch_failed.csv`, `pdf_download_report.csv`, `run_summary.txt`, and `pdfs\`.
