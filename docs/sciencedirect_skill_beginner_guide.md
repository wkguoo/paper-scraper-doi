# ScienceDirect Skill 新手使用说明

这份说明写给第一次使用本工具的学生或课题组成员。目标是：把网页 AI、ChatGPT、Google Scholar 记录或老师给的一段论文推荐文本，交给 Codex 自动识别 DOI 和题名，再通过学校或机构的 ScienceDirect 权限下载 PDF，并生成可检查的报告。

## 1. 这个工具能做什么

`sciencedirect-doi-download` 是一个 Codex skill。你不用打开图形界面，也不用手工整理每一条 DOI。你可以把一整段论文推荐列表粘贴给 Codex，让它调用本仓库的 `sd_institutional_skill.py` 完成这些工作：

1. 从混乱文本中识别 DOI。
2. 对只有题名、没有 DOI 的记录，尝试用公开元数据服务补 DOI、年份、作者、期刊。
3. 去重，避免同一篇论文重复下载。
4. 检查本机是否已经有 ScienceDirect/Elsevier 登录状态。
5. 如果没有登录，弹出浏览器窗口，让你自己完成学校或机构账号登录。
6. 登录后自动取回必要 cookie，不显示、不打印 cookie 内容。
7. 下载有机构权限的 ScienceDirect PDF。
8. 输出报告，告诉你哪些成功、哪些失败、哪些需要人工复核。

它不能做这些事：

1. 不能替你输入学校账号和密码。
2. 不能绕过学校或出版社权限。
3. 不能自动破解 CAPTCHA 或人机验证。
4. 不能使用 Sci-Hub、LibGen 等非合规来源。
5. 不能保证题名-only 的模糊匹配 100% 正确；低置信度结果会进入复核表。

## 2. 第一次使用前检查

确认你满足这些条件：

1. 当前机器是 Windows，且能打开 Codex。
2. 项目仓库已经安装或可定位。推荐让维护者先运行 `install_codex_skills.ps1`，使 Codex 能通过 `PAPER_SCRAPER_DOI_ROOT` 找到仓库。仓库路径通常类似：

```text
D:\Tools\paper-scraper-doi
```

3. 项目里已经有 Python 虚拟环境；如果没有，启动脚本或维护者可以创建：

```text
<仓库路径>\.venv
```

4. 你有学校或机构的 ScienceDirect 权限。
5. 你知道如何在浏览器里完成学校统一认证、CARSI、VPN 或图书馆入口登录。

如果你不确定环境是否正常，可以先让 Codex 帮你试跑：

```text
Use $sciencedirect-doi-download to preflight this paper list with --beginner --preflight:
A critical review of high entropy alloys and related concepts
DOI: 10.1016/j.actamat.2016.08.081
unclear recommendation without enough bibliographic information
```

preflight 是新手和混乱 AI 推荐列表的第一步：它只做输入识别、去重、题名/DOI 候选检查和复核提示，不下载 PDF。`--dry-run` 只用于 ScienceDirect DOI 元数据/PII 解析且不下载 PDF，不作为混乱输入的第一步。

## 3. 最推荐用法：直接让 Codex 调用 skill

在 Codex 里直接输入下面这种请求，然后把论文推荐列表粘贴进去：

```text
Use $sciencedirect-doi-download to download these ScienceDirect papers.
Please save results to D:\Literature\ScienceDirect.

1. A critical review of high entropy alloys and related concepts
2. DOI: 10.1016/j.actamat.2016.08.081
3. A critical review of high entropy alloys and related concepts, Acta Materialia, 2017
4. unclear recommendation about high entropy alloy fatigue without enough bibliographic information
```

Codex 应该做这些事：

1. 定位并进入项目目录。
2. 调用 `sd_institutional_skill.py`。
3. 先整理输入，生成预览表。
4. 解析 DOI 和 ScienceDirect PII。
5. 如果需要登录，弹出浏览器窗口。
6. 等你完成学校或机构登录。
7. 下载 PDF。
8. 最后告诉你输出目录、成功数量、失败数量和失败报告位置。

如果浏览器里出现登录页面，请在浏览器里完成登录，然后回到 Codex 等待程序继续。不要把账号密码发给 Codex。

如果出现 CAPTCHA 或人机验证，请在弹出的浏览器窗口里手动完成验证。程序会等待一段时间后继续，不要频繁重启任务。

## 4. 手动命令用法

如果你想不用自然语言，直接在 PowerShell 里运行，也可以照抄下面的命令。

先进入项目目录。如果安装脚本已经设置了 `PAPER_SCRAPER_DOI_ROOT`，优先使用该环境变量：

```powershell
Set-Location $env:PAPER_SCRAPER_DOI_ROOT
```

如果环境变量还没有生效，也可以手动进入仓库：

```powershell
Set-Location "<仓库路径>"
```

### 4.1 先 preflight，不下载 PDF

适合第一次使用，或你不确定 AI 推荐列表里哪些是有效论文。

```powershell
$papers = @'
A critical review of high entropy alloys and related concepts
DOI: 10.1016/j.actamat.2016.08.081
unclear recommendation without enough bibliographic information
'@

.\.venv\Scripts\python.exe sd_institutional_skill.py --text $papers --out results --run-name beginner_preflight --beginner --preflight --auto-web-search
```

这个命令会生成识别和复核报告，但不会下载 PDF。`--auto-web-search` 是可选项，适合题名-only 或短引用较多的列表；如果列表里已经都是 DOI，可以去掉。

如果你明确只想对已有 DOI 做 ScienceDirect 元数据/PII 解析、且不下载 PDF，可以使用 `--dry-run`。不要把它当作新手混乱输入的第一步。

### 4.2 正式下载 PDF

```powershell
$papers = @'
A critical review of high entropy alloys and related concepts
DOI: 10.1016/j.actamat.2016.08.081
'@

.\.venv\Scripts\python.exe sd_institutional_skill.py --text $papers --out "D:\Literature\ScienceDirect" --login-wait-seconds 600
```

`--login-wait-seconds 600` 表示如果需要登录，程序最多等待 600 秒。第一次登录学校账号时建议给长一点。

如果你已经用 Cookie Editor 合规导出了本机登录后的 `cookies.json`，可以显式指定它：

```powershell
.\.venv\Scripts\python.exe sd_institutional_skill.py --text $papers --out "D:\Literature\ScienceDirect" --cookies "D:\Papers\cookies.json"
```

显式 `--cookies` 会优先于缓存 cookie 或浏览器读取。程序只检查文件是否可用，不会在日志里输出 cookie 值。

### 4.3 弹出文件夹选择窗口

如果你不想手打保存路径：

```powershell
.\.venv\Scripts\python.exe sd_institutional_skill.py --text $papers --choose-out
```

### 4.4 批量处理一个文件

支持 `.xlsx`、`.xlsm`、`.csv`、`.tsv`、`.txt`、`.md`、`.markdown`。

```powershell
.\.venv\Scripts\python.exe sd_institutional_skill.py --input "D:\Papers\papers.xlsx" --out "D:\Literature\ScienceDirect"
```

如果 Excel 里 DOI 列不是自动识别出来的，可以指定列名：

```powershell
.\.venv\Scripts\python.exe sd_institutional_skill.py --input "D:\Papers\papers.xlsx" --doi-column "DOI" --out "D:\Literature\ScienceDirect"
```

如果要指定 Excel 工作表：

```powershell
.\.venv\Scripts\python.exe sd_institutional_skill.py --input "D:\Papers\papers.xlsx" --sheet "Sheet1" --out "D:\Literature\ScienceDirect"
```

### 4.5 批量扫描一个文件夹

```powershell
.\.venv\Scripts\python.exe sd_institutional_skill.py --folder "D:\PapersToDownload" --out "D:\Literature\ScienceDirect"
```

程序会递归扫描支持的文献文件，并自动忽略 `.git`、`.venv`、`results`、`dist`、`pdfs`、`__pycache__` 等目录。

## 5. 输出文件怎么看

每次运行都会在输出目录下创建一个任务文件夹。默认类似：

```text
results\sd_skill_20260621_182439\
```

如果你用了 `--run-name beginner_preflight`，则类似：

```text
results\beginner_preflight\
```

preflight 输出重点看这些文件：

| 文件或目录 | 用途 |
| --- | --- |
| `doi_intake_preview.csv` | 输入预览表。看每一行来自哪里、识别到什么 DOI、是否重复、是否需要人工复核。 |
| `merged_doi_input.csv` | 后续正式解析可使用的 DOI 表。重复 DOI 只保留一次。 |
| `doi_batch_failed.csv` | preflight 发现的空 DOI、重复项、无效项或需要复核的记录。 |
| `00_给研究生查看\README_先看我.txt` | 给学生的阅读说明，说明索引、相对路径和失败处理顺序。 |
| `00_给研究生查看\paper_index.csv` / `paper_index.xlsx` | 研究生查看入口。preflight 阶段会标出哪些记录尚未请求下载。 |
| `00_给研究生查看\失败项_下一步处理.csv` | 把 `needs_review`、重复、无 DOI 等问题整理成可操作类别。 |
| `run_summary.txt` | 本次任务摘要。包括成功数、失败数、下一步建议。 |
| `run_summary.json` | 给 UI 或脚本读取的机器可读摘要，包含研究生查看入口路径。 |

正式解析和 PDF 下载才会额外关注这些输出：

| 文件或目录 | 生成条件和用途 |
| --- | --- |
| `doi_batch_resolved.xlsx` | 正式解析时生成，保存成功解析到 ScienceDirect PII 的论文。 |
| `pdf_download_report.csv` | 启用 PDF 下载时生成，逐篇记录成功、失败、跳过原因和文件名。 |
| `pdfs\` | 下载成功的 PDF 文件。 |
| `library_index.csv` | 与 `00_给研究生查看\paper_index.csv` 同内容，放在任务根目录，便于脚本继续处理。 |
| `supplement_download_report.csv` | 只有启用 PDF 下载且启用补充材料下载时生成，逐个记录附件成功、失败、跳过或未发现原因。 |
| `supplements\` | 只有启用 PDF 下载且启用补充材料下载时生成，按文章文件名前缀建立子目录保存对应补充材料。 |

补充材料状态 `not_found` 表示页面上没有检测到可下载的 supplement 链接，不代表正文 PDF 下载失败。

最重要的是这些入口：

1. `00_给研究生查看\paper_index.xlsx`：给学生优先打开的总索引，正文 PDF 和补充材料都用相对路径指向原文件，不复制文件。
2. `00_给研究生查看\失败项_下一步处理.csv`：失败后先看这里，不要连续大批量重跑。
3. `doi_intake_preview.csv`：检查输入识别是否正确。
4. `pdf_download_report.csv`：检查 PDF 是否真的下载成功。
5. `supplement_download_report.csv`：如果正式下载时启用了附件，检查补充材料是否找到并下载成功。

## 6. `doi_intake_preview.csv` 里的状态是什么意思

常见状态如下：

| 状态 | 含义 | 你需要做什么 |
| --- | --- | --- |
| `valid` | 已识别为有效 DOI，进入后续解析和下载。 | 一般不用处理。 |
| `duplicate` | 重复 DOI 或题名解析到同一 DOI。 | 一般不用处理，程序只下载一次。 |
| `needs_review` | 信息不足、题名匹配置信度低或有多个候选。 | 人工检查题名，必要时补 DOI 后重跑。 |
| `invalid` | 文本里像 DOI 但格式不合法。 | 检查原始输入是否复制错。 |
| `empty` | 空行或没有可用信息。 | 一般不用处理。 |

如果 `needs_review` 很多，通常说明输入太模糊。建议让 AI 推荐文献时要求输出“题名、年份、期刊、DOI”。

## 7. 常见问题和处理方法

### 7.1 没有弹出登录窗口

可能原因：

1. 已经有可用 cookie，程序直接继续。
2. 本机浏览器调试端口已经打开。
3. Edge/Chrome/Chromium 启动失败。

处理方法：

1. 先看 Codex 最后的错误信息。
2. 如果提示找不到浏览器，优先安装 Microsoft Edge；Chrome/Chromium 仍可作为后备。
3. 如果浏览器装在特殊位置，先设置：

```powershell
$env:PAPER_SCRAPER_BROWSER_EXE = "D:\Path\To\msedge.exe"
```

再重新运行下载命令。

### 7.2 已登录，但下载失败

先打开 `00_给研究生查看\失败项_下一步处理.csv` 和 `pdf_download_report.csv` 看失败原因。常见原因：

1. 学校没有订阅该论文全文。
2. ScienceDirect 返回 403 或限速。
3. 出现 CAPTCHA，需要人工验证。
4. 该 DOI 不是 ScienceDirect/Elsevier 文献。
5. DOI 能解析，但 PDF 地址不可访问。

不要连续反复重跑大量任务。先用 1 到 2 篇论文测试登录和权限是否正常。

### 7.3 出现 CAPTCHA

这是正常的人工验证，不要尝试绕过。切换到弹出的浏览器窗口，按页面要求完成验证，然后等待程序继续。

### 7.4 题名-only 没有下载

如果只有题名，没有 DOI，程序会尝试用 Crossref/OpenAlex 解析。若匹配不可靠，会写入 `needs_review`，不会自动下载。

处理方法：

1. 在 `doi_intake_preview.csv` 找到 `needs_review` 行。
2. 人工去 Google Scholar、Crossref、出版社页面或学校图书馆确认 DOI。
3. 把确认后的 DOI 加回输入列表再运行。

### 7.5 非 ScienceDirect 文献怎么办

这个 skill 是机构权限版 ScienceDirect 下载流程。非 ScienceDirect 文献不会伪装成功，通常会进入失败报告。

如果你想找开放获取 PDF，可以改用本项目的 `paper_skill.py` 合规 OA 流程。它只下载明确开放获取的 PDF，不使用机构 cookie。

### 7.6 `run_summary.txt` 中文乱码

这是 PowerShell 或编辑器编码显示问题。优先看 CSV/XLSX 报告，或用支持 UTF-8 的编辑器打开 `run_summary.txt`。

### 7.7 PDF 文件名为什么很长

默认文件名会尽量包含：

```text
年份_第一作者_短题名_DOI哈希.pdf
```

这样做是为了避免同名论文覆盖，也方便以后追溯 DOI。

## 8. 建议的课题组使用习惯

1. 第一次拿到 AI 推荐列表，先跑 `--beginner --preflight`，题名-only 或短引用很多时可加 `--auto-web-search`。
2. 先检查 `doi_intake_preview.csv`，确认识别结果。
3. 对 `needs_review` 的论文，人工补 DOI。
4. 正式下载时指定清楚输出目录，例如：

```powershell
--out "D:\Literature\ScienceDirect"
```

5. 下载后检查 `pdf_download_report.csv`，不要只看 `pdfs` 文件夹。
6. 把 `00_给研究生查看` 作为交付给学生的入口；它不会复制 PDF，而是用相对路径指向 `pdfs\` 和 `supplements\`。
7. 把失败报告留着，方便后续手工补下载或请老师判断是否有必要找馆际互借。
8. 不要把 `results\_auth\sciencedirect_cookies.json` 或导出的 `cookies.json` 发给别人。
9. 如果是在公共电脑或临时测试机器上使用，测试后可以清理本机凭据状态：

```powershell
Remove-Item -Recurse -Force (Join-Path $env:TEMP "chrome_dbg_profile")
Remove-Item -Force ".\results\_auth\sciencedirect_cookies.json"
```

## 9. 安全和合规要求

必须遵守：

1. 不要把 cookie 文件、`results\_auth\`、账号截图发到群里或上传到 GitHub。
2. 不要把学校账号密码发给 Codex 或任何脚本。
3. 不要使用 Sci-Hub、LibGen 或其他侵权来源。
4. 不要试图绕过 CAPTCHA、403、付费墙或机构权限边界。
5. 遇到无权限论文，让它进入失败报告，不要伪装为下载成功。
6. 不要分享 `%TEMP%\chrome_dbg_profile`；它是临时调试浏览器 profile，属于本机凭据状态。

这个工具的定位是：在你已经有合法机构权限的前提下，减少 DOI 整理、登录状态取回、批量下载和报告归档的重复劳动。

## 10. 给学生的最短使用模板

把下面这段复制到 Codex，然后把论文列表替换成自己的：

```text
Use $sciencedirect-doi-download to download these ScienceDirect papers.
Save results to D:\Literature\ScienceDirect.
If anything is uncertain, put it in needs_review and report it at the end.

<在这里粘贴 AI 推荐的论文列表，可以包含 DOI、题名、年份、期刊，也可以有少量噪声文本>
```

如果只是预检查，不下载 PDF，把第一句改成：

```text
Use $sciencedirect-doi-download to preflight these paper recommendations with --beginner --preflight.
```
