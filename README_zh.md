# 中文说明

[English](README.md) | 中文说明

# 论文下载助手：ScienceDirect 下载 + OA 资源获取

这是一个面向 Windows 的论文下载辅助工具。推荐环境是 Windows 10/11 + Python 3.10 或 3.11。它可以配合 Codex Skills、图形界面或命令行，把 DOI 表格、AI 推荐文献列表、复制来的论文文本整理成可检查的报告，并下载 PDF。Codex Skill 是可选增强入口；不使用 Codex 时，也可以直接运行图形界面或命令行。

本项目主要包含两条流程：

| 使用场景 | 推荐入口 | 说明 |
| --- | --- | --- |
| 你有学校/机构的 ScienceDirect 或 Elsevier 权限，要下载 `10.1016/...` 这类论文 | `paper-download` 或 `sciencedirect-doi-download` | 使用你的机构登录状态或 Cookie 下载有权限访问的 ScienceDirect PDF。 |
| 你有混合出版社论文列表，想查找开放获取 PDF 候选资源 | `paper-download` 或 `legal-oa-paper-download` | 不使用机构 Cookie；先尝试公开 OA 下载，失败后自动回退到第三方数据源。 |
| 你不想写命令，只想点按钮 | `start_paper_scraper_ui.bat` | 打开 Windows Tkinter 图形界面。 |

## 这个工具能做什么

- 从 Excel、CSV、TXT、Markdown 或直接粘贴文本里识别 DOI。
- 对混乱的 AI 推荐列表先做 preflight，标出有效 DOI、重复项和需要人工复核的记录。
- 通过你的机构权限下载 ScienceDirect PDF，并生成下载报告。
- 默认尝试下载 ScienceDirect 补充材料，并把附件状态写入报告。
- 对非 ScienceDirect 或混合来源列表，使用公开元数据服务查找公开开放获取 PDF 候选资源。
- 给 Codex 安装 `paper-download` 等 Skills，让你可以直接用自然语言发任务。

## 这个工具不能做什么

- 不能替你输入学校账号密码。
- 不能自动完成 CAPTCHA 或人机验证。
- 不能保证题名-only 的模糊匹配 100% 正确；不确定的记录会进入 `needs_review`。

## 新手最快开始

下面命令都在 PowerShell 里运行。先进入你下载或克隆后的仓库目录：

```powershell
cd "<仓库路径>"
```

例如仓库放在 `D:\Tools\paper-scraper-doi`，就运行：

```powershell
cd "D:\Tools\paper-scraper-doi"
```

### 1. 安装 Python 依赖

如果你还没有 Python，先安装 Python 3。安装时建议勾选 “Add Python to PATH”。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. 先预检查 Codex Skills 安装位置

`-DryRun` 只检查路径和将要复制的 skill，不会改文件，也不会改环境变量：

```powershell
powershell -ExecutionPolicy Bypass -File .\install_codex_skills.ps1 -DryRun
```

正常情况下会看到类似信息：

```text
Repository: <仓库路径>
Codex skills target: C:\Users\<你的用户名>\.codex\skills
Install skill: legal-oa-paper-download -> ...
Install skill: paper-download -> ...
Install skill: sciencedirect-doi-download -> ...
Set user environment variable PAPER_SCRAPER_DOI_ROOT=<仓库路径>
Dry run only; no files or environment variables were changed.
```

### 3. 正式安装或刷新 Codex Skills

```powershell
powershell -ExecutionPolicy Bypass -File .\install_codex_skills.ps1
```

安装脚本会做两件事：

- 把 `skills\paper-download`、`skills\sciencedirect-doi-download`、`skills\legal-oa-paper-download` 复制到 Codex 的 skills 目录。
- 设置用户环境变量 `PAPER_SCRAPER_DOI_ROOT=<仓库路径>`，让 Codex 能找到本仓库。

安装后请重启 Codex 或重新打开终端，让新的环境变量生效。

### 4. 验证命令行入口可用

```powershell
.\.venv\Scripts\python.exe sd_scraper.py --help
.\.venv\Scripts\python.exe paper_skill.py --help
```

如果这两个命令能显示帮助信息，说明 Python 依赖基本可用。

## 推荐用法：直接让 Codex 调用 Skill

安装 Skills 后，在 Codex 里优先使用统一入口 `paper-download`。它会根据你的请求自动选择 ScienceDirect 机构权限流程或 OA 资源辅助获取流程。

可用入口：

- `paper-download`：推荐入口，自动判断走哪条下载流程。
- `sciencedirect-doi-download`：明确用于 ScienceDirect/Elsevier 机构权限下载。
- `legal-oa-paper-download`：兼容入口，用于公开开放获取 PDF 候选资源的辅助获取。

### 示例 1：ScienceDirect 机构权限下载

把下面这段复制到 Codex，再替换成自己的论文列表：

```text
Use $paper-download to download these ScienceDirect papers.
Save results to D:\Literature\ScienceDirect.
If anything is uncertain, put it in needs_review and report it at the end.

DOI: 10.1016/j.actamat.2016.08.081
DOI: 10.1016/j.scriptamat.2023.115000
```

第一次运行时，如果没有可用登录状态，工具可能会弹出 Chrome 或 Edge 窗口。请你自己在浏览器里完成学校、机构、VPN、CARSI 或图书馆登录。不要把账号密码发给 Codex。

### 示例 2：混乱 AI 推荐列表先做 preflight

如果你复制的是 ChatGPT、网页 AI、Google Scholar 或老师给的一段混乱推荐，先不要直接下载，先让工具检查识别结果：

```text
Use $paper-download to preflight these paper recommendations with --beginner --preflight.
Save results to D:\Literature\ScienceDirect.

1. A critical review of high entropy alloys and related concepts
2. DOI: 10.1016/j.actamat.2016.08.081
3. unclear recommendation about alloy fatigue without enough bibliographic information
```

preflight 只做输入识别、去重和复核提示，不下载 PDF，也不会生成补充材料目录。它会重点生成 `doi_intake_preview.csv`、`merged_doi_input.csv`、`doi_batch_failed.csv`、`run_summary.txt` 和 `00_给研究生查看\`，检查确认后再把 `merged_doi_input.csv` 交给 Codex 正式下载。

### 示例 3：查找公开开放获取 PDF 候选资源

如果你的论文来源混杂，或者没有机构权限，只想查找公开开放获取 PDF 候选资源：

```text
Use $paper-download to find PDF candidates for this list.
Save results to D:\Literature\OA.
Use you@example.com for polite metadata API access.

DOI: 10.1038/s41586-024-07000-1
Example title copied from a bibliography
```

这个流程不会读取 `cookies.json`，不会使用机构登录。

## 图形界面用法

如果你不想使用 Codex 或命令行，可以双击：

```text
start_paper_scraper_ui.bat
```

首次启动会自动创建 `.venv` 并安装依赖。界面里常用两个入口：

- `DOI 批量下载`：用于 ScienceDirect/Elsevier DOI 表格或 DOI 文本。
- `OA 资源辅助获取`：用于混合来源论文列表，仅尝试查找公开开放获取 PDF 候选资源。

ScienceDirect PDF 下载推荐使用 Cookie Editor 导出的 `cookies.json`。在界面中选择 `Cookie JSON 文件` 后，不需要再勾选“从本机 Chrome 读取 Cookie”。

更详细的 UI 说明见 [WINDOWS_UI_README.md](WINDOWS_UI_README.md)。

## 命令行示例

### ScienceDirect DOI 表格下载

```powershell
.\.venv\Scripts\python.exe sd_scraper.py -m doi_batch --input "papers.csv" --doi-column "doi" --cookies "cookies.json" --download-pdfs
```

如果只想下载正文 PDF，不下载补充材料：

```powershell
.\.venv\Scripts\python.exe sd_scraper.py -m doi_batch --input "papers.csv" --doi-column "doi" --cookies "cookies.json" --download-pdfs --no-download-supplements
```

如果输入是 Excel 且需要指定工作表：

```powershell
.\.venv\Scripts\python.exe sd_scraper.py -m doi_batch --input "papers.xlsx" --doi-column "DOI号" --sheet "Sheet1" --cookies "cookies.json" --download-pdfs
```

### ScienceDirect 新手 preflight

```powershell
.\.venv\Scripts\python.exe sd_institutional_skill.py --text "<论文列表>" --out results --beginner --preflight
```

preflight 只做本地识别、去重和复核提示，不联网补 DOI、不解析 ScienceDirect PII，也不下载 PDF。

### OA 资源辅助获取

建议先 dry-run 看识别结果：

```powershell
.\.venv\Scripts\python.exe paper_skill.py --input "papers.txt" --out "D:\Literature\OA" --email "you@example.com" --dry-run
```

确认无误后尝试下载可访问的公开开放获取 PDF：

```powershell
.\.venv\Scripts\python.exe paper_skill.py --input "papers.txt" --out "D:\Literature\OA" --email "you@example.com"
```

## 输入文件怎么准备

ScienceDirect DOI 批量模式最少只需要 DOI 信息。Excel 或 CSV 推荐这样写：

| title | authors | year | doi |
| --- | --- | --- | --- |
| Example title | Zhang; Li | 2024 | 10.1016/example |

支持的 DOI 列名包括：

```text
doi
DOI
Doi
DOI号
doi号
```

支持的文件类型：

- `.xlsx`
- `.xlsm`
- `.csv`
- `.tsv`
- `.txt`
- `.md`
- `.markdown`

TXT 和 Markdown 会逐行扫描 DOI，不要求表头。Windows 上 Excel/WPS 导出的 GBK/ANSI CSV 也会自动尝试读取。

## 输出文件怎么看

ScienceDirect 批量任务会在输出目录下生成一个时间戳子目录，例如：

```text
results\doi_batch_20260616_120000\
├── 00_给研究生查看\
│   ├── README_先看我.txt
│   ├── paper_index.csv
│   ├── paper_index.xlsx
│   └── 失败项_下一步处理.csv
├── doi_batch_resolved.xlsx
├── doi_batch_failed.csv
├── library_index.csv
├── pdf_download_report.csv
├── run_summary.json
├── run_summary.txt
└── pdfs\
```

常见输出含义：

| 文件或目录 | 什么时候生成 | 新手怎么看 |
| --- | --- | --- |
| `doi_intake_preview.csv` | preflight 或 skill 输入整理时 | 看哪些行是 `valid`，哪些是 `needs_review`。 |
| `merged_doi_input.csv` | preflight 或 skill 输入整理时 | 去重后的正式下载输入；UI 里的“使用预检合并表”会用它回填。 |
| `doi_batch_resolved.xlsx` | ScienceDirect DOI/PII 正式解析后 | 成功解析到 ScienceDirect 文章页的记录。 |
| `doi_batch_failed.csv` | 有空 DOI、重复 DOI、无效 DOI 或解析失败时 | 失败和需要复核的记录，不要忽略。 |
| `pdf_download_report.csv` | 启用 PDF 下载时 | 最重要，逐篇看 PDF 是 `success`、`failed` 还是 `skipped`。 |
| `run_summary.txt` | 每次任务 | 本次任务摘要和下一步建议。 |
| `run_summary.json` | 每次任务 | 给 UI 或后续脚本读取的机器可读摘要。 |
| `00_给研究生查看\` | 预检或正式任务 | 给课题组学生直接打开的入口，包含说明、论文索引和失败项下一步处理表。 |
| `library_index.csv` | 正式下载或索引生成时 | 与学生入口索引同类的信息，放在任务根目录便于脚本继续处理。 |
| `pdfs\` | PDF 下载成功时 | 下载好的正文 PDF。 |
| `supplement_download_report.csv` | PDF 下载且启用补充材料下载时 | 逐个记录补充材料状态。 |
| `supplements\` | 找到并下载补充材料时 | 保存补充材料附件。 |

`00_给研究生查看\paper_index.csv/xlsx` 和 `library_index.csv` 用相对路径指向正文 PDF 与补充材料，不复制下载文件。补充材料状态 `not_found` 表示页面没有检测到可下载 supplement 链接，不代表正文 PDF 失败。

OA 资源辅助获取流程会生成类似：

```text
D:\Literature\OA\
├── pdfs\
├── metadata\
│   ├── manifest.csv
│   └── manifest.json
├── failed\
│   └── duplicates.csv
└── logs\
```

`manifest.csv` 和 `manifest.json` 会记录每篇论文的 DOI、标题、作者、期刊、年份、OA 状态、PDF 来源、下载状态和失败原因。

## 常见问题

| 问题 | 处理方法 |
| --- | --- |
| Codex 找不到 skill | 重新运行 `powershell -ExecutionPolicy Bypass -File .\install_codex_skills.ps1`，然后重启 Codex。 |
| 不确定安装脚本会改哪里 | 先运行 `powershell -ExecutionPolicy Bypass -File .\install_codex_skills.ps1 -DryRun`。 |
| 没有弹出登录窗口 | 可能已经有可用 Cookie；也可能浏览器路径异常。先看日志，如果提示找不到浏览器，可安装 Chrome/Edge 或设置 `PAPER_SCRAPER_BROWSER_EXE`。 |
| 已登录但下载失败 | 打开 `pdf_download_report.csv` 看原因，常见是无机构权限、Cookie 过期、CAPTCHA、403 或限速。 |
| `needs_review` 很多 | 输入信息太少。给每篇论文补 DOI、完整题名、期刊、年份、卷期页后重跑。 |
| 补充材料状态是 `not_found` | 页面没有检测到可下载 supplement 链接，不代表正文 PDF 失败。 |
| `run_summary.txt` 中文乱码 | 用支持 UTF-8 的编辑器打开，或优先看 CSV/XLSX 报告。 |
| 非 ScienceDirect DOI 下载不了 | 改用 `paper-download` 的 OA 资源辅助获取流程，或手工通过图书馆/出版社处理。 |

## Cookie 使用和安全

ScienceDirect 机构下载依赖你的机构权限。最稳妥的新手方式是用 Cookie Editor 从已经登录的 `sciencedirect.com` 导出 `cookies.json`，然后在 UI 或 CLI 里选择它。

详细步骤见 [如何导出机构Cookie.md](如何导出机构Cookie.md)。

必须注意：

- 不要把 `cookies.json` 上传到 GitHub。
- 不要提交下载的 PDF、补充材料或生成的结果表。
- 不要分享 `results\_auth\` 或 `%TEMP%\chrome_dbg_profile`。
- 不要把学校账号密码发给 Codex、脚本或任何人。
- 公共电脑或临时测试机器用完后，建议清理本机凭据状态：

```powershell
Remove-Item -Recurse -Force (Join-Path $env:TEMP "chrome_dbg_profile")
Remove-Item -Force ".\results\_auth\sciencedirect_cookies.json"
```

## 公开发布和打包注意事项

如果你 fork 或二次发布本项目，请只发布 Git 仓库中被跟踪的源码，或使用 `make_windows_ui_package.bat` 生成的源码包。不要直接压缩自己的整个工作区，因为本地目录里可能包含机构 Cookie、PDF、运行报告、虚拟环境或浏览器缓存。

发布前建议检查：

```powershell
git status --short
git ls-files | rg "cookie|cookies|results|pdfs|\.pdf$|\.xlsx$|\.csv$|\.venv|dist"
```

正常情况下，`cookie.json`、`cookies.json`、`results\`、`pdfs\`、下载的 PDF、CSV/XLSX 结果表、`.venv\` 和 `dist\` 都不应该被 Git 跟踪。

## 开发和测试

修改 Python 代码前，至少运行：

```powershell
.\.venv\Scripts\python.exe -m compileall paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

真实机构登录、PDF 下载、CAPTCHA 和补充材料下载属于人工 QA，见 [MANUAL_QA.md](MANUAL_QA.md)。

## 来源声明

本项目基于开源项目 [GAO-pooh/paper-scraper](https://github.com/GAO-pooh/paper-scraper/tree/main) 修改并扩展。原项目采用 MIT License，本仓库保留原项目版权声明和许可声明。当前版本保留并增强 ScienceDirect 工作流，增加 Windows 图形界面、DOI 批量解析、Cookie JSON 支持、补充材料下载、OA 资源辅助获取流程和 Codex Skills。

授权和修改声明见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。本仓库后续修改、扩展与新增模块由 `wkguoo` 维护并声明修改部分版权：`Copyright (c) 2026 wkguoo (modifications)`。
