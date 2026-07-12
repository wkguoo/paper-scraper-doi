# 中文说明

[English](README.md) | 中文说明

# 论文下载助手：统一批量下载与 Zotero 回退

这是一个面向 Windows 的论文下载辅助工具。推荐环境是 Windows 10/11 + Python 3.10 或 3.11。它可以配合 Codex Skills、图形界面或命令行，把 DOI 表格、AI 推荐文献列表、复制来的论文文本整理成可检查的报告，并下载 PDF。

## 推荐入口（新任务只用这些）

| 使用场景 | 推荐入口 | 说明 |
| --- | --- | --- |
| 命令行批量下载 | `paper_batch.py` | 唯一推荐 CLI：`start` →（必要时）`resume` → `zotero` |
| 图形界面 | `start_paper_scraper_ui.bat` → **统一批次（推荐）** | 同一套 `paper_batch` 流程 |
| 自然语言 / Codex | `$paper-download` | 安装脚本只安装这一个 skill |

```powershell
.\.venv\Scripts\python.exe paper_batch.py start --input "papers.xlsx" --out "results" --email "you@example.com"
```

**不要**把 `paper_skill.py`、`sd_institutional_skill.py`、`sd_scraper.py`、`sd_scraper_en.py` 当作新任务的首选入口；它们不走统一批次状态，失败项也进不了同一份 Zotero 回退清单。

## 兼容 / 高级入口（非默认）

| 入口 | 角色 |
| --- | --- |
| UI 的「DOI 批量下载 / 文献检索 / OA 资源辅助获取」 | 旧版专用路径，仅兼容维护 |
| `sd_scraper.py` / `sd_scraper_en.py` | 旧版 ScienceDirect 中英文 CLI |
| `sd_institutional_skill.py` / `paper_skill.py` / `institutional_paper_skill.py` | 统一流程内部适配器 |
| `sciencedirect-doi-download` / `legal-oa-paper-download` skill | 内部说明；默认不安装 |

## 这个工具能做什么

- 从 Excel、CSV、TXT、Markdown 或直接粘贴文本里识别 DOI。
- 对混乱的 AI 推荐列表先做 preflight，标出有效 DOI、重复项和需要人工复核的记录。
- 通过你的机构权限下载 ScienceDirect PDF，并生成下载报告。
- 默认尝试下载 ScienceDirect 补充材料，并把附件状态写入报告。
- 对非 ScienceDirect 或混合来源列表，使用公开元数据服务查找公开开放获取 PDF 候选资源。
- 给 Codex 安装唯一的 `paper-download` Skill，让你可以直接用自然语言发任务。

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
Install skill: paper-download -> ...
Set user environment variable PAPER_SCRAPER_DOI_ROOT=<仓库路径>
Dry run only; no files or environment variables were changed.
```

### 3. 正式安装或刷新 Codex Skills

```powershell
powershell -ExecutionPolicy Bypass -File .\install_codex_skills.ps1
```

安装脚本会做两件事：

- 把 `skills\paper-download` 复制到 Codex 的 skills 目录。
- 设置用户环境变量 `PAPER_SCRAPER_DOI_ROOT=<仓库路径>`，让 Codex 能找到本仓库。

安装后请重启 Codex 或重新打开终端，让新的环境变量生效。

### 4. 验证统一入口可用

```powershell
.\.venv\Scripts\python.exe paper_batch.py --help
.\.venv\Scripts\python.exe paper_batch.py start --help
```

如果能显示 `start`、`resume`、`zotero` 和 `finalize`，说明统一入口可用。

## 推荐用法：直接让 Codex 调用 Skill

安装后，在 Codex 里使用唯一入口 `paper-download`。它会自动选择公开 OA、机构访问和 Zotero 回退路径。

### 示例 1：ScienceDirect 机构权限下载

把下面这段复制到 Codex，再替换成自己的论文列表：

```text
Use $paper-download to download these ScienceDirect papers.
Save results to D:\Literature\ScienceDirect.
If anything is uncertain, put it in needs_review and report it at the end.

DOI: 10.1016/j.actamat.2016.08.081
DOI: 10.1016/j.scriptamat.2023.115000
```

第一次运行时，先尝试使用 Codex 内置浏览器完成需要的登录或验证；如果内置浏览器不可用，项目才启动外部浏览器，并按 Google Chrome → Edge Stable/Beta/Dev/Canary → Playwright Chromium 的顺序选择。项目 Python 下载器不能直接接管 Codex 内置浏览器的登录会话；请你自己完成学校、机构、VPN、CARSI 或图书馆登录，不要把账号密码发给 Codex。

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

## 统一批处理：项目优先，Zotero 仅处理失败项

当 DOI 与题名混合列表需要先走项目已有流程、再把剩余失败项交给 Zotero 9 时，使用本地文件桥接。打开 Zotero 并启用“文献下载桥接”插件；正常路径不再使用直接 Zotero MCP 写入。

```powershell
.\.venv\Scripts\python.exe paper_batch.py start --input "papers.xlsx" --out "results"
```

默认路径：合法 OA → 机构访问 → **失败项全部写入 `zotero_fallback.csv`（不再默认走 `resume`）**，且 `start` 结束后**自动排队** Zotero 本地桥接。请保持 Zotero 打开并启用桥接插件。退出码 `3` 表示已排队等待确认；在 Zotero 中接受一次批次确认后，只重跑：

```powershell
.\.venv\Scripts\python.exe paper_batch.py zotero --run-dir "<run-dir>"
```

可选：`start` 加 `--wait-seconds N` 同进程等待；`--no-auto-zotero` 改为稍后手动排队；`--enable-manual-retry` 恢复旧的一次登录/验证码门禁，此时仅当 `manual_retry.csv` 有数据时运行一次：

```powershell
.\.venv\Scripts\python.exe paper_batch.py resume --run-dir "<run-dir>"
```

桥接队列固定在 `%LOCALAPPDATA%\PaperScraperDOI\zotero-bridge\v1`。多个分块仍是 one confirmation per batch。

输出目录为 `results\paper_batch_YYYYMMDD_HHMMSS\`：最终 PDF 在 `pdfs\`，报告在 `reports\`。流程遵守 do not overwrite：不移动或覆盖 Zotero 原附件、原始输入、已有结果或已有 PDF。当前只完成源码和离线测试；先验收 Zotero test profile，do not install to the main profile yet。未经明确批准不生成 XPI。详细步骤见 [Zotero 9 本地桥接新手指南](docs/zotero_bridge_beginner_guide.md)。

## 图形界面（推荐页：统一批次）

双击：

```text
start_paper_scraper_ui.bat
```

首次启动会自动创建 `.venv` 并安装依赖。打开后**默认在「统一批次（推荐）」页**；其它页签标明「兼容」，仅在你明确需要旧版 ScienceDirect 专用或 OA 专用流程时使用。

机构 PDF 可用 Cookie Editor 导出的 `cookies.json`。更详细说明见 [WINDOWS_UI_README.md](WINDOWS_UI_README.md)。

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
| 没有弹出登录窗口 | 可能已经有可用 Cookie；也可能浏览器路径异常。先看日志，如果提示找不到浏览器，可优先安装 Edge，或设置 `PAPER_SCRAPER_BROWSER_EXE`。 |
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
