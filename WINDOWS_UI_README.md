# ScienceDirect Paper Scraper Windows UI

这个界面使用 Python 标准库 `tkinter` 编写，不需要额外安装 GUI 框架。当前版本只保留 ScienceDirect。

## 来源声明

本工具是在开源项目 [GAO-pooh/paper-scraper](https://github.com/GAO-pooh/paper-scraper/tree/main) 的基础上修改完成。

## 启动方式

在 Windows 文件管理器中双击：

```text
start_paper_scraper_ui.bat
```

或在 PowerShell 中运行：

```powershell
cd "C:\Users\wkguopro\Documents\New project 2\paper-scraper-main"
.\start_paper_scraper_ui.bat
```

## 当前推荐操作流程：DOI 批量下载 PDF

1. 在“检索模式”中选择 `doi_batch`。
2. 选择“输出目录”。
3. 在“DOI 批量输入表”中选择你的文献文件，例如 `lookup_preview.csv`、`papers.txt` 或 `papers.md`。
4. 在“DOI 列名”中填写 DOI 所在列名，例如 `doi`。
5. 在“Cookie JSON 文件”中选择 Cookie Editor 导出的 `cookies.json`。
6. 点击“预览解析”，确认识别到的 DOI 数量和前 200 条预览。
7. 只勾选“检索后下载 PDF”。
8. 点击“开始运行”。

不要勾选“从本机 Chrome 读取 Cookie”，也不要勾选“先弹出 Chrome 手动登录”。使用 Cookie Editor 导出的 `cookies.json` 时，程序会通过 `--cookies` 参数读取该文件。

也可以不选择文件，直接把 DOI 列表或从 Excel 复制出的表格粘贴到“直接粘贴 DOI 或表格内容”。点击“预览解析”后，界面只显示前 200 条，但会统计全部 DOI 数量；点击“开始运行”时会自动生成临时 CSV。

## 输入表要求

最少需要 DOI 列。推荐列名：

```text
doi
```

也支持：

```text
DOI
Doi
DOI号
doi号
```

支持 `.xlsx`、`.xlsm`、`.csv`、`.tsv`、`.txt`、`.md`、`.markdown`。文本和 Markdown 文件会逐行扫描 DOI，不要求表头。如果是 CSV/文本文件，Excel/WPS 导出的 GBK/ANSI 编码也可以读取。

大批量导入时，预览和日志都采用分批刷新，避免一次性渲染全部数据导致界面卡死。

## 输出文件

运行后会生成类似目录：

```text
results\doi_batch_时间戳\
├── doi_batch_resolved.xlsx
├── doi_batch_failed.csv
└── pdfs\
```

`doi_batch_failed.csv` 用于查看哪些 DOI 没有解析或下载失败。

## 生成 Windows UI 源码包

运行：

```powershell
.\make_windows_ui_package.bat
```

生成目录：

```text
dist\paper-scraper-ui-windows
```
