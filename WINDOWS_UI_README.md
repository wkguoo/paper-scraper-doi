# ScienceDirect Paper Scraper Windows UI

这个界面使用 Python 标准库 `tkinter` 编写，不需要额外安装 GUI 框架。当前版本只保留 ScienceDirect。

## 来源声明

本工具是在开源项目 [GAO-pooh/paper-scraper](https://github.com/GAO-pooh/paper-scraper/tree/main) 的基础上修改完成。

## 启动方式

在 Windows 文件管理器中双击：

```text
start_paper_scraper_ui.bat
```

首次启动时脚本会自动创建 `.venv` 并安装 `requirements.txt` 中的依赖；如果安装失败，窗口会保留错误信息，方便排查。

或在 PowerShell 中运行：

```powershell
cd "C:\Users\wkguopro\Documents\New project 2\paper-scraper-main"
.\start_paper_scraper_ui.bat
```

## 当前推荐操作流程：DOI 批量下载 PDF

界面默认打开“DOI 批量下载”页，并按步骤分成“1 数据来源”“2 权限与输出”“3 预览检查”和底部运行按钮。

1. 在“1 数据来源”中选择 DOI 表格，例如 `lookup_preview.csv`、`papers.txt` 或 `papers.md`；也可以直接粘贴 DOI/表格内容。
2. 如需指定 Excel 工作表或 DOI 列名，填写“Excel 工作表名”和“DOI 列名”。
3. 在“2 权限与输出”中选择输出目录和 Cookie Editor 导出的 `cookies.json`。
4. 保持“检索后下载 PDF”勾选；如果不用 Cookie JSON，再按需选择“从本机 Chrome 读取 Cookie”或“先弹出 Chrome 手动登录”。
5. 点击“预览解析”，在“3 预览检查”中确认识别到的 DOI 数量、列识别方式和前 200 条预览。
6. 点击底部固定操作栏中的“开始运行”；运行后界面会切到“运行日志”页。

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

界面会记住最近的输出目录、Cookie 文件、窗口尺寸和常用登录选项，配置保存在 `results/_ui_settings.json`。

## 输出文件

运行后会生成类似目录：

```text
results\doi_batch_时间戳\
├── doi_batch_resolved.xlsx
├── doi_batch_failed.csv
├── pdf_download_report.csv
├── run_summary.txt
└── pdfs\
```

`doi_batch_failed.csv` 用于查看哪些 DOI 没有解析；`pdf_download_report.csv` 逐篇记录 PDF 下载成功、失败或跳过；`run_summary.txt` 汇总本次任务和下一步建议。

## 生成 Windows UI 源码包

运行：

```powershell
.\make_windows_ui_package.bat
```

生成目录：

```text
dist\paper-scraper-ui-windows
```
