# ScienceDirect 论文抓取工具

这是一个面向 Windows 使用的 ScienceDirect 论文元数据抓取和 PDF 下载辅助工具，提供命令行脚本和 `tkinter` 图形界面。

## 来源声明

本工具是在开源项目 [GAO-pooh/paper-scraper](https://github.com/GAO-pooh/paper-scraper/tree/main) 的基础上修改完成，主要调整包括：仅保留 ScienceDirect 相关功能、增加 Windows 图形界面、增加 DOI 批量解析与下载流程、支持 Cookie JSON 文件和常见 Windows CSV 编码。

## 主要文件

- `sd_scraper.py`：中文命令行脚本。
- `sd_scraper_en.py`：英文命令行脚本。
- `paper_scraper_ui.py`：Windows 图形界面。
- `start_paper_scraper_ui.bat`：Windows 双击启动入口。
- `requirements.txt`：依赖清单。

## 安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 启动图形界面

```powershell
.\start_paper_scraper_ui.bat
```

首次双击启动会自动创建 `.venv` 并安装依赖；如果安装失败，窗口会保留错误信息。

## 当前推荐用法：DOI 批量下载 PDF

适用于你已经有一批文献表格，表格中包含 DOI 列，并且已经用浏览器 Cookie Editor 导出了 `cookies.json` 的情况。

界面默认打开“DOI 批量下载”页。推荐操作顺序：

1. 在“1 数据来源”中选择 DOI 表格，或直接粘贴 DOI/表格内容。
2. 如需指定 Excel 工作表或 DOI 列名，填写“Excel 工作表名”和“DOI 列名”。
3. 在“2 权限与输出”中选择输出目录和 Cookie Editor 导出的 `cookies.json`。
4. 保持“检索后下载 PDF”勾选；如果不用 Cookie JSON，再按需选择高级登录方式。
5. 点击“预览解析”，在“3 预览检查”中确认 DOI 总数、列识别方式和前 200 条预览。
6. 点击底部固定操作栏中的“开始运行”，运行后会自动切到“运行日志”页。

注意：使用 `cookies.json` 时，不需要勾选“从本机 Chrome 读取 Cookie”，也不需要勾选“先弹出 Chrome 手动登录”。

如果不想导入文件，也可以把 DOI 列表或从 Excel 复制出的表格直接粘贴到“直接粘贴 DOI 或表格内容”。点击“开始运行”时，程序会自动生成临时 CSV 文件。大批量导入时，界面只预览前 200 条并统计总数，避免一次性渲染全部数据导致卡死。

界面会记住最近的输出目录、Cookie 文件、窗口尺寸和常用登录选项，配置保存在 `results/_ui_settings.json`。请不要把该文件和 Cookie 一起上传到公开平台。

## DOI 表格格式

最少只需要 DOI 信息。Excel/CSV 推荐表格格式如下：

| title | authors | year | doi |
| --- | --- | --- | --- |
| Example title | Zhang; Li | 2024 | 10.xxxx/xxxxx |

程序会自动尝试识别 `doi`、`DOI`、`Doi`、`DOI号`、`doi号`。如果识别失败，请在界面中手动填写“DOI 列名”。

对于 `.txt`、`.md`、`.markdown`，程序会逐行扫描 DOI，不要求表头；`.tsv` 会先按表格解析，失败时再逐行扫描。Windows 上 Excel/WPS 导出的 CSV 或文本文件可能是 GBK/ANSI 编码，程序会自动尝试 `utf-8-sig`、`utf-8`、`gb18030`、`gbk`、`cp936`。

## 输出文件

DOI 批量模式会在输出目录下生成一个时间戳子目录，例如：

```text
results\doi_batch_20260616_120000\
├── doi_batch_resolved.xlsx
├── doi_batch_failed.csv
├── pdf_download_report.csv
├── run_summary.txt
└── pdfs\
```

- `doi_batch_resolved.xlsx`：成功解析到 ScienceDirect PII 的记录。
- `doi_batch_failed.csv`：空 DOI、重复 DOI、非 ScienceDirect DOI 或解析失败的记录。
- `pdf_download_report.csv`：逐篇记录 PDF 下载成功、失败或跳过原因。
- `run_summary.txt`：本次任务摘要、失败原因分组和下一步建议。
- `pdfs`：下载成功的 PDF 文件。

## 命令行等价示例

```powershell
.\.venv\Scripts\python.exe sd_scraper.py -m doi_batch --input "papers.csv" --doi-column "doi" --cookies "cookies.json" --download-pdfs
```

如果 DOI 在普通文本或 Markdown 文件中：

```powershell
.\.venv\Scripts\python.exe sd_scraper.py -m doi_batch --input "papers.md" --cookies "cookies.json" --download-pdfs
```

如果是 Excel 且需要指定工作表：

```powershell
.\.venv\Scripts\python.exe sd_scraper.py -m doi_batch --input "papers.xlsx" --doi-column "DOI号" --sheet "Sheet1" --cookies "cookies.json" --download-pdfs
```

## 注意事项

- PDF 下载依赖你的机构权限和 `cookies.json` 是否有效。
- 请不要把 `cookies.json` 上传到公开平台。
- 非 ScienceDirect/Elsevier DOI 会跳过并写入失败报告，不会中断整个任务。
