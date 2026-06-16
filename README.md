# ScienceDirect Paper Scraper

Windows-friendly ScienceDirect metadata scraper and PDF downloader with a Tkinter UI.

## Attribution

This tool is modified from [GAO-pooh/paper-scraper](https://github.com/GAO-pooh/paper-scraper/tree/main). This local version keeps the ScienceDirect workflow, adds a Windows UI, DOI batch processing, Cookie JSON support, and Windows CSV encoding handling.

## Start UI

```powershell
.\start_paper_scraper_ui.bat
```

## Recommended Workflow: DOI Batch PDF Download

1. Select `doi_batch` in the search mode field.
2. Choose the output directory.
3. Choose the DOI batch input file, such as `lookup_preview.csv`, `papers.txt`, or `papers.md`.
4. Fill the DOI column name, such as `doi`.
5. Choose the Cookie Editor export file in `Cookie JSON 文件`.
6. Click `预览解析` to check the DOI count and the first 200 preview rows.
7. Only check `检索后下载 PDF`.
8. Click `开始运行`.

Do not enable local Chrome cookie reading when using an exported `cookies.json`.

Supported input formats include `.xlsx`, `.xlsm`, `.csv`, `.tsv`, `.txt`, `.md`, and `.markdown`. Text and Markdown files are scanned line by line for DOI values and do not need a header.

You can also paste DOI lines or an Excel-copied table into `直接粘贴 DOI 或表格内容`. The UI previews only the first 200 rows and counts all detected DOI values to avoid freezing on large batches.

Command-line equivalent:

```powershell
.\.venv\Scripts\python.exe sd_scraper.py -m doi_batch --input "papers.csv" --doi-column "doi" --cookies "cookies.json" --download-pdfs
```

Outputs are written to `results\doi_batch_timestamp\`, including `doi_batch_resolved.xlsx`, `doi_batch_failed.csv`, and `pdfs\`.
