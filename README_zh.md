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

## 当前推荐用法：DOI 批量下载 PDF

适用于你已经有一批文献表格，表格中包含 DOI 列，并且已经用浏览器 Cookie Editor 导出了 `cookies.json` 的情况。

界面操作顺序：

1. 在“检索模式”中选择 `doi_batch`。
2. 选择“输出目录”，用于保存解析结果、失败报告和 PDF。
3. 在“DOI 批量输入表”中选择你的文献文件，支持 `.xlsx`、`.xlsm`、`.csv`、`.tsv`、`.txt`、`.md`、`.markdown`。
4. 在“DOI 列名”中填写 DOI 所在列名，例如 `doi`、`DOI` 或 `DOI号`。
5. 在“Cookie JSON 文件”中选择 Cookie Editor 导出的 `cookies.json`。
6. 点击“预览解析”，确认 DOI 总数和前 200 条预览。
7. 只勾选“检索后下载 PDF”。
8. 点击“开始运行”。

注意：使用 `cookies.json` 时，不需要勾选“从本机 Chrome 读取 Cookie”，也不需要勾选“先弹出 Chrome 手动登录”。

如果不想导入文件，也可以把 DOI 列表或从 Excel 复制出的表格直接粘贴到“直接粘贴 DOI 或表格内容”。点击“开始运行”时，程序会自动生成临时 CSV 文件。大批量导入时，界面只预览前 200 条并统计总数，避免一次性渲染全部数据导致卡死。

## DOI 表格格式

最少只需要 DOI 信息。Excel/CSV 推荐表格格式如下：

| title | authors | year | doi |
| --- | --- | --- | --- |
| Example title | Zhang; Li | 2024 | 10.xxxx/xxxxx |

程序会自动尝试识别 `doi`、`DOI`、`Doi`、`DOI号`、`doi号`。如果识别失败，请在界面中手动填写“DOI 列名”。

对于 `.txt`、`.md`、`.markdown`、`.tsv`，程序会逐行扫描 DOI，不要求表头。Windows 上 Excel/WPS 导出的 CSV 或文本文件可能是 GBK/ANSI 编码，程序会自动尝试 `utf-8-sig`、`utf-8`、`gb18030`、`gbk`、`cp936`。

## 输出文件

DOI 批量模式会在输出目录下生成一个时间戳子目录，例如：

```text
results\doi_batch_20260616_120000\
├── doi_batch_resolved.xlsx
├── doi_batch_failed.csv
└── pdfs\
```

- `doi_batch_resolved.xlsx`：成功解析到 ScienceDirect PII 的记录。
- `doi_batch_failed.csv`：空 DOI、重复 DOI、非 ScienceDirect DOI 或解析失败的记录。
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
