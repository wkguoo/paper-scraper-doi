# ScienceDirect 论文抓取工具

这是一个面向 Windows 使用的 ScienceDirect 论文元数据抓取和 PDF 下载辅助工具，提供命令行脚本和 `tkinter` 图形界面。

## 来源声明

本工具是在开源项目 [GAO-pooh/paper-scraper](https://github.com/GAO-pooh/paper-scraper/tree/main) 的基础上修改完成，主要调整包括：仅保留 ScienceDirect 相关功能、增加 Windows 图形界面、增加 DOI 批量解析与下载流程、支持 Cookie JSON 文件和常见 Windows CSV 编码。

## 主要文件

- `sd_scraper.py`：中文命令行脚本。
- `sd_scraper_en.py`：英文命令行脚本。
- `paper_scraper_ui.py`：Windows 图形界面。
- `paper_skill.py`：混合论文文本识别 + 公开 OA PDF 合规下载命令行入口。
- `paper_automation/`：`paper_skill.py` 使用的解析、去重、元数据补全、PDF 候选和 manifest 模块。
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

## 图形界面中的两个下载模式

图形界面现在提供两个入口：

- `DOI 批量下载` 和 `文献检索`：面向 ScienceDirect/Elsevier，使用你的机构权限、Cookie JSON 或浏览器登录状态，底层仍走原有 CDP/DevTools PDF 下载机制。
- `合法 OA 下载`：面向非 ScienceDirect 或混合来源论文列表，调用 `paper_skill.py`，只下载明确合法开放获取的 PDF，不读取 Cookie、不打开机构登录浏览器、不绕过付费墙。

如果你的文献大多是 `10.1016/...` 或明确来自 ScienceDirect，优先用 `DOI 批量下载`。如果来源混杂，且只想找公开可合法下载的 PDF，用 `合法 OA 下载`。

## 当前推荐用法：ScienceDirect DOI 批量下载 PDF

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

机构登录测试后如需清理本机凭据状态，可以运行：

```powershell
Remove-Item -Recurse -Force (Join-Path $env:TEMP "chrome_dbg_profile")
Remove-Item -Force ".\results\_auth\sciencedirect_cookies.json"
```

调试浏览器 profile 属于本机凭据状态。默认流程只复制最小浏览器状态子集，但仍不要分享该目录或 `results\_auth\`。

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

## 混合文本识别与合法 OA PDF 下载

如果你复制的是一大段格式混乱的论文信息，而不只是标准 DOI 表格，可以在图形界面中打开“合法 OA 下载”页，选择 `.txt/.md/.markdown/.csv` 文件或直接粘贴文本。该模式会调用 `paper_skill.py`，自动识别 DOI 和标题候选、去重、通过公开元数据服务补全文献信息，并且只下载明确可合法开放获取的 PDF 候选。这个流程不使用 ScienceDirect Cookie，不读取本机浏览器 Cookie，不绕过付费墙，也不会使用 Sci-Hub、LibGen 等侵权来源。

对应命令行也可以直接使用 `paper_skill.py`。

推荐先 dry-run 检查识别和可下载情况：

```powershell
py paper_skill.py --input "papers.txt" --out "D:\Literature\Papers" --email "you@example.com" --dry-run
```

确认无误后下载开放获取 PDF：

```powershell
py paper_skill.py --input "papers.txt" --out "D:\Literature\Papers" --email "you@example.com"
```

也可以直接在命令行传入少量粘贴文本：

```powershell
py paper_skill.py --text "Example paper DOI: 10.xxxx/example" --out "D:\Literature\Papers" --email "you@example.com"
```

输出目录结构：

```text
D:\Literature\Papers\
├── pdfs\
├── metadata\
│   ├── manifest.csv
│   └── manifest.json
├── failed\
│   └── duplicates.csv
└── logs\
```

`manifest.csv` / `manifest.json` 会记录每篇论文的输入 DOI/标题、补全后的 DOI/标题、作者、期刊、年份、OA 状态、PDF 来源、下载状态和失败原因。无法合法自动下载的论文不会伪造成功记录，会标记为 `no_legal_open_pdf`、`needs_review`、`response_not_pdf` 等原因。

## Codex Skills

推荐使用统一入口 `paper-download`，它会根据你的请求自动选择下载流程：

- `paper-download`：统一入口，自动选择 ScienceDirect 机构权限下载或合法 OA 下载。
- `sciencedirect-doi-download`：兼容旧入口，通过用户已有机构权限下载 ScienceDirect/Elsevier PDF。
- `legal-oa-paper-download`：兼容旧入口，只用公开元数据服务解析文献并下载合法 OA PDF。

安装或刷新到 Codex：

```powershell
powershell -ExecutionPolicy Bypass -File install_codex_skills.ps1
```

安装脚本会把 skill 复制到 `$CODEX_HOME\skills` 或 `%USERPROFILE%\.codex\skills`，并把当前仓库路径写入用户环境变量 `PAPER_SCRAPER_DOI_ROOT`。

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
- 请不要分享 `%TEMP%\chrome_dbg_profile` 或 `results\_auth\`。
- 非 ScienceDirect/Elsevier DOI 会跳过并写入失败报告，不会中断整个任务。
- `paper_skill.py` 只处理公开元数据和合法开放获取 PDF；需要机构登录或出版社禁止自动下载的论文会进入 manifest 的失败/待处理记录。
