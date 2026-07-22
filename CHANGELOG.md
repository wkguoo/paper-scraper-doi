# CHANGELOG

## 2026-07-21 — MDPI gold-OA download (Akamai interstitial)

- **OA downloader**: for MDPI (`mdpi.com` / `10.3390/`), use `curl_cffi` Chrome TLS impersonation, browser-like `Referer`, URL variants (strip `version=`, article `/pdf` paths), and solve Akamai interstitial (`bm-verify` + trivial JS `pow`) before re-fetching the PDF.
- **Institutional**: add `MdpiAdapter` so MDPI is no longer `unsupported_publisher`; browser capture candidates include `/doi/pdf/{doi}` and journal-path `/pdf`.
- Live check: three previously 403/no_pdf DOIs (`ma15051696`, `met12071089`, `met14090991`) now download as valid PDFs via OA client.
- Tests: `MetadataAndPdfTests.test_mdpi_url_variants_and_referer`, `test_mdpi_adapter_matches_and_candidates`.

## 2026-07-18 — A1/A2/A3 + B4/B5 + C6 delivery ladder

- **A1** Merge-safe `结果/` publish: manual/external PDFs survive republish (content-hash dedupe); listed as `外部补入`.
- **A2** Shared `run_post_download_ladder` on `start` and `retry-failed` (limited OA → zotero_fallback → delivery). Auto Zotero also on `retry-failed` / `recover-oa` (disable with `--no-auto-zotero`).
- **A3** New CLI `paper_batch.py refresh-delivery --run-dir …` renames `结果/` PDFs, maps failed DOIs, rewrites `下载清单.csv` + `重命名对照表.csv`.
- **B4** DOI extract keeps balanced `()` and strips markdown `**` (`doi_batch_utils.clean_doi` / `extract_doi_from_text`).
- **B5** Delivery filename sanitize strips HTML/MathML and tag residues (`iin-situ-i`, `subN-sub`).
- **C6** IUCr (`10.1107`) short try: circuit trip after 1 browser fail → OA → Zotero (`--no-iucr-short-try` to disable).
- Tests: `tests/test_batch_optimizations.py` (A1/A3/B5/C6), `tests/test_doi_batch_utils.py` (B4).

## 2026-07-16 — Less-manual batch optimizations (Elsevier unchanged)

- Prefer DOI-only intake: drop Markdown section/note rows by default; optional title inheritance for following DOI lines.
- DOI preflight **on by default** (`--no-doi-preflight` to skip); fail-open on network errors; severe title/DOI mismatch → `metadata_uncertain`.
- Failure routing: only DOI-bearing bridge-eligible failures enter `zotero_fallback.csv` (not `metadata_uncertain` / no-DOI noise).
- Non-Elsevier institutional: skip browser when no adapters match; per-adapter circuit breaker (default 3 consecutive failures); reuse debug browser session.
- `retry-failed` defaults to network/capture failures only (`--retry-all-failed` for broad mode).
- Bounded OA recovery only for OA-signal rows; `start` can auto-run recovery before Zotero.
- Zotero bridge plugin **0.2.0**: auto-confirm by default (`extensions.zoteroPaperDownloadBridge.autoConfirm=false` to restore modal).
- CLI defaults: auto-Zotero on, `--wait-seconds 600` (use `--no-auto-zotero` / `0` to opt out).
- ScienceDirect/Elsevier download path intentionally **not** modified.
- Tests: `Ran 408 ... OK (skipped=2)`; Node bridge runtime 52 pass.

## v0.2.0 — Zotero 9 bridge and unified batch workflow

Release date: 2026-07-12

- 将 `paper_batch.py` 确立为 DOI、题名、CSV/XLSX/Markdown 文献任务的统一入口。
- 完成 OA → 机构访问 → 人工重试 → Zotero 回退的可恢复批次流程。
- 增加 Zotero 9 本地桥接、批次队列、分块处理、结果校验和安全 PDF 交付。
- 加强 Windows 浏览器选择、路径安全、并发 PDF 发布和原始文件不覆盖保护。
- 补充完整的离线单元测试、CI 稳定性修复、Windows 使用文档和 Zotero 新手指南。
- 本 release 提供源码，不包含 exe 或自动生成的 Windows UI 压缩包。

## 2026-07-12 22:36:37 +08:00

- 本次任务目标：修复 GitHub Actions Windows runner `windows-tests` 中由短路径/长路径差异和相对 PDF symlink 检查顺序导致的 5 个失败用例。
- 新增、修改或删除的文件：
  - 修改 `paper_automation/batch_workflow.py`
  - 修改 `paper_automation/batch_stages.py`
  - 修改 `paper_batch.py`
  - 修改 `CHANGELOG.md`
- 具体修改内容：
  - PDF 复制内部继续使用规范路径，但返回调用者传入的路径写法，避免 `RUNNER~1` 与 `runneradmin` 在跨进程测试中被误判为不同文件。
  - 相对 PDF 路径在 `resolve()` 前先检查最终路径是否为 symlink。
  - CLI 恢复、Zotero 和 finalize 命令保留用户传入的 `--run-dir` 路径写法。
- 修改原因：Windows runner 会在临时目录中混用 8.3 短路径和长路径；路径字符串不同但文件实际相同。先 resolve 再检查 symlink 还会隐藏相对链接的安全信号。
- 生成的输出文件：未生成 PDF、下载结果、原始数据或 Windows UI 打包产物；测试仅在系统临时目录生成临时文件。
- 如何检查是否成功：5 个失败用例定向测试通过；`compileall` 通过；完整测试为 `Ran 386 tests ... OK (skipped=2)`；`git diff --check` 通过。
- 注意事项或潜在风险：未修改原始实验/文献数据，未修改 Git 历史，未自动打包；提交后仍需在 GitHub Actions 重新运行 `windows-tests` 确认远端 runner 结果。

## 2026-06-21 20:41:21

- 本次任务目标：修复所有文件输入中的 DOI 识别、去重和误补 DOI 问题。
- 新增、修改或删除的文件：
  - 修改 `paper_automation/parser.py`
  - 修改 `paper_automation/deduplicator.py`
  - 修改 `sd_institutional_skill.py`
  - 修改 `tests/test_paper_automation.py`
  - 修改 `tests/test_sd_institutional_skill.py`
  - 新增 `CHANGELOG.md`
- 具体修改内容：
  - 统一混合文本解析中的 DOI 正则，允许圆括号，完整保留老 Elsevier DOI。
  - 含 DOI 的记录只按 DOI 精确去重，不再按题名相似度误判重复。
  - 文件输入默认只提取显式 DOI，不再对无 DOI 的标题、备注或说明段落自动补 DOI。
  - 新增 `--resolve-title-only` 参数，只有显式开启时文件输入才会尝试 title-only 元数据补全。
  - 增加回归测试，覆盖老 Elsevier DOI、相似题名不同 DOI、文件输入误补 DOI、表格无 DOI 列但单元格含 DOI 等场景。
- 修改原因：
  - Markdown 文献清单中约 50 篇显式 DOI 论文此前只进入 38 条，原因是题名相似误去重、老 DOI 被括号截断、无 DOI 备注行被错误补全为外部 DOI。
- 如何运行：
  - 语法检查：`.\.venv\Scripts\python.exe -m py_compile doi_batch_utils.py sd_institutional_skill.py paper_automation\parser.py paper_automation\deduplicator.py`
  - 单元测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  - 当前 Markdown dry-run：`.\.venv\Scripts\python.exe sd_institutional_skill.py --input "D:\桌面\文献下载 - 副本\acta_scripta_ti_synchrotron_xrd_literature_list.md" --out "D:\桌面\文献下载 - 副本\results" --run-name doi_count_check_after_fix --dry-run`
- 生成的输出文件：
  - `D:\桌面\文献下载 - 副本\results\doi_count_check_after_fix\doi_intake_preview.csv`
  - `D:\桌面\文献下载 - 副本\results\doi_count_check_after_fix\merged_doi_input.csv`
  - `D:\桌面\文献下载 - 副本\results\doi_count_check_after_fix\doi_batch_resolved.xlsx`
  - `D:\桌面\文献下载 - 副本\results\doi_count_check_after_fix\doi_batch_failed.csv`
  - `D:\桌面\文献下载 - 副本\results\doi_count_check_after_fix\pdf_download_report.csv`
  - `D:\桌面\文献下载 - 副本\results\doi_count_check_after_fix\run_summary.txt`
- 如何检查是否成功：
  - 当前 Markdown dry-run 显示 `有效唯一 DOI: 50`。
  - `doi_batch_failed.csv` 共 0 条。
  - 老 DOI 如 `10.1016/s1359-6454(00)00218-4`、`10.1016/s1359-6454(02)00134-9`、`10.1016/s1359-6454(02)00050-2` 完整保留。
  - 不再出现误补 DOI `10.4028/www.scientific.net/msf.849.219`。
  - 完整测试结果为 65 项全部通过。
- 注意事项或潜在风险：
  - 文件输入默认不再自动补全 title-only 文献；如果确实需要文件中的无 DOI 题名补 DOI，需要显式加 `--resolve-title-only`。
  - 本次没有执行正式 PDF 下载，没有重新打包项目。

## 2026-06-21 20:54:12

- 本次任务目标：合并两个论文下载 skill 的调用入口，新增统一入口 `paper-download`。
- 新增、修改或删除的文件：
  - 新增 `skills/paper-download/SKILL.md`
  - 修改 `README.md`
  - 修改 `README_zh.md`
  - 修改 `tests/test_skills_packaging.py`
  - 修改 `CHANGELOG.md`
- 具体修改内容：
  - 新增 `paper-download` skill，按用户意图自动路由到 ScienceDirect 机构权限下载流程或 OA 下载流程。
  - 保留 `sciencedirect-doi-download` 和 `legal-oa-paper-download` 两个旧 skill，不删除、不破坏已有调用。
  - 在 README 和中文 README 中说明推荐使用 `$paper-download`，旧入口作为兼容入口继续可用。
  - 在 skill 打包测试中增加 `paper-download` frontmatter 检查，确保新增入口随 `skills/` 目录一起安装。
- 修改原因：
  - 原来 ScienceDirect 机构下载和 OA 下载是两个独立 skill，用户需要自行选择；新增统一入口可以减少选择成本。
- 如何运行：
  - 安装 skill：`powershell -ExecutionPolicy Bypass -File install_codex_skills.ps1`
  - 使用统一入口：`Use $paper-download to download these papers: ...`
  - ScienceDirect 机构权限流程仍会调用 `sd_institutional_skill.py`。
- 生成的输出文件：
  - 本次只新增和修改项目文件，没有执行论文下载，也没有生成 PDF 或批量下载结果目录。
- 如何检查是否成功：
  - 静态测试：`.\.venv\Scripts\python.exe -m unittest tests.test_skills_packaging -v`
  - 全量测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  - skill 校验：`python C:\Users\wkguopro\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills\paper-download`
  - 安装预览：`powershell -ExecutionPolicy Bypass -File install_codex_skills.ps1 -DryRun`
- 注意事项或潜在风险：
  - 本次不改变 PDF 下载核心逻辑，只新增统一 skill 入口和文档说明。
  - 安装到 `C:\Users\wkguopro\.codex\skills` 后，当前 Codex 会话可能需要重启或新开会话才能在技能列表中显示 `$paper-download`。
  - 本次没有重新打包 Windows UI。

## 2026-06-22 00:10:32

- 本次任务目标：为 UI 新增 OA 下载模式，并修复 ScienceDirect PDF 文件名元数据缺失导致的 `unknown-year_Unknown_S...pdf` 问题。
- 新增、修改或删除的文件：
  - 修改 `paper_scraper_ui.py`
  - 修改 `sd_scraper.py`
  - 修改 `tests/test_doi_batch_utils.py`
  - 修改 `tests/test_sd_institutional_skill.py`
  - 修改 `README_zh.md`
  - 修改 `WINDOWS_UI_README.md`
  - 修改 `CHANGELOG.md`
- 具体修改内容：
  - UI 新增”OA 下载”页，支持选择 `.txt/.md/.markdown/.csv` 文件或直接粘贴论文列表，调用 `paper_skill.py`。
  - OA 模式支持输出目录、邮箱、dry-run、覆盖已存在 PDF、limit 参数；不使用 Cookie JSON 或 Chrome/Edge 机构登录。
  - ScienceDirect DOI 解析时从页面 HTML 的 `citation_title`、`citation_author`、`citation_publication_date`、`citation_journal_title` 补全标题、作者、年份和期刊。
  - PDF 文件名生成改为优先使用 `年份_第一作者_标题_短hash.pdf`；没有元数据时用 DOI/PII 兜底，不再优先生成 `unknown-year_Unknown_S...pdf`。
  - 增加 UI 命令构造测试、ScienceDirect 元数据补全测试和无元数据文件名兜底测试。
- 修改原因：
  - Skill 已有 ScienceDirect 与 OA 两条下载路径，但 UI 之前只有 ScienceDirect 入口。
  - 部分 DOI 批量下载结果缺少标题、作者、年份，导致 PDF 文件名可读性差，不便于文献整理。
- 如何运行：
  - 启动 UI：`.\start_paper_scraper_ui.bat`
  - ScienceDirect：打开“DOI 批量下载”页，选择 DOI 表和 Cookie JSON，勾选“检索后下载 PDF”，点击“开始运行”。
  - OA：打开“OA 下载”页，选择文件或粘贴论文列表，选择输出目录，按需勾选 dry-run，点击“开始运行”。
  - 语法检查：`.\.venv\Scripts\python.exe -m py_compile sd_scraper.py paper_scraper_ui.py sd_institutional_skill.py paper_skill.py`
  - 单元测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests -v`
- 生成的输出文件：
  - 本次没有正式下载论文，没有生成新的 PDF 结果目录。
  - ScienceDirect 运行时仍生成 `doi_batch_resolved.xlsx`、`doi_batch_failed.csv`、`pdf_download_report.csv`、`run_summary.txt` 和 `pdfs\`。
  - OA 运行时生成 `pdfs\`、`metadata\manifest.csv`、`metadata\manifest.json`、`failed\duplicates.csv` 等。
- 如何检查是否成功：
  - UI 命令预览中，ScienceDirect 页仍显示 `sd_scraper.py` 命令。
  - UI 命令预览中，OA 页显示 `paper_skill.py --input ... --out ...` 或粘贴内容对应的临时输入文件。
  - ScienceDirect 下载出的 PDF 文件名应包含年份、第一作者和标题；缺少元数据时至少使用 DOI/PII 兜底，不再出现 `unknown-year_Unknown_S...` 作为优先形式。
  - 新增和完整单元测试应全部通过。
- 注意事项或潜在风险：

  - OA 模式查找开放获取 PDF；无法下载的论文会写入 manifest。
  - 本次没有重新打包 Windows UI。

## 2026-06-22 11:52:30

- 本次任务目标：增强无 DOI 文献的 DOI 自动匹配规则，避免把备注、说明、分区标题等误当作文献题名并错误补 DOI。
- 新增、修改或删除的文件：
  - 修改 `paper_automation/parser.py`
  - 修改 `sd_institutional_skill.py`
  - 修改 `tests/test_paper_automation.py`
  - 修改 `tests/test_sd_institutional_skill.py`
  - 修改 `CHANGELOG.md`
- 具体修改内容：
  - 新增无 DOI 文本的文献信号判断：只有“题名 + 至少一个额外文献信号”才进入 Crossref/OpenAlex 自动匹配。
  - 额外文献信号包括年份、作者格式、常见期刊名、卷期页码等。
  - 备注、说明、`P8:` 类标签说明、`可能相关/边界/排除参考`、`unclear recommendation` 等文本进入 `needs_review`，不自动补 DOI。
  - 支持相邻两行合并判断：标题单独一行、期刊/年份在下一行时，可以作为一条有效 title-only 候选。
  - 表格启用 `--resolve-title-only` 时，同一行只有标题而缺少作者/期刊/年份等上下文时不自动匹配 DOI；标题列中明显是备注时标记为 `not_probable_title`。
- 修改原因：
  - 无 DOI 文本只凭标题或备注进行公开元数据匹配时，容易把说明文字误配成外部 DOI，导致下载列表污染。
- 如何运行：
  - 语法检查：`.\.venv\Scripts\python.exe -m py_compile paper_automation\parser.py sd_institutional_skill.py paper_skill.py`
  - 定向测试：`.\.venv\Scripts\python.exe -m unittest tests.test_paper_automation -v`
  - 定向测试：`.\.venv\Scripts\python.exe -m unittest tests.test_sd_institutional_skill -v`
  - 完整测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests -v`
- 生成的输出文件：
  - 本次没有正式下载论文，没有生成新的 PDF 或批量下载结果目录。
  - 测试仅在系统临时目录生成临时 CSV、manifest 和报告文件。
- 如何检查是否成功：
  - 只有标题的无 DOI 文本应显示为 `needs_review`，原因包含 `insufficient_bibliographic_context`。
  - 备注/说明/分区标题应显示为 `needs_review`，原因包含 `not_probable_title`。
  - `标题 + 期刊/年份/作者` 的无 DOI 文献仍可进入自动匹配。
  - 显式 DOI 行继续正常识别，不受新规则影响。
- 注意事项或潜在风险：
  - 新规则更保守，部分只有标题的真实文献不会自动补 DOI，需要补充作者、期刊或年份后再匹配。
  - 本次不改变 ScienceDirect PDF 下载、Cookie、CDP/DevTools 或 UI 打包流程。

## 2026-07-09 15:44:09

- 本次任务目标：
  - 对项目做公开发布前的稳妥硬化：完善文档和发布前准备，补充来源声明、License/NOTICE、CI 和发布安全说明，并修复大批量任务前期长时间无反馈的问题。
- 新增、修改或删除的文件：
  - 新增 `NOTICE`
  - 新增 `.github/workflows/tests.yml`
  - 修改 `LICENSE`
  - 修改 `README.md`
  - 修改 `WINDOWS_UI_README.md`
  - 修改 `docs/sciencedirect_skill_beginner_guide.md`
  - 修改 `docs/superpowers/plans/2026-06-17-paper-skill.md`
  - 修改 `make_windows_ui_package.bat`
  - 修改 `paper_scraper_ui.py`
  - 修改 `sd_institutional_skill.py`
  - 修改 `sd_scraper.py`
  - 修改 `sd_scraper_en.py`
  - 修改 `skills/paper-download/SKILL.md`
  - 修改 `skills/sciencedirect-doi-download/SKILL.md`
  - 修改 `skills/sciencedirect-doi-download/references/beginner-workflow.md`
  - 修改 `tests/test_doi_batch_utils.py`
  - 修改 `tests/test_sd_institutional_skill.py`
  - 修改 `tests/test_skills_packaging.py`
  - 修改 `windows_paths.py`
  - 修改 `CHANGELOG.md`
- 具体修改内容：
  - 将公开文档、帮助文本和源码注释中的文档措辞改为中性表述，强调使用用户已授权的真实浏览器会话、Cookie 和 CDP 捕获有权限访问的 PDF。
  - 保留并强化使用说明：权限、不自动完成 CAPTCHA，不下载无访问权限的 PDF。
  - 新增 `NOTICE`，声明本项目基于 `GAO-pooh/paper-scraper` 修改，原项目为 MIT License，并列出本项目的主要新增能力。
  - 在 `LICENSE` 中补充 `Modifications Copyright (c) 2026 wkguoo`。
  - 在 README 和 Windows UI 文档中补充公开发布/打包注意事项，提醒不要发布 `cookie.json`、`results/`、PDF、虚拟环境、浏览器缓存和本地构建产物。
  - 新增 Windows + Python 3.11 的 GitHub Actions 测试工作流，执行语法编译和完整单元测试。
  - 调整 `sd_institutional_skill.py` 的输入整理流程：先本地识别 DOI/题名、去重并写出 `doi_intake_preview.csv` 和 `merged_doi_input.csv`，再进入联网元数据增强；关键日志全部及时刷新。
  - 调整 `--beginner --preflight` 行为：只做本地识别、去重和复核报告，不默认联网补 DOI 元数据。
  - 修复 Windows 浏览器 profile 探测时部分 Edge 路径权限异常导致测试或运行中断的问题。
  - 更新 skill 文档和 UI 智能预检命令，避免 beginner preflight 默认触发公开元数据搜索。
  - 增加回归测试，覆盖 preflight 不调用 `MetadataResolver.resolve_one`、预览文件先于联网元数据解析写出、公开风险短语扫描、CI 文件存在和打包脚本包含 `NOTICE`。
- 修改原因：
  - 项目准备公开发布，需要让 README、skill、源码注释和打包说明更清楚地表达使用方式，让用户更清楚工具的使用方式。
  - 大批量文献输入时，如果先联网解析再写预览，会让用户长时间看不到输出，难以判断程序是否卡住。
  - 公开仓库需要基本的 License/NOTICE、CI 和敏感文件发布提醒，便于其他用户安全安装和复现。
- 如何运行：
  - 语法和编译检查：`.\.venv\Scripts\python.exe -m compileall paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation`
  - 完整单元测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  - 文案安全扫描：运行 `tests/test_skills_packaging.py` 中的公开风险措辞检查，或按该测试中的拆分关键词规则执行 `rg` 扫描。
  - 敏感产物跟踪检查：`git ls-files | rg "cookie|cookies|results|pdfs|\.pdf$|\.xlsx$|\.csv$|\.venv|dist"`
  - Skill 安装预检查：`powershell -ExecutionPolicy Bypass -File install_codex_skills.ps1 -DryRun`
- 生成的输出文件：
  - 新增仓库文件 `NOTICE`
  - 新增 CI 文件 `.github/workflows/tests.yml`
  - 测试过程中仅在系统临时目录生成测试日志和临时测试文件，没有生成新的论文 PDF、下载结果目录或 Windows UI 打包产物。
- 如何检查是否成功：
  - `python -m compileall ...` 应返回退出码 0。
  - `python -m unittest discover -s tests -v` 应显示全部测试通过。
  - 文案安全扫描不应命中把工具能力描述为规避检测的短语。
  - `git ls-files` 敏感产物扫描不应出现真实 `cookie.json`、PDF、`results/`、`.venv/`、`dist/` 等运行产物。
  - 运行 `--beginner --preflight` 时，应能先看到本地预览和去重报告，不默认进行联网元数据补全。
- 注意事项或潜在风险：
  - 本次不改变 ScienceDirect/CDP/机构权限下载核心流程，也不改变 Cookie、浏览器登录。
  - 本次没有重新打包 Windows UI；如需发布压缩包，应后续显式运行打包脚本，并再次检查包内是否包含敏感文件。
  - 本地未跟踪的 `cookie.json`、`results/`、PDF 和虚拟环境不应删除，但也不应进入 Git 或发布包。

## 2026-07-09 16:02:36

- 本次任务目标：
  - 根据当前项目与原项目的实际关系，完善公开来源声明和 MIT 修改版权表述。
  - 将用户可见的”OA 下载”改为”OA 资源辅助获取”。
- 新增、修改或删除的文件：
  - 修改 `LICENSE`
  - 修改 `NOTICE`
  - 修改 `README.md`
  - 修改 `README_zh.md`
  - 修改 `WINDOWS_UI_README.md`
  - 修改 `paper_scraper_ui.py`
  - 修改 `paper_skill.py`
  - 修改 `skills/paper-download/SKILL.md`
  - 修改 `skills/legal-oa-paper-download/SKILL.md`
  - 修改 `skills/sciencedirect-doi-download/SKILL.md`
  - 修改 `skills/sciencedirect-doi-download/references/failure-reasons.md`
  - 修改 `docs/superpowers/plans/2026-06-17-paper-skill.md`
  - 修改 `tests/test_doi_batch_utils.py`
  - 修改 `tests/test_skills_packaging.py`
  - 修改 `CHANGELOG.md`
- 具体修改内容：
  - `LICENSE` 中维护者声明改为 `Copyright (c) 2026 wkguoo (modifications)`，同时保留原作者 `Copyright (c) 2026 GAO-pooh`。
  - `NOTICE` 改为说明本项目基于并扩展 `GAO-pooh/paper-scraper`，并把 OA 相关描述改为 `open-access resource discovery and download-assistance workflow`。
  - README 来源声明改为“基于开源项目修改并扩展”，并说明本仓库保留原项目版权声明和许可声明，后续修改、扩展与新增模块由 `wkguoo` 维护并声明修改部分版权。
  - README、Windows UI 文档和 UI 标签将”OA 下载”统一改为”OA 资源辅助获取”。
  - 保留 `legal-oa-paper-download` 目录名和 skill name 作为兼容入口。
  - 更新测试，检查新版权声明、新来源声明、新 UI 摘要名称，并增加公开文案禁用短语检查。
- 修改原因：
  - 项目确实复用了原项目的实质性代码、结构或实现逻辑，因此公开声明应采用“基于并扩展”而不是“仅受启发”。
  - 发布时更适合使用”OA 资源辅助获取”的措辞。
- 如何运行：
  - 语法检查：`.\.venv\Scripts\python.exe -m py_compile paper_scraper_ui.py paper_skill.py`
  - 定向测试：`.\.venv\Scripts\python.exe -m unittest tests.test_doi_batch_utils tests.test_skills_packaging -v`
  - 完整测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  - 文案检查：`rg -n "不合规|不合理|异常" README.md README_zh.md WINDOWS_UI_README.md NOTICE paper_scraper_ui.py paper_skill.py skills docs`
  - Git 检查：`git diff --check`
- 生成的输出文件：
  - 本次没有生成新的 PDF、下载结果目录或 Windows UI 打包产物。
  - 测试过程中仅在系统临时目录生成临时测试文件和日志。
- 如何检查是否成功：
  - UI 中第三个入口应显示为“OA 资源辅助获取”。
  - README 和 Windows UI 文档不应再把 OA 流程表述成法律保证。
  - `LICENSE` 和 `NOTICE` 应同时保留原项目来源和本项目修改版权声明。
  - 定向测试和完整测试应全部通过。
- 注意事项或潜在风险：
  - 本次不改变 ScienceDirect/CDP、Cookie、机构权限下载或 OA 下载实现逻辑。
  - 本次不重命名 `legal-oa-paper-download` skill，避免破坏已有 Codex 调用。
  - 本次没有重新打包 Windows UI。

## 2026-07-09 16:37:55

- 本次任务目标：
  - 完善 GitHub 公开首页的“门面信息”，让仓库更像可使用的公开项目，而不是个人脚本目录。
  - 增加 README 顶部展示、安全政策和 Issue 模板，并准备发布首个 `v0.1.0` 源码 release。
- 新增、修改或删除的文件：
  - 修改 `README.md`
  - 修改 `README_zh.md`
  - 新增 `SECURITY.md`
  - 新增 `.github/ISSUE_TEMPLATE/bug_report.yml`
  - 新增 `.github/ISSUE_TEMPLATE/feature_request.yml`
  - 修改 `CHANGELOG.md`
- 具体修改内容：
  - `README.md` 改为英文公开首页，顶部加入 Python、Windows、License、Tests 和 Release badge，并加入 `English | 中文说明` 语言入口。
  - `README.md` 聚焦项目用途、使用说明、快速开始、常用工作流、输出文件、安全提醒、开发检查和来源声明。
  - `README_zh.md` 改为完整中文说明，保留原新手安装、Codex Skills、ScienceDirect 机构权限、OA 资源辅助获取、输出文件、安全和发布说明。
  - `SECURITY.md` 明确不要在公开 Issue/PR 上传 cookies、账号密码、PDF、机构内部页面截图或私有结果文件，并说明安全问题应私下报告。
  - 新增 Bug report 和 Feature request 两个 GitHub Issue form，加入敏感信息和访问权限绕过相关确认项。
- 修改原因：
  - GitHub 公开项目首页需要清晰的英文门面、可点击徽章、语言入口和安全边界说明，方便新用户快速判断项目用途。
  - 该项目会接触机构 Cookie、浏览器登录状态、下载目录和论文 PDF，因此需要比普通工具更明确的安全提交规则。
  - Issue 模板可减少无效问题报告，并降低用户误传敏感凭证、PDF 或机构页面截图的风险。
- 如何运行：
  - 格式检查：`git diff --check`
  - 完整单元测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  - 文案扫描：`rg -n "CAPTCHA|403|cookie|cookies" README.md README_zh.md SECURITY.md .github`
  - 敏感产物跟踪检查：`git ls-files | rg "cookie|cookies|results|pdfs|\.pdf$|\.xlsx$|\.csv$|\.venv|dist"`
- 生成的输出文件：
  - 新增 `SECURITY.md`
  - 新增 `.github/ISSUE_TEMPLATE/bug_report.yml`
  - 新增 `.github/ISSUE_TEMPLATE/feature_request.yml`
  - 本次没有重新打包 Windows UI，没有生成 exe、zip、PDF、下载结果目录或其他发布附件。
- 如何检查是否成功：
  - GitHub README 顶部应显示 badge 和 `English | 中文说明` 语言入口。
  - GitHub Issues 新建页面应出现 Bug report 和 Feature request 两个模板。
  - `SECURITY.md` 应提醒不要公开上传 cookies、密码、PDF、机构内部页面截图或私有结果文件。
  - 本地测试和 `git diff --check` 应通过。
  - GitHub About 区域后续应显示项目 description 和 topics，Website 保持为空。
  - Release 页面后续应显示 `v0.1.0 - Initial public release`，且不包含二进制 exe 或敏感附件。
- 注意事项或潜在风险：
  - 本次不改变 ScienceDirect/CDP、Cookie、机构权限下载、OA 资源辅助获取或 UI 实现逻辑。
  - 本次不重新打包 Windows UI，不发布 exe。
  - `cookie.json`、PDF、`results/`、`.venv/` 和 `dist/` 等本地产物仍不应进入 Git、Issue 或 release 附件。

## 2026-07-09 17:02:55

- 本次任务目标：
  - 排查 GitHub README 中 `tests failing` 徽章对应的 CI 失败，并修复测试对可选依赖导入状态过于敏感的问题。
- 新增、修改或删除的文件：
  - 修改 `tests/test_sd_institutional_skill.py`
  - 修改 `CHANGELOG.md`
- 具体修改内容：
  - `test_scraper_reads_edge_cookies_before_chrome_cookies` 改为直接注入假的 `browser_cookie3` 对象，避免在缺少 `browser-cookie3` 或该库导入失败的环境中因 `None.edge` 报错。
  - `test_english_devtools_uses_legacy_existing_pdf_filename_for_supplements` 增加对 `sd_scraper_en.curl_requests.Session` 的 mock，避免测试补充材料文件名传递逻辑时误触发真实 `curl_cffi` 依赖。
- 修改原因：
  - 这两个测试验证的是 Cookie 读取优先级和补充材料使用既有 PDF 文件名的业务行为，不应依赖 CI 或本地环境是否真的可导入浏览器 Cookie 库和 `curl_cffi`。
  - Codex 自带 Python 3.12 无项目依赖环境可复现两个错误：`browser_cookie3` 为 `None` 以及 `curl_cffi` 缺失时测试失败。
- 如何运行：
  - 定向测试：`.\.venv\Scripts\python.exe -m unittest tests.test_sd_institutional_skill -v`
  - 完整测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  - 格式检查：`git diff --check`
- 生成的输出文件：
  - 本次没有生成新的 PDF、下载结果目录、Windows UI 打包产物或 release 附件。
  - 测试过程只会在系统临时目录生成临时测试文件。
- 如何检查是否成功：
  - 定向测试应不再出现 `None does not have the attribute 'edge'`。
  - 定向测试应不再因 `Missing dependency curl_cffi` 阻断补充材料文件名测试。
  - GitHub Actions 的 `tests` badge 后续应从 failing 变为 passing。
- 注意事项或潜在风险：
  - 本次只修改测试隔离方式，不改变 ScienceDirect/CDP、Cookie、机构权限下载、OA 资源辅助获取或 UI 运行逻辑。
  - 真实机构登录、真实 PDF 下载和补充材料下载仍需要按 `MANUAL_QA.md` 人工检查。

## 2026-07-09 17:15:14

- 本次任务目标：
  - 继续排查 GitHub README 中 `tests failing` 徽章对应的 CI 失败，并修复 GitHub Actions Windows runner 上的路径断言问题。
- 新增、修改或删除的文件：
  - 修改 `tests/test_sd_institutional_skill.py`
  - 修改 `CHANGELOG.md`
- 具体修改内容：
  - 新增 `assert_same_existing_path()` 测试辅助函数，先检查 JSON 中记录的路径和期望路径都存在，再用 `Path.samefile()` 判断是否指向同一个文件。
  - 将 `paper_index_path`、`failure_next_steps_path`、`paper_index_xlsx_path` 三处直接字符串相等断言改为同文件断言。
  - 将 `run_summary.txt` 中的三个路径字符串断言改为检查关键输出文件名，避免 Windows 短路径/长路径差异造成误判。
- 修改原因：
  - GitHub Actions 的 Windows runner 会在临时目录中混用短用户名路径 `C:\Users\RUNNER~1\...` 和长用户名路径 `C:\Users\runneradmin\...`。
  - 这两种字符串不同，但实际指向同一个文件；原测试直接比较字符串会误判失败。
- 如何运行：
  - 定向测试：`.\.venv\Scripts\python.exe -m unittest tests.test_sd_institutional_skill.InstitutionalSkillIntakeTests.test_beginner_preflight_writes_review_hints_without_sciencedirect_resolution tests.test_sd_institutional_skill.InstitutionalSkillIntakeTests.test_main_writes_empty_reports_when_no_valid_doi -v`
  - 完整测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  - 格式检查：`git diff --check`
- 生成的输出文件：
  - 本次没有生成新的 PDF、下载结果目录、Windows UI 打包产物或 release 附件。
  - 测试过程只会在系统临时目录生成临时测试文件。
- 如何检查是否成功：
  - 两个 GitHub Actions 失败用例应通过。
  - 完整单元测试应显示 `Ran 135 tests ... OK`。
  - GitHub Actions 的 `tests` badge 后续应从 failing 变为 passing。
- 注意事项或潜在风险：
  - 本次只修复测试在 Windows 短路径/长路径差异下的断言方式，不改变业务输出路径、不改变下载逻辑。
  - 本地仍存在被 `.gitignore` 忽略的 `cookie.json`、`results/`、`dist/` 等文件；它们不应进入 Git、Issue 或 release 附件。
## 2026-07-09 18:21:32 +08:00

- 本次任务目标：
  - 先修复 IUCr 非 Elsevier 机构下载中 `not_pdf_response` 的常见根因。
  - 新增 AAAS、Taylor & Francis、ACS、AIP 四类常用出版社的官网 PDF 候选链接适配，避免这些 DOI 直接落入 `unsupported_publisher`。
- 新增、修改或删除的文件：
  - 新增 `paper_automation/institutional/adapters/common_publishers.py`
  - 修改 `paper_automation/institutional/adapters/__init__.py`
  - 修改 `paper_automation/institutional/adapters/iucr.py`
  - 修改 `paper_automation/institutional/pdf_checks.py`
  - 修改 `paper_automation/institutional/registry.py`
  - 修改 `tests/test_institutional_browser.py`
  - 修改 `tests/test_institutional_paper_skill.py`
  - 修改 `CHANGELOG.md`
- 具体修改内容：
  - 为 AAAS、Taylor & Francis、ACS、AIP 增加 adapter，按 DOI 前缀、publisher 字段或落地页 host 识别出版社。
  - 新增出版社官网 PDF 候选路由：`science.org/doi/pdf/...`、`tandfonline.com/doi/pdf/...?...`、`pubs.acs.org/doi/pdf/...`、`pubs.aip.org/.../article-pdf/doi/...`。
  - IUCr 适配新增 `journals.iucr.org/.../index.html` 到同目录 `文章代码.pdf` 的候选路径。
  - IUCr 适配修复 `scripts.iucr.org/cgi-bin/paper?S...` 查询串被覆盖的问题，现在追加 `download=pdf` 时保留原始文章编号。
  - PDF URL 判断新增对 `/epdf` 和 `article-pdf` 的识别。
  - 更新离线测试，覆盖 IUCr 文章代码 PDF 路径、IUCr scripts 查询串保留、常用出版社 adapter 路由和工作流报告行为。
- 修改原因：
  - 用户提供的失败清单中，IUCr 失败集中表现为页面可打开但未捕获 PDF，根因之一是候选 PDF URL 不完整或破坏了 scripts 查询串。
  - AAAS、Taylor & Francis、ACS、AIP 原先被明确标为未支持出版社，导致即使机构浏览器可访问，也不会进入下载尝试。
  - 这些修改只增加出版社官网候选链接， `%PDF` 文件头校验。
- 如何运行：
  - 定向 adapter 测试：`.\.venv\Scripts\python.exe -m unittest tests.test_institutional_browser -v`
  - 定向工作流测试：`.\.venv\Scripts\python.exe -m unittest tests.test_institutional_paper_skill -v`
  - 完整单元测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  - 编译检查：`.\.venv\Scripts\python.exe -m compileall paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation`
- 生成的输出文件：
  - 新增源码文件 `paper_automation/institutional/adapters/common_publishers.py`
  - 测试过程只在系统临时目录生成临时 CSV、PDF、JSON、日志文件。
  - 本次没有生成新的真实论文 PDF、下载结果目录、Windows UI 打包产物或 release 附件。
- 如何检查是否成功：
  - `tests.test_institutional_browser` 应显示 9 个测试全部通过。
  - `tests.test_institutional_paper_skill` 应显示 2 个测试全部通过。
  - 完整测试应显示 `Ran 146 tests ... OK`。
  - 重新处理失败清单时，#8、#43、#47、#63、#88 不应再直接报告 `unsupported_publisher`，而应进入对应 adapter 后报告真实下载结果，例如 `pdf_downloaded`、`auth_required`、`publisher_blocked`、`not_pdf_response` 或 `error`。
  - IUCr 的 `journals.iucr.org` 和 `scripts.iucr.org` DOI 应能生成更具体的 PDF 候选 URL。
- 注意事项或潜在风险：
  - 新增 adapter 只负责生成候选 PDF 链接；真实下载仍取决于学校 VPN、机构登录、出版社权限、验证码和站点反自动化策略。
  - AIP 的 DOI 直连路由依赖落地页中的期刊路径；若某些 AIP 文章落地页结构不同，仍可能需要后续按报告继续补适配。
  - 本次没有自动重新下载失败论文，没有修改原始输入数据，也没有重新打包项目。

## 2026-07-09 22:10:20 +08:00

- 本次任务目标：
  - 在正式下载流程开始时允许输入一个可选保底 PDF 链接。
  - 自动下载流程照常运行；只有最后恰好 1 篇 PDF 失败时，才使用该链接补下载。
  - 不增加单独 CSV、不增加第二套下载流程。
- 新增、修改或删除的文件：
  - 修改 `doi_batch_utils.py`
  - 修改 `sd_scraper.py`
  - 修改 `sd_institutional_skill.py`
  - 修改 `paper_scraper_ui.py`
  - 修改 `tests/test_doi_batch_utils.py`
  - 修改 `CHANGELOG.md`
- 具体修改内容：
  - 为 `PdfDownloadRecord` 和 `pdf_download_report.csv` 增加 `manual_pdf_url`、`manual_status`、`manual_reason` 三列。
  - 新增 `apply_manual_pdf_url_fallback()`，负责单链接保底下载、`http/https` 链接校验、PDF 文件头校验、HTML/登录页拒绝和多失败项拒绝。
  - `sd_scraper.py` 新增 `--manual-pdf-url` 参数，并在 DOI 批量和检索下载结束后执行单篇失败保底补下载。
  - `sd_institutional_skill.py` 同步新增 `--manual-pdf-url` 参数和相同保底逻辑。
  - Windows UI 在“权限与输出”区域新增“保底 PDF 链接（可选）”输入框，并在开启 PDF 下载时把它传入正式命令。
  - UI 运行前体检和参数校验会提示/阻止非 `http/https` 链接。
  - 新增测试覆盖：单篇失败 + 有效 PDF 成功补下载、单篇失败 + HTML 拒绝、多篇失败不猜测、全部自动成功时不使用保底链接、UI 命令参数传递。
- 修改原因：
  - 部分文章自动流程可能因出版社适配、机构登录或页面捕获失败而无法下载。
  - 用户希望在同一个正式流程开始时只输入一个保底链接，避免另建 CSV 或额外流程。
  - 单链接无法可靠匹配多篇失败文章，因此只在最后恰好剩 1 篇失败时使用，降低误配风险。
- 如何运行：
  - UI：启动 `start_paper_scraper_ui.bat`，在“DOI 批量下载”页填写输入表和“保底 PDF 链接（可选）”，然后按原流程运行。
  - CLI：`.\.venv\Scripts\python.exe sd_scraper.py -m doi_batch --input "papers.csv" --download-pdfs --manual-pdf-url "https://example.edu/paper.pdf"`
  - 技能入口：`.\.venv\Scripts\python.exe sd_institutional_skill.py --input "papers.csv" --manual-pdf-url "https://example.edu/paper.pdf"`
- 生成的输出文件：
  - 正式运行时仍输出到原有结果目录和 `pdfs/` 子目录。
  - `pdf_download_report.csv` 新增三列用于记录保底链接状态。
  - 测试过程只在系统临时目录生成临时 CSV、PDF、JSON、日志文件。
  - 本次没有生成真实论文 PDF、没有修改原始输入数据、没有打包项目。
- 如何检查是否成功：
  - 单元测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests -v`，结果为 `Ran 150 tests ... OK`。
  - 编译检查：`.\.venv\Scripts\python.exe -m compileall paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation doi_batch_utils.py`。
  - 格式检查：`git diff --check` 不应出现空白错误。
  - 实际运行后，若自动下载只剩 1 篇 PDF 失败且保底链接返回真 PDF，`pdf_download_report.csv` 中该行状态应为 `manual_pdf_downloaded`，PDF 应保存到 `pdfs/`。
- 注意事项或潜在风险：
  - 保底链接应使用你有权访问的普通 PDF 链接；程序不会新增任何额外出版社或站点适配。
  - 如果最后失败超过 1 篇，程序不会猜测该链接对应哪一篇，会记录 `manual_url_ambiguous_multiple_failures`。
  - 如果链接返回 HTML、登录页或非 PDF 内容，会保留原失败状态，并记录 `manual_response_not_pdf`。
  - 真正能否补下载仍取决于链接有效期、机构登录状态、学校 VPN、站点权限和网络连接。

## 2026-07-10 11:50:02 +08:00

- 本次任务目标：解析 `D:\桌面\文献下载\acta_v51_must_cite_100_high_level_references.md`，并下载其中论文 PDF。
- 新增、修改或删除的文件：
  - 新增 `results/acta_v51_must_cite_institutional_20260710/download_status.md`。
  - 新增 `results/acta_v51_must_cite_institutional_20260710/remaining_aip.txt`。
  - 新增下载结果目录及其中的 PDF、预检表、失败报告和运行摘要。
  - 修改 `CHANGELOG.md`，追加本次操作记录。
- 具体修改内容：
  - 预检识别出 14 个有效且唯一的 DOI，无重复、无无效项。
  - 使用非 Elsevier 机构访问下载器，确认 7 篇 PDF 保存到 `non_elsevier_institutional/pdfs/`。
  - 通过 Chrome 中的 IUCr 官方文章页对另外 6 篇触发 PDF 下载，但浏览器接口未返回保存路径，因此只记录为“已触发、待确认”。
  - 对最后一篇 AIP 文献单独重试，报告为 `not_pdf_response` / `network_pdf_not_captured`，页面出现 Cloudflare Turnstile 验证。
- 修改原因：原始清单由 AAAS、Taylor & Francis、ACS、Springer、IUCr 和 AIP 等多个非 Elsevier 出版商组成，ScienceDirect 专用入口不适用，需要按出版商路由并使用机构访问或官方公开链接。
- 如何运行：
  - 预检：`.\.venv\Scripts\python.exe sd_institutional_skill.py --input "D:\桌面\文献下载\acta_v51_must_cite_100_high_level_references.md" --out ".\results" --run-name "acta_v51_must_cite_retry_20260710" --preflight`
  - 非 Elsevier 机构下载：`.\.venv\Scripts\python.exe institutional_paper_skill.py --input "D:\桌面\文献下载\acta_v51_must_cite_100_high_level_references.md" --out ".\results\acta_v51_must_cite_institutional_20260710"`
  - AIP 单篇重试：`.\.venv\Scripts\python.exe institutional_paper_skill.py --input ".\results\acta_v51_must_cite_institutional_20260710\remaining_aip.txt" --out ".\results\acta_v51_must_cite_institutional_20260710\aip_retry"`
- 生成的输出文件：
  - 7 个已确认的 PDF：`results/acta_v51_must_cite_institutional_20260710/non_elsevier_institutional/pdfs/`。
  - 状态汇总：`results/acta_v51_must_cite_institutional_20260710/download_status.md`。
  - AIP 失败报告：`results/acta_v51_must_cite_institutional_20260710/aip_retry/non_elsevier_institutional/institutional_pdf_download_report.csv`。
- 如何检查是否成功：
  - 项目 PDF 目录应有 7 个非空 `.pdf` 文件。
  - `download_status.md` 应列出 14 个 DOI 的三类状态。
  - AIP 报告应保留真实失败原因，不应把 HTML/Cloudflare 页面保存为 PDF。
- 注意事项或潜在风险：
  - 6 篇 IUCr 文献的官方 Chrome 下载动作已完成，但项目目录中未确认其保存位置；需在 Chrome 下载列表或浏览器配置的下载目录中确认。
  - AIP 文献需要用户本人完成 Cloudflare Turnstile 验证。
  - 未修改原始 Markdown，未自动重新打包项目。

## 2026-07-10 16:55:37 +08:00

- 本次任务目标：设计“用户只提供文献清单，由项目下载器和 Zotero 自动协作，最终集中交付 PDF”的失败回退流程。
- 新增、修改或删除的文件：
  - 新增 `docs/superpowers/specs/2026-07-10-zotero-paper-download-fallback-design.md`。
  - 修改 `CHANGELOG.md`，追加本次设计记录。
- 具体修改内容：
  - 确定项目优先、Zotero 仅处理失败项的两层编排架构。
  - 确定 Zotero 临时集合保留、不自动删除条目，附件只复制不移动。
  - 明确 OA、机构访问、Zotero 回退的顺序，以及一次暂停、一次重试的人工恢复策略。
  - 明确批次状态恢复、PDF 校验、去重、输出结构、错误状态、测试和人工验收标准。
  - 明确新流程不调用 Sci-Hub、Anna's Archive、LibGen 或其他影子库，不绕过访问权限或 CAPTCHA。
- 修改原因：让用户以后只需提供文献清单，由 Codex 自动协调项目与 Zotero，尽量减少逐篇人工操作，同时保持可恢复、可复核和不修改原始数据。
- 如何运行：本次仅完成设计，尚无可运行的新入口；设计获最终复核后再生成实施计划并开发。
- 生成的输出文件：本次未下载论文、未生成 PDF；只生成设计文档。
- 如何检查是否成功：打开设计文档，确认其中没有 `TBD`、`TODO` 或未定义流程，并核对架构、数据流、异常处理和测试要求与已确认内容一致。
- 注意事项或潜在风险：
  - 当前 Zotero 连接检测返回 `No active library available`，实施和人工验收时需要打开 Zotero 并激活目标文库。
  - 当前工作区存在用户未提交修改；本次不覆盖这些修改，也不自动重新打包项目。

## 2026-07-10 17:10:00 +08:00

- 本次任务目标：根据已批准的 Zotero 文献下载回退设计，编写可测试、可恢复、分任务实施的详细开发计划。
- 新增、修改或删除的文件：
  - 新增 `docs/superpowers/plans/2026-07-10-zotero-paper-download-fallback.md`。
  - 修改 `CHANGELOG.md`，追加实施计划记录。
- 具体修改内容：
  - 将开发拆分为停用影子库活动回退、批次状态与 PDF 校验、项目下载路由、一次性恢复、Zotero 结果归并、统一 CLI、Skill 协调和完整验收八个任务。
  - 为每个任务写明文件、接口、测试驱动步骤、运行命令、预期结果和提交边界。
  - 明确当前工作区已有未提交修改时不得整文件误提交，尤其是 README、Skill 和 CHANGELOG。
- 修改原因：让后续开发可以逐步验证，不因跨项目、浏览器和 Zotero 的复杂协作而遗漏安全边界或恢复能力。
- 如何运行：本次只生成实施计划；开发时按计划中的任务顺序运行对应 `unittest`、`compileall` 和人工 Zotero 验收。
- 生成的输出文件：实施计划 Markdown；未下载论文，未生成 PDF。
- 如何检查是否成功：确认计划不存在 `TBD`、`TODO` 或未定义接口，并逐项对应已批准设计中的架构、数据流、错误处理、测试和完成标准。
- 注意事项或潜在风险：
  - 当前 Zotero 尚无活动文库，最终人工验收前需要打开 Zotero。
  - 当前工作区为只读权限配置，实施写入需要按最小范围申请权限。
  - 本次未自动重新打包项目。

## 2026-07-10 17:30:00 +08:00

- 本次任务目标：为 Zotero 文献下载回退功能创建安全的隔离开发工作树。
- 新增、修改或删除的文件：
  - 修改 `.gitignore`。
  - 修改 `CHANGELOG.md`，追加本次工作树准备记录。
- 具体修改内容：
  - 忽略 `.worktrees/`，防止项目内 Git 工作树被误加入版本控制。
  - 忽略 `.codex-test-tmp/`，防止离线测试临时文件进入 Git 状态。
- 修改原因：当前 `main` 工作区已有用户未提交修改，隔离开发可以避免覆盖或混入这些文件。
- 如何运行：创建分支 `codex/zotero-paper-download`，工作树路径为 `.worktrees/codex-zotero-paper-download`。
- 生成的输出文件：隔离工作树目录；不生成论文 PDF。
- 如何检查是否成功：`git check-ignore -v .worktrees` 应命中 `.gitignore`，隔离工作树中基线测试应通过。
- 注意事项或潜在风险：不删除、不覆盖当前 `main` 中的未提交修改；本次不自动重新打包项目。


## 2026-07-11 21:54:33 +08:00

- 本次任务目标：
  - 只处理 `results/acta_v51_llm_zotero_fallback_doi_20260711_20260711_205638/working/zotero_fallback.csv` 中 7 条 DOI 的 Zotero 回退。
  - 不重跑项目下载流程，直接在当前选中的个人 Zotero 文库中按 DOI 查找现有条目，并生成严格表头的 `zotero_results.csv`。
- 新增、修改或删除的文件：
  - 新增 `results/acta_v51_llm_zotero_fallback_doi_20260711_20260711_205638/working/zotero_results.csv`
  - 修改 `CHANGELOG.md`
- 具体修改内容：
  - 使用 Zotero MCP 和 Zotero runtime API 对 7 条 DOI 做精确匹配检查。
  - 确认 7 条 DOI 均已存在于当前个人文库中，且每条都已有实际存在的 PDF 附件，因此本次未执行缺失条目导入。
  - 创建临时集合 `tmp_acta_v51_llm_zotero_fallback_20260711_205638`（collectionId `117`），并将选中的 7 条现有文献加入该集合。
  - 对重复 DOI `10.1107/S0021889886089999` 命中的 2 条现有条目，选用带有效 PDF 且 `itemId` 更小的 `12967` 作为结果写入项。
  - 按严格表头 `task_id,zotero_item_id,attachment_path,status,reason` 写出结果文件。
  - 通过 Zotero runtime 检查 `canFindPDFForItem()`，这 7 条条目均因已存在 PDF 附件而不适用额外“Find Available PDF”动作，因此在结果 `reason` 中记录 `find_available_pdf_not_applicable_canFindPDF_false`。
- 修改原因：
  - 用户要求对非 Elsevier 失败项执行一次独立的 Zotero 回退，并将可核验的 Zotero 条目 ID 与实际 PDF 绝对路径回写到指定结果文件，供原流程后续 `finalize` 使用。
- 如何运行：
  - 本次未运行项目主下载脚本。
  - 通过 Zotero MCP 的 `library_search`、`library_read`、`collection_update`、`library_update` 与 `zotero_script` 完成条目匹配、附件绝对路径检查和临时集合整理。
- 生成的输出文件：
  - `C:\Users\wkguopro\Documents\New project 2\paper-scraper-doi\results\acta_v51_llm_zotero_fallback_doi_20260711_20260711_205638\working\zotero_results.csv`
- 如何检查是否成功：
  - 打开 `zotero_results.csv`，应只有 7 条数据，且表头严格为 `task_id,zotero_item_id,attachment_path,status,reason`。
  - 每条 `attachment_path` 都应为实际存在的绝对 PDF 路径。
  - Zotero 中应存在临时集合 `tmp_acta_v51_llm_zotero_fallback_20260711_205638`，其中包含 7 条文献。
- 注意事项或潜在风险：
  - 本次没有安装或打包 Zotero 桥接插件，没有参考 AutoClass，没有直接修改 Zotero SQLite 数据库。
  - 本次没有重跑 `sd_scraper.py`、`sd_institutional_skill.py` 或其他项目下载主流程。
  - 由于 7 条 DOI 均已存在 PDF，本次没有实际触发新的附件抓取或 DOI 导入。

## 2026-07-11 22:08:00 +08:00

- 本次任务目标：校验 Zotero 回退结果，并完成 `acta_v51_llm_zotero_fallback_doi_20260711_20260711_205638` 批次的最终非破坏归并。
- 新增、修改或删除的文件：
  - 新增 `results/acta_v51_llm_zotero_fallback_doi_20260711_20260711_205638/working/zotero_results_retry_20260711_220354.csv`。
  - 更新该批次的 `working/batch_state.json`、`working/manual_retry.csv`、`working/zotero_fallback.csv` 和 `reports/` 最终报告。
  - 向该批次的 `pdfs/` 新增 7 份从 Zotero 附件非破坏复制的 PDF。
  - 修改 `CHANGELOG.md`，追加本次归并记录。
- 具体修改内容：
  - 校验原始 `zotero_results.csv` 的严格表头、7 个任务 ID、Zotero 条目 ID、绝对附件路径、普通文件属性及 PDF 文件签名。
  - 原结果使用了非协议状态 `success`，因此保留原文件不变，并按恢复规则独占创建时间戳重试文件，将7条结果规范化为 `existing_pdf`。
  - 执行 `paper_batch.py finalize`，将7份附件复制到批次 `pdfs/`，不移动、不重命名、不修改 Zotero 原附件。
  - 首次报告发布受到另一 Codex 沙箱创建文件的 Windows ACL 限制；PDF与批次状态已经保存。随后使用本机项目权限恢复报告发布，终态任务被自动跳过，没有重复复制PDF。
- 修改原因：使 Zotero 输出符合项目状态协议，并生成可核验的最终 PDF 目录和审计报告。
- 如何运行：本次已经完成，无需再次执行 `start`、`resume` 或 `finalize`。
- 生成的输出文件：
  - 最终 PDF：`results/acta_v51_llm_zotero_fallback_doi_20260711_20260711_205638/pdfs/`（7份）。
  - 最终清单：`results/acta_v51_llm_zotero_fallback_doi_20260711_20260711_205638/reports/final_manifest.csv` 和 `final_manifest.xlsx`。
  - 运行摘要：`results/acta_v51_llm_zotero_fallback_doi_20260711_20260711_205638/reports/run_summary.txt`。
- 如何检查是否成功：`run_summary.txt` 应显示 `input_count: 7`、`success_count: 7`、`failure_count: 0`；最终 PDF 目录应包含7份 `.pdf` 文件，`zotero_fallback.csv` 应只保留表头。
- 注意事项或潜在风险：原始 `zotero_results.csv` 保留为审计证据；后续应使用规范化的时间戳重试文件和最终报告。未安装或打包 Zotero 插件，未参考 AutoClass，未修改 Zotero SQLite 数据库。

## 2026-07-11 22:52:10 +08:00

- 本次任务目标：将“缺少 DOI 的文献线索必须先检索核验、不能直接跳过”的原则写入项目级长期规则。
- 新增、修改或删除的文件：
  - 修改 `AGENTS.md`。
  - 修改 `CHANGELOG.md`，追加本次规则变更记录。
- 具体修改内容：
  - 在 `AGENTS.md` 新增 `Literature Identification & Download Rules` 小节。
  - 明确只有作者、年份、题名片段、期刊线索或研究方向时，必须先通过权威学术来源核验正式题名、作者、年份、期刊和 DOI，再进入下载流程。
  - 明确完成身份核验后需与已解析或已下载文献去重，并继续下载正文及明确关联的补充材料。
  - 明确无法唯一匹配时不得猜测或静默忽略，应记录候选、歧义原因和 `metadata_uncertain` 等待复核状态。
  - 明确泛指研究方向或论文系列应先形成有边界、有筛选标准的候选清单，避免无限扩展下载范围。
- 修改原因：避免后续文献批次把“没有现成 DOI”错误等同于“无需下载”，确保模糊文献线索也经过可审计的检索、核验和结果记录。
- 生成的输出文件：无新的 PDF、数据表或打包文件；仅更新项目说明与变更记录。
- 如何检查是否成功：打开 `AGENTS.md`，确认存在 `Literature Identification & Download Rules` 小节，并包含“不因缺少 DOI 跳过、先核验、歧义留痕、候选范围有边界”四项要求。
- 注意事项或潜在风险：该规则约束后续任务流程，但不会自动补跑此前遗漏的模糊文献线索；本次未修改下载脚本，未重新打包项目。

## 2026-07-11 22:56:48 +08:00

- 本次任务目标：将 Windows 浏览器辅助登录和论文下载的默认浏览器从 Edge 改为 Chrome，并禁止项目默认读取 Edge Cookie。
- 新增、修改或删除的文件：
  - 修改 `windows_paths.py`。
  - 修改 `sd_scraper.py`。
  - 修改 `sd_institutional_skill.py`。
  - 修改 `WINDOWS_UI_README.md`。
  - 修改 `AGENTS.md`。
  - 修改 `tests/test_windows_paths.py`。
  - 修改 `tests/test_sd_institutional_skill.py`。
  - 修改 `CHANGELOG.md`。
- 具体修改内容：
  - Windows 默认浏览器候选仅保留 Google Chrome、Playwright Chromium 和系统 Chrome 命令，不再自动发现或启动 Edge Stable/Beta/Dev/SxS。
  - 自动浏览器 Cookie 读取改为只调用 Chrome，不再调用 `browser_cookie3.edge`。
  - 更新 CLI 帮助、交互提示和 Windows UI 文档，统一说明默认使用 Chrome。
  - 在项目 `AGENTS.md` 中写入长期规则：Windows 机构登录和论文下载默认使用 Chrome，不自动启动 Edge 或读取 Edge Cookie。
  - 保留 `--browser-exe` 和 `PAPER_SCRAPER_BROWSER_EXE` 作为用户显式覆盖入口。
  - 更新路径与 Cookie 单元测试，覆盖 Chrome 优先、忽略各 Edge 通道以及不调用 Edge Cookie 加载器。
- 修改原因：用户明确要求项目不要调用 Edge 浏览器，改用 Chrome；原实现的浏览器候选顺序和 Cookie 加载顺序均以 Edge 优先。
- 生成的输出文件：无新的论文 PDF、数据表或安装包。
- 如何运行：正常运行原 ScienceDirect CLI 或 Skill 即可；未指定 `--browser-exe` 时会使用 Chrome。
- 如何检查是否成功：
  - `\.venv\Scripts\python.exe -m unittest tests.test_windows_paths tests.test_sd_institutional_skill.InstitutionalSkillCookieTests -v` 应显示 14 项测试全部通过。
  - `\.venv\Scripts\python.exe -m py_compile windows_paths.py sd_scraper.py sd_institutional_skill.py` 应返回退出码 0。
  - 本机同时安装 Edge 和 Chrome 时，`browser_bin()` 应返回 Chrome 路径。
- 注意事项或潜在风险：如果 Chrome 未安装，程序将报告 Chrome 路径不可用，不会自动回退到 Edge；如需其他 Chromium 浏览器，必须显式传入 `--browser-exe`。本次未重新打包项目。
## 2026-07-11 23:15:05 +08:00

- 本次任务目标：将“浏览器操作默认使用 Codex 内置 Chrome，不单独打开桌面浏览器窗口”写入项目长期规则。
- 新增、修改或删除的文件：
  - 修改 `AGENTS.md`。
  - 修改 `CHANGELOG.md`，追加本次规则变更记录。
- 具体修改内容：
  - 浏览器辅助登录、文献检索和论文下载默认使用 Codex 内置 Chrome 浏览器。
  - 禁止自动启动独立窗口中的 Google Chrome、Microsoft Edge 或其他桌面浏览器，也不得自动读取这些桌面浏览器的 Cookie。
  - 只有用户明确要求或授权时，才允许使用外部桌面浏览器。
  - 保留 `--browser-exe` 和 `PAPER_SCRAPER_BROWSER_EXE`，但仅作为用户显式控制、且流程确实需要外部浏览器时的覆盖入口。
- 修改原因：避免自动打开独立桌面窗口，确保后续浏览器交互统一在 Codex 内置浏览器中完成。
- 生成的输出文件：无数据、PDF 或打包文件；仅更新项目规则和变更记录。
- 如何检查是否成功：打开 `AGENTS.md`，确认 `Literature Identification & Download Rules` 小节明确包含“默认使用 Codex 内置 Chrome、禁止自动启动桌面浏览器、外部浏览器需用户明确授权”。
- 注意事项或潜在风险：该规则约束后续操作方式，但不会自动重构现有 CLI 中依赖外部浏览器进程的实现；如某流程只能由外部浏览器完成，必须先说明并取得用户授权。本次未重新打包项目。
## 2026-07-10 17:25:00 +08:00

- 本次任务目标：在隔离分支中开始实施项目下载器与 Zotero 的失败回退集成。
- 新增、修改或删除的文件：
  - 修改 `.gitignore`。
  - 修改 `CHANGELOG.md`，追加实施启动记录。
- 具体修改内容：
  - 创建隔离分支 `codex/zotero-paper-download` 和项目内工作树。
  - 忽略 `.superpowers/`，用于保存子任务驱动开发的临时进度账本、任务简报和审查包。
  - 在隔离工作树中运行完整基线测试，146 项全部通过。
- 修改原因：避免覆盖主工作区已有未提交修改，并让长任务在上下文压缩后仍可从进度账本恢复。
- 如何运行：使用主项目虚拟环境运行 `..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v`。
- 生成的输出文件：仅生成被 Git 忽略的测试临时目录和子任务进度文件；未生成论文 PDF。
- 如何检查是否成功：`git branch --show-current` 应为 `codex/zotero-paper-download`，完整测试显示 `Ran 146 tests ... OK`。
- 注意事项或潜在风险：主工作区未提交修改保持不变；本次未自动重新打包项目。

## 2026-07-10 17:36:56 +08:00

- 本次任务目标：移除所有活跃工作流中的影子文献库自动下载回退，为后续授权的 Zotero 回退阶段保留明确失败记录。
- 新增、修改或删除的文件：
  - 删除 `paper_automation/scihub_fallback.py`
  - 修改 `paper_automation/workflow.py`、`sd_institutional_skill.py`、`sd_scraper.py`、`doi_batch_utils.py`、`paper_skill.py`
  - 修改 `tests/test_paper_automation.py`、`tests/test_sd_institutional_skill.py`、`tests/test_doi_batch_utils.py`
  - 修改 `CHANGELOG.md`
- 具体修改内容：删除 `apply_auto_fallback` 包装器及所有活跃调用；OA 工作流失败保留为 `failed` 和 `no_legal_open_pdf`；恢复判定仅接受 `success`；更新 legal OA CLI 描述；新增三个源码/行为安全回归测试。
- 修改原因：避免未经授权的影子文献库下载，并为后续项目优先与 Zotero 授权回退流程提供可追踪的失败记录。
- 如何运行：在隔离工作树运行 `..\\..\\.venv\\Scripts\\python.exe -m unittest tests.test_paper_automation.WorkflowSafetyTests -v`、`..\\..\\.venv\\Scripts\\python.exe -m unittest tests.test_sd_institutional_skill -v`、`..\\..\\.venv\\Scripts\\python.exe -m unittest tests.test_doi_batch_utils -v` 和 `..\\..\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`。
- 生成的输出文件：仅生成 `.codex-test-tmp` 下的临时测试报告；未修改原始输入、现有 PDF 或项目打包文件。
- 如何检查是否成功：安全测试和完整测试套件均为 `OK`，并且源码扫描不再匹配 `Sci-Hub`、`scihub`、`Anna's Archive`、`annas_archive` 或 `apply_auto_fallback`。
- 注意事项或潜在风险：此更改不会下载 OA 失败的文献；这些记录将留待后续经授权的 Zotero 阶段处理。根据 Task 1 范围修正，`sd_scraper.py` 与 `tests/test_doi_batch_utils.py` 已纳入本任务。

## 2026-07-10 17:49:10 +08:00

- 本次任务目标：修复 Task 1 代码审查发现的活跃交接流程遗漏，禁止把遗留 `scihub_downloaded` 状态视为已完成 PDF。
- 新增、修改或删除的文件：修改 `student_handoff.py`、`tests/test_student_handoff.py`、`CHANGELOG.md`，并补充 `.superpowers/sdd/task-1-report.md`。
- 具体修改内容：从 `classify_failure()` 的完成状态集合中移除 `scihub_downloaded`；新增回归测试，要求该遗留状态归类为“可重试 PDF 失败”。
- 修改原因：`sd_institutional_skill.py` 和 `sd_scraper.py` 都调用学生交接生成器，遗留状态分支违反“每个活跃工作流均不得保留影子文献库行为”的约束。
- 如何运行：`..\\..\\.venv\\Scripts\\python.exe -m unittest tests.test_student_handoff -v`；`..\\..\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`。
- 生成的输出文件：测试仅在 `.codex-test-tmp` 下生成临时交接表；未修改原始输入、现有 PDF 或打包产物。
- 如何检查是否成功：新增测试先 RED（实际“已完成”，期望“可重试 PDF 失败”），修复后焦点套件 3 项通过，完整套件 `Ran 151 tests ... OK`，扩展活跃源码扫描无匹配。
- 注意事项或潜在风险：旧报告中的 `scihub_downloaded` 记录现在会显示为待处理项，供后续授权 Zotero 阶段复核；本次未重新打包项目。

## 2026-07-10 17:59:47 +08:00

- 本次任务目标：完成 Task 2，建立批量下载工作流的批次路径、可恢复状态、PDF 响应校验和安全复制基础。
- 新增、修改或删除的文件：新增 `paper_automation/batch_workflow.py`、`tests/test_batch_workflow.py`；修改 `CHANGELOG.md`；补充 `.superpowers/sdd/task-2-report.md`。
- 具体修改内容：新增 `BatchPaths` 和 `create_batch_paths()` 创建独立的 `paper_batch_YYYYMMDD_HHMMSS` 目录及 `pdfs/reports/working` 子目录；新增原子写入/读取 `batch_state.json`；新增基于最小文件大小和 `%PDF-` 文件头的 PDF 校验；新增 SHA-256 去重复制，避免覆盖不同内容并保留原始源文件。
- 修改原因：为后续 Task 3–Task 任务提供不依赖临时路径的可复用批次文件系统和 durable state 基础，并拒绝把登录页等 HTML 响应当作 PDF 保存。
- 如何运行：在本隔离 worktree 中设置 `TEMP`/`TMP` 为 `.codex-test-tmp`，运行 `..\\..\\.venv\\Scripts\\python.exe -m unittest tests.test_batch_workflow.BatchFileTests -v`；再运行 `..\\..\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`。
- 生成的输出文件：仅在 `.codex-test-tmp` 中生成临时测试输出；未修改原始实验数据、现有 PDF 或项目打包文件。
- 如何检查是否成功：聚焦测试 `Ran 3 tests ... OK`；完整套件 `Ran 154 tests ... OK`；`git diff --check` 无输出；代码实现提交为 `432a437`。
- 注意事项或潜在风险：`copy_pdf_safely()` 的 `filename` 参数应由调用方提供安全的文件名；本 Task 仅按 brief 实现 PDF 头校验、非破坏复制和内容去重，不负责文件名策略。状态文件损坏时会由 JSON 解析异常显式暴露，便于上层报告和恢复流程处理。

## 2026-07-10 18:16:04 +08:00

- 本次任务目标：执行 Task 2 修复波次，封闭批次目录名和 PDF 目标文件名的路径逃逸风险，并保证同时间戳批次及多重文件名冲突永不复用、永不覆盖。
- 新增、修改或删除的文件：修改 `paper_automation/batch_workflow.py`、`tests/test_batch_workflow.py`、`CHANGELOG.md`，并追加 `.superpowers/sdd/task-2-report.md`；未修改其他模块或 `__init__` 文件。
- 具体修改内容：将 `run_name` 作为安全前缀处理，清理空白并始终追加 `YYYYMMDD_HHMMSS`；拒绝绝对路径、驱动器、`..`、路径分隔符、控制字符、Windows 非法字符和保留设备名；使用排他目录创建并在同秒冲突时递增 `_2`、`_3`；对 `copy_pdf_safely()` 的 `filename` 应用单路径组件校验；使用排他文件写入，目标冲突时按内容哈希和数字后缀寻找唯一名称，相同内容复用，任何不同内容文件均不覆盖。
- 修改原因：原实现会直接使用 `run_name` 和 `filename`，可逃逸预期目录；同一时间戳会复用旧批次；首个哈希候选已存在时 `shutil.copy2()` 会覆盖该文件。
- 如何运行：先设置 `TEMP`/`TMP` 为工作树 `.codex-test-tmp`；聚焦测试运行 `..\\..\\.venv\\Scripts\\python.exe -m unittest tests.test_batch_workflow.BatchFileTests -v`；语法检查运行 `..\\..\\.venv\\Scripts\\python.exe -m compileall paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation`；完整测试运行 `..\\..\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`。
- 生成的输出文件：测试仅在被忽略的 `.codex-test-tmp` 下生成临时目录、PDF、CSV、JSON 和报告；未修改原始文献清单、现有 PDF 或 Zotero 附件，未重新打包项目。
- 如何检查是否成功：修复前聚焦套件 `Ran 9 tests`，出现 12 个预期断言失败；修复后 `Ran 9 tests in 0.057s ... OK`；compileall 退出码 0；完整套件 `Ran 160 tests in 7.415s ... OK`；`git diff --check` 无空白错误；实现提交为 `41cbcca`。
- 注意事项或潜在风险：更严格的安全规则会拒绝包含 `..`、分隔符、Windows 非法字符或保留设备名的旧自定义名称；PDF 有效性仍按 Task 2 约定使用最小大小和 `%PDF-` 文件头，而不是完整 PDF 结构解析；本次未执行真实网络、机构登录或 Zotero 下载。

## 2026-07-10 18:43:23 +08:00

- 本次任务目标：执行 Task 2 第二修复波次，解决批次状态并发写入与一次性人工重试 claim 的跨进程竞态，补齐 Windows 上标设备名校验，并消除 PDF 源文件验证后再次读取的 TOCTOU 风险。
- 新增、修改或删除的文件：修改 `paper_automation/batch_workflow.py`、`tests/test_batch_workflow.py`、`CHANGELOG.md`，并追加 `.superpowers/sdd/task-2-report.md`；未修改 Task 3+ 文件或 `__init__` 文件。
- 具体修改内容：状态保存改为同目录唯一临时文件，完整写入后执行 `flush`、`os.fsync` 和原子 `os.replace`，异常清理自身临时文件，并对 Windows 同目标 replace 的短暂共享冲突做最多 2 秒有界重试；新增基于 `msvcrt.locking`（非 Windows 使用 `fcntl.flock`）的 `batch_state_lock()`，默认 10 秒超时、异常安全释放且不静默绕过；新增 `claim_manual_retry()`，在同一把锁内完成 load→检查→置位→durable save，保证两个进程只有一个能 claim；`COM¹/²/³` 与 `LPT¹/²/³` 现在同时被 run_name 和 filename 拒绝；PDF 复制先把源单次读取到目标目录唯一快照并同步落盘，在该稳定快照上验证、计算哈希、去重和排他复制，最后清理快照。
- 修改原因：固定 `batch_state.json.tmp` 会让并发保存共享并争用同一临时路径；仅原子替换单个文件不能保护 `manual_retry_used` 的多步读改写；Windows 还保留上标数字设备名；旧 PDF 流程在验证/哈希后重新打开源文件，源被替换或截断时会把未验证内容写入目标。
- 如何运行：先设置 `TEMP`/`TMP` 为工作树 `.codex-test-tmp`；聚焦测试运行 `..\\..\\.venv\\Scripts\\python.exe -m unittest tests.test_batch_workflow.BatchFileTests -v`；语法检查运行 `..\\..\\.venv\\Scripts\\python.exe -m compileall paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation`；完整测试运行 `..\\..\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`；格式检查运行 `git diff --check`。
- 生成的输出文件：测试仅在被忽略的 `.codex-test-tmp` 下生成临时锁文件、状态 JSON、PDF 快照和报告；未修改原始文献清单、现有 PDF、Zotero 附件或真实下载结果，未重新打包项目。
- 如何检查是否成功：修复前聚焦套件 `Ran 17 tests`，出现 18 个预期断言失败；修复后 `Ran 17 tests in 1.191s ... OK`；compileall 退出码 0；完整套件 `Ran 168 tests in 7.633s ... OK`；`git diff --check` 无空白错误；实现提交为 `caed578`。
- 注意事项或潜在风险：Task 4 的 `resume_batch()` 必须使用 `claim_manual_retry()`，不得自行无锁执行 load→check→save，也不应在网络重试期间长期持有 `batch_state_lock()`；独立 `save_batch_state()` 的并发语义是“每个快照完整、最后写入者生效”，不是多字段合并；锁标记文件会保留但 OS 字节锁会随上下文、异常或进程退出释放；PDF 仍仅做最小大小和 `%PDF-` 文件头校验；本次未执行真实网络、机构登录或 Zotero 测试。

## 2026-07-10 19:03:56 +08:00

- 本次任务目标：执行 Task 2 第三修复波次，消除 `copy_pdf_safely()` 直接写正式 `.pdf` 导致的半成品可见、同内容并发产生重复文件和进程崩溃遗留损坏正式文件问题。
- 新增、修改或删除的文件：
  - 修改 `paper_automation/batch_workflow.py`。
  - 修改 `tests/test_batch_workflow.py`。
  - 修改 `CHANGELOG.md`，追加本记录。
  - 追加 `.superpowers/sdd/task-2-report.md`。
  - 未修改 Task 3+ 文件、`__init__` 文件、原始输入、现有 PDF 或 Zotero 附件。
- 具体修改内容：
  - 把现有 Windows `msvcrt.locking` / POSIX `fcntl.flock` 逻辑抽取为共用、不可重入、带超时且异常安全释放的 `_file_lock()`。
  - 为每个 PDF 目标目录使用非交付物锁标记 `.pdf_publish.lock`；锁覆盖旧快照清理、源文件单次读取、SHA-256 计算、快照 `flush`/`os.fsync`、PDF 校验、候选名复查、去重和发布。
  - 正式文件只通过同一文件系统内的 `os.link(snapshot, candidate)` 排他发布；不再以 `xb` 向正式 `.pdf` 流式写入，也不使用覆盖式替换或降级路径。
  - 崩溃最多留下 `.pdf_snapshot_*.tmp` 私有快照；后续调用取得目录锁后清理失去所有者的快照。正常成功或异常退出均清理自身快照。
  - 新增 `copy_pdf_safely(..., lock_timeout=10.0)` 关键字参数；锁竞争超时抛出 `TimeoutError("pdf_publish_lock_timeout")`，硬链接不支持或失败时抛出包含 `hard_link_publish_failed` 的 `OSError`。
  - 删除锁标记文件首次创建时写入/刷新占位字节的步骤；Windows 可直接锁定零字节文件，避免两个进程同时初始化新锁文件时发生 `PermissionError`。
  - 新增 Windows `spawn` 回归测试，覆盖同内容并发只交付一个有效 PDF、发布前终止不遗留正式残件且后续恢复、发布锁超时、硬链接失败不暴露正式 PDF、不同内容并发得到两个安全唯一结果。测试用 `Event`/`Queue` 控制顺序，不依赖任意 `sleep`。
- 修改原因：旧实现使用 `target.open("xb")` 直接写正式文件；并发进程会把对方的半成品判为无效并生成哈希副本，进程被终止时还可能留下损坏的正式 `.pdf`。完整私有快照加目录锁和硬链接发布把正式名可见性缩短为一次原子、不覆盖的文件系统操作。
- 如何运行：在隔离工作树中设置 `TEMP`/`TMP` 为 `.codex-test-tmp`，然后运行：
  - `..\..\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchFileTests -v`
  - `..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  - `..\..\.venv\Scripts\python.exe -m compileall paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation`
  - `git diff --check`
- 生成的输出文件：自动测试只在被忽略的 `.codex-test-tmp` 中生成临时锁、私有快照、PDF 和报告；未联网下载论文，未打包项目。
- 如何检查是否成功：初始 RED 为 `Ran 22 tests ... FAILED (failures=4)`；修复后聚焦测试为 `Ran 22 tests in 2.520s ... OK`，完整套件为 `Ran 173 tests in 11.470s ... OK`，`compileall` 退出码为 0。不同内容并发用例在修正锁初始化竞态后连续 30 次通过。
- 注意事项或潜在风险：
  - 目标文件系统必须支持并允许同目录硬链接；不支持时函数会明确失败且不生成正式 PDF，不会回退到不安全的直接写入。
  - 为保证崩溃清理不误删活跃快照，同一目标目录的快照创建也在目录锁内，因此大 PDF 会串行复制，并可能需要调用方调大 `lock_timeout`。
  - PDF 有效性仍按 Task 2 约定只检查最小大小和 `%PDF-` 文件头，不执行完整 PDF 结构解析。
  - 硬链接目录项在突然断电时的持久性由操作系统和文件系统保证；本实现已在发布前 `fsync` 完整快照，但 Windows 没有额外执行目录句柄 `fsync`。

## 2026-07-10 19:18:53 +08:00

- 本次任务目标：执行 Task 2 第四修复波次，只修复 PDF 目标 symlink 被错误复用，以及文件锁接受 `nan`/无穷 timeout 两项审查发现。
- 新增、修改或删除的文件：
  - 修改 `paper_automation/batch_workflow.py`。
  - 修改 `tests/test_batch_workflow.py`。
  - 修改 `CHANGELOG.md`，追加本记录。
  - 追加 `.superpowers/sdd/task-2-report.md`。
  - 未修改 Task 3+ 文件、`__init__` 文件、原始输入、现有 PDF 或 Zotero 附件。
- 具体修改内容：
  - `_same_pdf_content()` 在验证或哈希前先检查 `Path.is_symlink()`；只有非 symlink 且通过 PDF 文件校验的常规文件才允许按相同 SHA-256 内容复用。
  - requested target、首个哈希候选和后续数字候选继续共用同一复用 helper；任何 symlink 均作为不可修改的占位冲突保留，并继续寻找安全后缀，通过既有硬链接原子发布独立 PDF。
  - `_file_lock()` 使用 `math.isfinite()`，只接受 finite 且大于等于 0 的 timeout；负数、`nan`、`+inf`、`-inf` 均在打开/等待锁之前抛出对应 `ValueError`。
  - `batch_state_lock()` 保持 `invalid_batch_state_lock_timeout`，`copy_pdf_safely()` 保持 `invalid_pdf_publish_lock_timeout`。
  - 新增永不跳过的 mocked `is_symlink()` 逻辑测试；新增真实 file symlink 端到端测试，在明确权限/平台不支持时才 skip；新增 state/PDF 两组四值 timeout 参数测试。
- 修改原因：`Path.is_file()`、文件打开和哈希默认跟随 symlink，旧实现会返回指向目标目录外附件的链接；`nan < 0` 与 `+inf < 0` 都为假，旧 timeout 校验会让这两个无效值进入甚至成功取得锁。
- 如何运行：先把 `TEMP`/`TMP` 设置为隔离工作树 `.codex-test-tmp`，然后运行：
  - `..\..\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchFileTests -v`
  - `..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  - `..\..\.venv\Scripts\python.exe -m compileall paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation`
  - `git diff --check`
- 生成的输出文件：测试仅在被忽略的 `.codex-test-tmp` 下生成临时目录、锁、快照和 PDF；未联网下载论文，未修改真实附件，未打包项目。
- 如何检查是否成功：初始 RED 为 `Ran 26 tests in 2.367s`、`FAILED (failures=5, skipped=1)`；修复后聚焦测试为 `Ran 26 tests in 2.569s ... OK (skipped=1)`；完整套件为 `Ran 177 tests in 10.606s ... OK (skipped=1)`；`compileall` 退出码为 0，`git diff --check` 无空白错误。
- 注意事项或潜在风险：
  - 当前 Windows 环境创建真实 file symlink 返回 `WinError 1314`，因此端到端 symlink 测试按要求跳过；mocked 核心逻辑测试始终执行并通过。
  - symlink 占位不会被删除、改写或作为交付路径返回；这可能使已有旧命名被跳过并产生哈希/数字后缀，这是预期安全行为。
  - PDF 仍只按最小大小和 `%PDF-` 文件头校验；硬链接支持、同目录串行复制与断电持久性风险保持第三波次记录不变。

## 2026-07-10 19:36:57 +08:00

- 本次任务目标：完成 Task 3，将合法 OA、ScienceDirect 和非 Elsevier 机构访问下载阶段归一化为一致的批次结果接口。
- 新增、修改或删除的文件：
  - 新增 `paper_automation/batch_stages.py`。
  - 修改 `tests/test_batch_workflow.py`（仅增加 `BatchStageTests`）。
  - 修改 `CHANGELOG.md`；新增忽略的 `.superpowers/sdd/task-3-report.md`。
- 具体修改内容：
  - 新增 `BatchOptions`、`StageResult`、`split_institutional_rows()`、`needs_manual_retry()` 和 UTF-8-SIG 的 `write_stage_input()`。
  - 新增三个薄适配器：OA 直接调用 `workflow.run_workflow()`；ScienceDirect 直接调用可 patch 的 `sd_institutional_skill.main()`，固定 `--run-name sciencedirect` 与 `--no-download-supplements`；非 Elsevier 直接调用 `institutional.run_institutional_workflow()`。
  - 按现有 OA manifest、`pdf_download_report.csv` 和 `institutional_pdf_download_report.csv` 映射报告，保持输入顺序和 `task_id`；缺失报告、缺失行、返回码和异常均生成可诊断的失败结果。
  - 只有存在、非 symlink、可读且通过 Task 2 `is_valid_pdf()` 校验的本地 PDF 才映射为 `downloaded`；HTML、空文件、缺失文件或 symlink 会记录 `invalid_pdf`，且不移动、不删除源文件。
  - 实现 `10.1016/` 路由至 ScienceDirect，空 DOI 和其他出版社路由至非 Elsevier；人工重试仅识别明确的 auth/login/captcha/turnstile 信号。
- 修改原因：为 Task 4 批次恢复流程提供一个无网络副作用、可追踪且不会将登录页误报为 PDF 成功的统一边界。
- 如何运行：在本隔离 worktree 中设置 `TEMP`/`TMP` 为 `.codex-test-tmp`，然后运行：
  - `..\..\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchStageTests -v`
  - `..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  - `..\..\.venv\Scripts\python.exe -m compileall paper_automation`
  - `git diff --check`
- 生成的输出文件：测试仅在忽略的 `.codex-test-tmp` 中产生临时 CSV/PDF 固件；未联网下载，未读取或记录 cookie 内容，未修改原始文献或已有 PDF，也未打包项目。
- 如何检查是否成功：聚焦测试显示 `Ran 12 tests ... OK (skipped=1)`；完整套件显示 `Ran 189 tests ... OK (skipped=2)`；`compileall` 和 `git diff --check` 退出码应为 0。
- 注意事项或潜在风险：
  - 当前 `sd_institutional_skill` CLI 没有 `debug-port` 或 `throttle` 参数，适配器不传递未被支持的参数，以避免真实 ScienceDirect 调用因 argparse 失败；这两个参数已正确传给支持它们的非 Elsevier 工作流。
  - 本机 Windows 未授予创建 file symlink 的权限（`WinError 1314`），所以端到端 symlink 测试被跳过；适配器仍在逻辑上显式拒绝 symlink。

## 2026-07-10 20:00:59 +08:00

- 本次任务目标：执行 Task 3 复审修复波次，修复三阶段相对 PDF 路径、OA `source_index` 映射、ScienceDirect 部分报告与非零返回码并存、以及规范重复输入四类问题。
- 新增、修改或删除的文件：
  - 修改 `paper_automation/batch_stages.py`。
  - 修改 `tests/test_batch_workflow.py`，仅扩展 `BatchStageTests`。
  - 追加 `CHANGELOG.md` 和被 Git 忽略的 `.superpowers/sdd/task-3-report.md`。
  - 未修改 Task 4+ 文件、已有下载器实现、原始输入或项目打包文件。
- 具体修改内容：
  - `_map_report()` 现在显式接收 `pdf_base_dir`。OA 相对文件按 `workflow_result.output_dir/pdfs` 解析；该属性缺失、空或为 `None` 时，按实际 manifest 运行目录的 `pdfs` 回退；ScienceDirect 和非 Elsevier 均按报告目录下的 `pdfs` 解析。
  - 相对 PDF 返回解析后的稳定绝对路径；包含 `..` 或 symlink 且会逃逸阶段 `pdfs` 根目录的路径被拒绝。绝对路径保持原路径语义，但仍必须是非 symlink、常规可读文件并通过 Task 2 `is_valid_pdf()`。
  - OA 按 parser 的 1-based `source_index` 为真正传入 parser 的非空 owner 行建立映射；报告优先按 `source_index` 精确匹配，再使用项目现有 `clean_doi()` 与规范标题降级，支持 DOI URL、元数据标题替换和乱序报告。
  - ScienceDirect 非零返回码不再先整体短路：报告存在时先映射已有成功或真实失败行，仅缺失行使用 `stage_exit_code_N`；报告完全缺失时仍全部记录该返回码。
  - 三阶段在调用下层前按规范 DOI、无 DOI 时按规范标题识别重复，只把第一个 owner 传给现有下载器；重复项按原输入顺序返回 `status=duplicate`、`reason=duplicate_stage_input`、空文件路径和正确 source。机构阶段仅在存在重复时于 `output_dir/working/` 写 UTF-8-SIG 去重阶段输入，不覆盖原输入。
- 修改原因：真实项目报告通常只保存 PDF 文件名而非绝对路径；OA 报告标题和 DOI 可能在元数据解析后变化；ScienceDirect 可能在部分成功落盘后返回非零；下层去重会使重复输入只产生一条报告。旧适配器分别会误报 `invalid_pdf`、错配/漏配任务、丢失部分成功、或把重复项误报为缺失报告行。
- 如何运行：在隔离 worktree 中设置 `$env:TEMP=(Resolve-Path .codex-test-tmp); $env:TMP=$env:TEMP`，然后运行：
  - `..\..\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchStageTests -v`
  - `..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  - `..\..\.venv\Scripts\python.exe -m compileall paper_automation`
  - `git diff --check`
- 生成的输出文件：测试只在被忽略的 `.codex-test-tmp` 中生成临时报告、PDF 固件和去重阶段 CSV；正式运行遇到重复机构输入时会生成 `working/sciencedirect_stage_input.csv` 或 `working/non_elsevier_stage_input.csv`。未联网、未读取或记录 cookie 内容、未移动/删除源 PDF、未打包项目。
- 如何检查是否成功：修复后聚焦测试为 `Ran 23 tests ... OK (skipped=1)`；完整套件为 `Ran 200 tests ... OK (skipped=2)`；`compileall paper_automation` 和 `git diff --check` 退出码均为 0。
- 注意事项或潜在风险：
  - Task 2 `is_valid_pdf()` 仍按最小字节数和 `%PDF-` 文件头校验，不执行完整 PDF 结构解析。
  - 当前 Windows 环境无法创建真实 file symlink（`WinError 1314`），端到端测试继续跳过；不依赖权限的 mocked symlink-before-resolve 测试已执行并通过。
  - 适配器只清理自身的逻辑输入，不删除原始输入、报告或 PDF；重复阶段 CSV 为可诊断中间文件，后续重复运行会更新同一批次的对应阶段 CSV。

## 2026-07-10 22:18:07 +08:00

- 本次任务目标：执行 Task 3 第二修复波次，拒绝单行多 DOI 阶段输入，并加固绝对 PDF 路径规范化、机构报告行号匹配和缺失报告路径处理。
- 新增、修改或删除的文件：
  - 修改 `paper_automation/batch_stages.py`。
  - 修改 `tests/test_batch_workflow.py`，仅扩展 `BatchStageTests`。
  - 追加 `CHANGELOG.md` 和被 Git 忽略的 `.superpowers/sdd/task-3-report.md`。
  - 未修改 Task 4 代码、Task 4 brief、现有下载器实现、原始输入或项目打包文件。
- 具体修改内容：
  - 使用项目现有 `parser.extract_dois()` 检测每个阶段输入行；一个输入行含多个不同 DOI 时不调用任何下层，按原位置返回 `failed / multiple_dois_in_stage_input`，并与 owner/duplicate 布局共同保持数量、顺序和 `task_id`。
  - 所有绝对报告 PDF 路径均先执行 `expanduser().resolve()`；含 `..` 的路径和祖先 junction/reparse 路径统一返回最终规范绝对目标，再要求该最终目标是非 symlink、常规可读且通过 Task 2 `is_valid_pdf()` 的 PDF。
  - `write_stage_input()` 生成的 CSV 报告 `row_number` 降级匹配仅接受 `index + 2`；伪造的 `index + 1` 不再消费错误报告行。
  - OA 的 `manifest_csv` 与非 Elsevier 的 `report_path` 对 `None`、空字符串和属性缺失统一返回 `failed / stage_report_missing`，不再把 `Path('')` 当作当前目录或抛出 `TypeError`。
  - Task 3 继续显式返回 `duplicate / duplicate_stage_input`，不伪装下载成功；跨任务契约由已更新的 Task 4 brief 约束其为终态，禁止写入 `manual_retry` 或 `zotero_fallback`。
- 修改原因：旧适配器可能把同一源行解析出的两个 DOI交给下层并丢失一对一任务语义，保留未规范化绝对路径，按错误的 CSV 行号消费报告，或在报告路径为空时异常退出；这些行为会破坏 Task 4 的复制与恢复流程。
- 如何运行：在隔离 worktree 中先设置 `$env:TEMP=(Resolve-Path .codex-test-tmp); $env:TMP=$env:TEMP`，然后运行：
  - `..\..\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchStageTests -v`
  - `..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  - `..\..\.venv\Scripts\python.exe -m compileall paper_automation`
  - `git diff --check`
- 生成的输出文件：测试只在被忽略的 `.codex-test-tmp` 中生成临时 CSV、报告、PDF 固件和 junction；未进行真实网络、机构登录、cookie 读取或论文下载，未移动/删除源 PDF，未重新打包项目。
- 如何检查是否成功：本波次最终聚焦测试为 `Ran 29 tests in 0.691s ... OK (skipped=1)`，其中真实 junction 端到端测试通过；完整套件为 `Ran 206 tests in 12.460s ... OK (skipped=2)`；`compileall paper_automation` 和 `git diff --check` 退出码均为 0。
- 注意事项或潜在风险：
  - Task 2 `is_valid_pdf()` 仍只检查最小字节数和 `%PDF-` 文件头，不执行完整 PDF 结构解析。
  - 当前 Windows 账户创建 file symlink 返回 `WinError 1314`；因此真实 file-symlink 测试按条件跳过。junction 端到端测试会实际尝试创建目录 junction，失败时跳过；另有不依赖权限且始终运行的 mocked `resolve()` 最终目标语义测试。
  - Task 3 只负责把多 DOI 单行显式标记失败；Task 4 必须在标准化阶段将它展开为独立 `task_id`，并把 `duplicate` 当作不进入人工重试或 Zotero 回退的终态。

## 2026-07-10 22:45:37 +08:00

- 本次任务目标：实现 Task 4 的批次启动与一次性人工重试工作流，连接既有输入整理、OA、ScienceDirect 和非 Elsevier 阶段，同时保持 PDF、状态和待处理清单可追溯。
- 新增、修改或删除的文件：`paper_automation/batch_workflow.py`、`tests/test_batch_workflow.py`、`CHANGELOG.md`，以及 Git 忽略的 `.superpowers/sdd/task-4-report.md`；未修改 `paper_automation/batch_stages.py`、Task 5+ 文件、原始输入、既有 PDF 或打包内容。
- 具体修改内容：新增 `BatchRunResult`、`NORMALIZED_FIELDS`、输入标准化、默认阶段网关、`start_batch()`、`resume_batch()` 和最小 CSV/JSON 状态报告。输入通过 `build_intake(resolve_metadata=True, resolve_title_only_files=True, min_confidence=0.65)` 支持文本与 TXT/MD/CSV/XLSX/XLSM；多 DOI 在阶段前展开为独立 `paper-0001...`，未解析题名保持 `metadata_uncertain`。CSV 统一 UTF-8-SIG 固定字段顺序；阶段只按 `task_id` 合并，成功 PDF 使用 `copy_pdf_safely()` 复制。状态持久化安全的 `BatchOptions` 值（Cookie 仅路径）；恢复使用 `claim_manual_retry()` 原子领取且不在网络重试期间持锁。
- 修改原因：提供不覆盖原始输入、可恢复、对机构登录/验证码失败可诊断且只重试一次的工作流，避免以 DOI 或题名猜测任务对应关系。
- 如何运行：设置 `TEMP`/`TMP` 为 `.codex-test-tmp` 后执行 `..\\..\\.venv\\Scripts\\python.exe -m unittest tests.test_batch_workflow.BatchRunTests -v`、`..\\..\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`、`..\\..\\.venv\\Scripts\\python.exe -m compileall paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation` 和 `git diff --check`。
- 生成的输出文件：实际批次生成 `working/normalized_input.csv`、`working/batch_state.json`、`working/manual_retry.csv`、`working/zotero_fallback.csv`、`pdfs/*.pdf` 与最小 `reports/batch_status.csv`/`batch_status.json`；测试临时文件仅位于忽略的 `.codex-test-tmp`。
- 如何检查是否成功：聚焦测试覆盖 OA 优先路由、多 DOI 展开、重复项排除、绝对 PDF 安全复制、配置恢复、原子领取、未知任务拒绝和原文件不变；全套测试、编译和差异检查结果见 Task 4 report。
- 注意事项或潜在风险：PDF 有效性沿用 Task 2 的最小大小与 `%PDF-` 文件头检查，不做完整 PDF 结构解析；未在离线测试中访问真实机构权限、浏览器登录或 Cookie 内容；Task 4 仅生成最小状态报告，未提前实现 Task 5 Zotero 对账。

## 2026-07-10 23:17:41 +08:00

- 本次任务目标：继续 Task 4 复审修复，补齐多格式表格多 DOI 展开、严格 metadata 状态路由、规范成功状态、锁内预检后原子领取、配置安全校验，以及网关阶段的行级隔离和断点持久化。
- 新增、修改或删除的文件：修改 `paper_automation/batch_workflow.py`、`tests/test_batch_workflow.py`、`CHANGELOG.md`；追加 Git 忽略的 `.superpowers/sdd/task-4-report.md`。未修改 `batch_stages.py`，未实现 Task 5，也未修改、覆盖或移动任何原始文献输入与既有 PDF。
- 具体修改内容：
  - `normalize_input()` 使用 `paper_automation.parser.extract_dois()` 从 intake 的 `raw_value`、`input_doi` 和 `doi` 重新提取完整 DOI 集；CSV/XLSX/XLSM/TXT/MD 单记录多 DOI 全部展开、全局规范去重后再生成固定 `paper-0001...`。
  - 只有 `intake.status=valid` 且有 DOI 的行进入 `pending`；其他行保留为 `metadata_uncertain` 并保留原因。默认网关只处理 `pending`，不再把低置信或空 DOI 行送入 OA/机构阶段。
  - 成功 PDF 统一写为 `oa_downloaded` 或 `institutional_downloaded`，并与 Task 5 约定的成功状态集合兼容；未知来源的 generic `downloaded` 转为 `invalid_download_source`。
  - 无效、缺失、symlink 或非 PDF 成功文件转为行级 `not_pdf_response`，不会中断其他任务。空/漏网关更新转为 `missing_stage_update`；start/resume 网关异常转为 `gateway_exception_<Type>` 并继续生成 pending 与报告。
  - `DefaultStageGateway` 新增可选 `on_updates` 回调，OA、ScienceDirect、非 Elsevier 各阶段结果到达即逐行保存；使用 `inspect.signature()` 保持既有三参数 FakeGateway 兼容，回调与最终返回重复时不回退终态。
  - `claim_manual_retry()` 新增向后兼容的 `validate_before_claim`；resume 在同一状态锁内完成 state/options/manual CSV 字段、task_id 子集和实际人工状态校验，通过后才写 `manual_retry_used=True`，网络阶段不持锁。
  - Cookie 配置只允许空值或 `.json` 路径形式，拒绝 Header、键值、分号、JSON 文本、CR/LF 与 URL；等待时间、端口和节流值执行严格类型、范围与有限性检查。JSON 状态写入启用 `allow_nan=False`。
- 修改原因：复审确认旧实现会截断表格多 DOI、误下载不确定元数据、把 generic `downloaded` 当终态、在预检失败前消耗唯一重试，并让单行 PDF/网关故障中断整批。
- 如何运行：在隔离工作树将 `TEMP`/`TMP` 指向 `.codex-test-tmp`，运行 `..\\..\\.venv\\Scripts\\python.exe -m unittest tests.test_batch_workflow.BatchRunTests -v`、`..\\..\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`、`..\\..\\.venv\\Scripts\\python.exe -m compileall paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation` 和 `git diff --check`。
- 生成的输出文件：测试只在忽略的 `.codex-test-tmp` 生成临时输入、批次状态、pending CSV、报告和 PDF 副本；正式运行仍生成 `working/normalized_input.csv`、`batch_state.json`、`manual_retry.csv`、`zotero_fallback.csv`、`reports/batch_status.*` 与 `pdfs/*.pdf`。
- 如何检查是否成功：聚焦测试覆盖真实 CSV/XLSX/XLSM/TXT/MD 多 DOI及原文件字节不变、低置信路由、成功状态、invalid PDF、空/漏更新、异常与 OA 断点、preclaim 失败不消耗、并发单领取、Cookie/数值安全和状态拒绝 NaN；最终测试计数见 Task 4 report。
- 注意事项或潜在风险：PDF 有效性仍沿用 Task 2 的最小大小与 `%PDF-` 文件头校验，不是完整 PDF 结构解析；真实机构登录、Cookie 文件读取、网络下载和 Zotero 对账均未在本轮离线测试中执行；Cookie 路径要求 `.json` 后缀但不要求文件当前已存在。

## 2026-07-10 23:41:28 +08:00

- 本次任务目标：完成 Task 4 第三修复波次，仅修复表格 DOI 来源隔离、callback-only 状态持久化、manual retry 严格集合与空清单语义，以及已使用 retry 后仍必须执行的批次状态校验。
- 新增、修改或删除的文件：
  - 修改 `paper_automation/batch_workflow.py`。
  - 修改 `tests/test_batch_workflow.py`，仅扩展 `BatchRunTests`。
  - 追加 `CHANGELOG.md` 和被 Git 忽略的 `.superpowers/sdd/task-4-report.md`。
  - 未修改 `paper_automation/batch_stages.py`，未实现 Task 5，也未修改原始输入、PDF 或打包产物。
- 具体修改内容：
  - CSV/TSV/XLSX/XLSM 在调用 intake 前读取表头和表格记录，按原始 `row_number` 绑定明确 DOI 单元格；仅从该单元格展开 DOI，空 DOI 单元格或无 DOI 列时不再从 title/authors/raw_value 提取引用 DOI。合法的 title-only 元数据解析结果仍可在 `input_doi` 为空且 intake 为 `valid` 时进入下载。
  - 对 title 引用 DOI 被 intake 误认成 `input_doi` 的表格行写入 `metadata_uncertain / doi_not_from_doi_column`，不送入 OA 或机构阶段；明确 DOI 单元格的多 DOI 仍在全局去重后生成确定的 `paper-0001...`。
  - 网关执行器记录 callback 已成功持久化的 `task_id`，最终返回空列表时不再把 callback-only 的 captcha、no-open 或机构成功结果覆盖成 `missing_stage_update`。
  - `claim_manual_retry()` 向后兼容新增总是执行的 `validate_state` callback，并允许 `validate_before_claim` 返回 `False` 原子取消 claim。`resume_batch()` 即使 retry 已使用也校验 state、保存配置和规范 `run_dir`；未使用时才校验 manual CSV 和 override options。
  - manual CSV 的 task ID 集合必须与 state 中当前全部 manual 条件行完全相等，且每行 status 必须匹配；缺失、额外、重复、状态不符或 captcha state 对应空 CSV 均不消耗 retry。state 与 CSV 均为空时不 claim、不改 pending 文件、不调用网关。
- 修改原因：复审确认表格题名中的参考 DOI 可能被误当目标下载，callback-only 非终态会被缺失更新覆盖，且旧 claim 早退顺序无法保证已使用 retry 的损坏 state 被诊断；manual CSV 子集校验也可能漏重试或错误消耗一次性 claim。
- 如何运行：先在隔离 worktree 中设置 `$env:TEMP=(Resolve-Path .codex-test-tmp); $env:TMP=$env:TEMP`，再运行 `python -m unittest tests.test_batch_workflow.BatchRunTests -v`、`python -m unittest discover -s tests -v`、`python -m compileall paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation` 和 `git diff --check`。
- 生成的输出文件：测试只在被忽略的 `.codex-test-tmp` 下生成临时 CSV、XLSX/XLSM、批次 state、pending 文件、报告与 PDF fixture；正式流程输出接口未变化，未生成真实下载或 Zotero 对账结果。
- 如何检查是否成功：严格 TDD 红灯阶段新增用例出现 11 个预期失败和 1 个缺失签名错误，status 精确匹配反例另行先红；修复后聚焦测试 `Ran 38 tests ... OK`，全套离线测试 `Ran 244 tests ... OK (skipped=2)`，全项目 `compileall` 退出码 0，最终 `git diff --check` 应无空白错误。
- 注意事项或潜在风险：title-only DOI 的接受依赖现有 intake 契约（`input_doi` 为空、`status=valid`、解析 `doi` 非空）；PDF 有效性仍沿用 Task 2 的最小大小与 `%PDF-` 文件头校验；本轮未访问网络、机构登录、Cookie 内容或 Zotero，未重新打包项目。

## 2026-07-11 00:11:05 +08:00 — Task 5 Zotero reconciliation

- Goal: add safe local Zotero-result reconciliation and stable final reports.
- Files: modified `paper_automation/batch_workflow.py` and `tests/test_batch_workflow.py`; appended `CHANGELOG.md`; added `.superpowers/sdd/task-5-report.md`. Task 6 CLI, Task 7 MCP, source inputs, Zotero attachments, and packages were not modified.
- Changes: strict UTF-8-SIG CSV/header/task-ID validation precedes every state mutation; only local regular valid PDFs are copied with `copy_pdf_safely()`; source attachments remain untouched and same-content copies are reused.
- Reports: `final_manifest.csv`, `final_manifest.xlsx`, `failed.csv`, and `run_summary.txt` use stable ordering; XLSX text is written as text and report files are written through temporary files before replacement.
- Metadata policy: a `metadata_uncertain` row may retain a usable Zotero PDF, but its `reason` keeps a `metadata_uncertain` audit marker; no DOI or title is invented.
- Run: set `TEMP` and `TMP` to `.codex-test-tmp`, then run `..\\..\\.venv\\Scripts\\python.exe -m unittest tests.test_batch_workflow.BatchFinalizeTests -v`, `..\\..\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`, `..\\..\\.venv\\Scripts\\python.exe -m compileall paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation`, and `git diff --check`.
- Outputs: final reports are inside each batch `reports/` directory; test artifacts remain in ignored `.codex-test-tmp/`.
- Verification: Task 5 focus `Ran 7 tests ... OK`; suite `Ran 251 tests ... OK (skipped=2)`; compile and diff checks exit 0.
- Risks: PDF validation remains the Task 2 magic-header/minimum-size test, not full PDF parsing. No network, institutional login, Cookie read, live Zotero operation, source-file mutation, or repackaging was performed.

## 2026-07-11 03:17:52 +08:00 — Task 5 P1/P2 修复波次

- 本次任务目标：修复 Task 5 审查发现的全部 P1/P2，包括 Zotero 输入状态注入、宽松 CSV、XLSX 未显式关闭/同步、附件路径链 reparse 风险，以及内部报告误入 Git 索引。
- 新增、修改或删除的文件：修改 `paper_automation/batch_workflow.py`、`tests/test_batch_workflow.py`、`CHANGELOG.md`；`.superpowers/sdd/task-5-report.md` 仅从 Git 索引移除，磁盘文件保留且内容未修改；未修改 Task 6 CLI 或 Task 7 MCP。
- 具体修改内容：
  - 为 Zotero 输入增加固定白名单：成功仅允许 `existing_pdf`/`downloaded`；失败允许 `no_pdf`、`not_found`、`metadata_uncertain`、`zotero_unavailable`、`no_attachment`、`download_failed`、`zotero_api_unavailable`。内部状态和未知状态在整体验证阶段统一报 `zotero_result_status_invalid`。
  - Zotero CSV 表头必须与 `ZOTERO_RESULT_FIELDS` 顺序和数量完全一致；额外列、乱序、重复表头、空白行和畸形行在状态变更前整体拒绝。
  - XLSX 在 `save()` 后通过 `finally` 显式 `close()`，随后以 `r+b` 打开临时文件并执行 `flush()`/`os.fsync()`，最后才原子替换正式报告。
  - Zotero 附件路径必须是绝对本地路径；解析前逐级 `lstat()` 检查原始路径链，Windows 拒绝 `FILE_ATTRIBUTE_REPARSE_POINT`，POSIX 拒绝任一 symlink ancestor；通过后返回规范绝对路径并进行普通 PDF 校验。
- 修改原因：旧实现允许任意非空 status 进入内部状态，CSV 只要求包含必要列，XLSX 未保证关闭及持久化顺序，附件只检查最终节点且相对路径语义不稳定。
- 如何运行：
  - `$env:TEMP=(Resolve-Path .codex-test-tmp); $env:TMP=$env:TEMP`
  - `..\..\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchFinalizeTests -v`
  - `..\..\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchRunTests -v`
  - `..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  - `..\..\.venv\Scripts\python.exe -m compileall paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation`
  - `git diff --check`
- 生成的输出文件：正式流程仍输出 `reports/final_manifest.csv`、`final_manifest.xlsx`、`failed.csv` 和 `run_summary.txt`；测试临时产物仅位于忽略的 `.codex-test-tmp/`，未覆盖原输入或 Zotero 附件。
- 如何检查是否成功：Task 5 聚焦测试显示 `Ran 14 tests ... OK`，其中真实 Windows junction 测试实际通过；全套离线测试显示 `Ran 258 tests ... OK (skipped=2)`；编译和差异检查退出码为 0。
- 注意事项或潜在风险：PDF 内容验证仍沿用 Task 2 的 `%PDF-` 文件头和最小大小规则，并非完整结构解析；路径链检查与复制之间仍存在操作系统级极短 TOCTOU 窗口，但复制阶段会再次从源快照校验 PDF。未联网、未访问真实 Zotero、未读取 Cookie、未打包项目。

## 2026-07-11 03:38:57 +08:00 — Task 5 第二修复波次

- 本次任务目标：修复最新 2 个 P1 与 2 个 P2，覆盖报告 CSV 公式注入、批次状态并发覆盖、Zotero 附件 TOCTOU，以及六文件报告集合的部分发布问题。
- 新增、修改或删除的文件：修改 `paper_automation/batch_workflow.py`、`tests/test_batch_workflow.py`、`CHANGELOG.md`；仅在本地追加 `.superpowers/sdd/task-5-report.md`，该文件继续 ignored 且未重新纳入 Git；未修改 Task 6。
- 具体修改内容：
  - `_write_report_csv()` 仅对 CSV 数据单元格执行 Excel 注入转义：若 `lstrip()` 后首字符为 `= + - @`，在原值前添加单引号。CSV 查看时会显示该安全前缀；表头、XLSX 和 state 不变。
  - `_apply_stage_updates()` 使用统一 `batch_state_lock`，锁内重新加载并验证最新 state，逐行 merge/save 后同步调用者 snapshot；`assume_locked=True` 提供内部无嵌套路径。`start_batch()` 初始 state 保存也遵守同一锁协议，gateway 网络调用不持锁。
  - `finalize_batch()` 在锁外预读 CSV，修改前获取同一 state 锁、重新加载最新 state 并重新校验 CSV/task IDs，保护并发产生的 OA/机构成功；报告使用锁内最终 snapshot。
  - `_copy_zotero_attachment()` 在首次路径验证和哈希后，再次执行完整绝对路径/祖先 reparse 检查并重新哈希；规范路径或哈希变化时报 `zotero_attachment_changed`，随后仍由 `copy_pdf_safely()` 快照校验。
  - `write_final_reports()` 在独立报告锁内先向唯一 staging 目录生成并 fsync 全部六个固定报告；全部成功后备份旧集合再发布。任一 replace 失败会恢复全部旧文件并移除本轮原本无旧文件的目标，只清理本轮 staging/backup 中的固定报告名。
- 修改原因：旧实现可能让 CSV 数据被表格软件解释为公式；阶段更新和 Zotero 对账可能基于旧 state 相互覆盖；附件在首次哈希后可被替换；六个报告逐个发布会留下新旧混合集合。
- 如何运行：
  - `$env:TEMP=(Resolve-Path .codex-test-tmp); $env:TMP=$env:TEMP`
  - `..\..\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchFinalizeTests -v`
  - `..\..\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchRunTests -v`
  - `..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  - `..\..\.venv\Scripts\python.exe -m compileall paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation`
  - `git diff --check`
- 生成的输出文件：正式流程仍发布 `final_manifest.csv/.xlsx`、`failed.csv`、`run_summary.txt`、`batch_status.csv/.json`；事务临时目录成功或可回滚失败后均清理。测试产物仅位于 ignored `.codex-test-tmp/`，未修改原始输入或 Zotero 附件。
- 如何检查是否成功：Task 5 聚焦测试 `Ran 20 tests ... OK`；Task 4 `Ran 38 tests ... OK`；全套离线测试 `Ran 264 tests ... OK (skipped=2)`；compileall 和 diff-check 退出码为 0。
- 注意事项或潜在风险：六文件发布依赖逐文件 `os.replace()` 加回滚，无法提供跨六个文件的操作系统原生单指令原子可见性，但失败后会恢复一致旧集合；附件第二次哈希与 `copy_pdf_safely()` 打开源文件之间仍存在极短竞态窗口，最终快照会再次执行 PDF 校验。未联网、未操作真实 Zotero、未读取 Cookie、未打包。

## 2026-07-11 03:58:01 +08:00 — Task 5 最终 P1 修复

- 本次任务目标：修复最终报告可能由旧内存 state 覆盖最新磁盘 state，以及 Zotero 附件在最终校验后被按路径重新打开的两个 P1 竞态窗口。
- 新增、修改或删除的文件：修改 `paper_automation/batch_workflow.py`、`tests/test_batch_workflow.py`、`CHANGELOG.md`；追加本地 ignored `.superpowers/sdd/task-5-report.md`。未修改 Task 6、Task 7、原始输入、真实 PDF/Zotero 附件或打包文件。
- 具体修改内容：
  - 新增 `_write_latest_state_outputs()`：使用与阶段更新相同的 `batch_state_lock`，锁内重新加载并验证最新 state，按 start/resume 语义写 pending 文件，发布六个最终报告，再同步调用者 state。`finalize_batch()` 在既有 state lock 内完成逐行保存后直接调用无嵌套锁路径；start/resume 末尾不再使用旧内存 rows 直接写报告。
  - 抽取 `_snapshot_pdf_handle()` 与 `_publish_verified_pdf_snapshot()`，让 Task 2 与 Zotero 共用“已验证私有 snapshot 去重 + 硬链接原子发布”逻辑。Zotero 在目标 PDF 目录锁内检查完整绝对路径/reparse 链，打开一次 `rb` 句柄，对比 `fstat`/`lstat` 的设备号、inode、普通文件和 reparse 标识，复制前后复查祖先链与大小/mtime/标识，并从同一句柄复制、哈希、fsync、验证 PDF。snapshot hash 不等于先前 verified hash 时抛出 `zotero_attachment_changed` 并清理 snapshot；发布阶段不再重新打开源附件。
  - 保留全 `pdfs/` 目录同 SHA-256 内容复用；源 Zotero 附件不移动、不删除、不修改。
- 修改原因：旧 finalize 会在释放 state lock 后用旧 rows 发布报告，可能覆盖并发阶段更新后的新报告；旧 Zotero 流程在二次哈希后仍把路径传给 `copy_pdf_safely()` 重新打开，路径被替换时可能发布未被该次验证覆盖的内容。
- 如何运行：
  - `$env:TEMP=(Resolve-Path .codex-test-tmp); $env:TMP=$env:TEMP`
  - `..\..\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchFinalizeTests -v`
  - `..\..\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchRunTests -v`
  - `..\..\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchFileTests -v`
  - `..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  - `..\..\.venv\Scripts\python.exe -m compileall paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation`
  - `git diff --check`
- 生成的输出文件：正式批次仍在 `reports/` 发布 `final_manifest.csv/.xlsx`、`failed.csv`、`run_summary.txt`、`batch_status.csv/.json`，PDF 输出仍位于批次 `pdfs/`；测试临时输出仅位于 ignored `.codex-test-tmp/`。
- 如何检查是否成功：Task 5 `Ran 24 tests ... OK`；Task 4 `Ran 38 tests ... OK`；Task 2 文件/PDF `Ran 26 tests ... OK (skipped=1)`；全套 `Ran 268 tests ... OK (skipped=2)`；compileall 退出码 0。新增交错测试逐字段确认最终 CSV 等于磁盘最新 state；第二次哈希后替换为另一有效 PDF 或 symlink/reparse 均不得发布外部内容。
- 注意事项或潜在风险：同句柄方案消除了应用层“最终验证后按路径重新打开”的窗口，并在复制后再次核对路径身份；仍无法对抗具备更高权限、可在多个系统调用之间持续快速切换路径且最终恢复原身份的操作系统级对抗。PDF 内容有效性仍沿用 Task 2 的最小尺寸和 `%PDF-` 文件头检查，不是完整 PDF 结构解析。未联网、未访问真实 Zotero、未读取 Cookie、未打包。

## 2026-07-11 04:15 +08:00 — Task 6 初学者批次 CLI

- 本次任务目标：新增面向初学者的 `start`、`resume`、`finalize` 批次命令行入口，并保持 Task 4/5 工作流接口不变。
- 新增、修改或删除的文件：新增 `paper_batch.py`；修改 `tests/test_batch_workflow.py` 的 `BatchCliTests`；追加 `CHANGELOG.md`；新增本地未纳入提交的 `.sdd/task-6-report`。未删除文件，未修改 Task 7 文档、README、技能、原始输入、PDF、Cookie 或打包产物。
- 具体修改内容：`start` 的 `--input` 与 `--text` 使用严格互斥必填参数，并将全部 `BatchOptions` 安全参数传递给真实 `start_batch()`；`resume` 和 `finalize` 分别调用真实工作流函数。成功时统一输出运行目录、最终 PDF 目录、总计/成功/失败/人工重试/Zotero 回退数量、两份 CSV 与报告目录；根据待处理数量输出带双引号路径的准确下一步命令。预期工作流异常仅输出中文错误码 2，不输出 traceback、Cookie 内容或 state 内容。
- 修改原因：为初学者提供可复现、可直接复制的批次入口，同时延续“仅一次人工重试、合法 OA/授权访问、Zotero 附件非破坏复制”的安全边界。
- 如何运行：`..\\..\\.venv\\Scripts\\python.exe paper_batch.py --help`；启动示例：`..\\..\\.venv\\Scripts\\python.exe paper_batch.py start --text "10.1000/example" --out "results"`。后续命令由 CLI 根据批次状态打印。
- 生成的输出文件：实际运行在所选输出根目录新建批次目录及其 `pdfs/`、`working/manual_retry.csv`、`working/zotero_fallback.csv`、`working/zotero_results.csv`、`reports/`；本次测试临时文件仅位于忽略的 `.codex-test-tmp/`。
- 如何检查是否成功：TDD 红灯确认缺少模块后，`BatchCliTests` 7 项通过；Task4 `BatchRunTests` 38 项通过；Task5 `BatchFinalizeTests` 24 项通过；已检查根帮助和 `start --help` 的简体中文输出。提交前还将运行全套离线测试、compileall 与 `git diff --check`。
- 注意事项或潜在风险：测试不联网、不读取真实 Cookie、不使用真实 Zotero；真实下载结果仍取决于合法 OA 来源或用户拥有的机构授权。项目未重新打包。
- 验证补充：全套离线测试 `python -m unittest discover -s tests -v` 已运行 `275` 项并通过（`skipped=2`）；`python -m compileall paper_batch.py paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation` 与 `git diff --check` 均以退出码 0 完成。

## 2026-07-11 04:30 +08:00 — Task 6 复审修复

- 本次任务目标：修复初学者 CLI 复审提出的 PowerShell 下一步命令、安全错误提示和空 Zotero 结果文件自动创建三项问题。
- 新增、修改或删除的文件：修改 `paper_batch.py`、`tests/test_batch_workflow.py` 和 `CHANGELOG.md`；追加本地未提交的 `.sdd/task-6-report`。未新增工作树，未修改 Task 4/5 工作流、Task 7 文档、README、技能或打包文件，未删除文件。
- 具体修改内容：下一步命令改为 `& '绝对 Python' '绝对 paper_batch.py' 'resume/finalize' ...`，所有参数使用 PowerShell 单引号且内部单引号以 `''` 转义；新增固定 `ERROR_HINTS`，仅从异常文本首部识别白名单安全错误码，已知码显示固定中文建议，未知错误只显示异常类型与通用提示；当无人工重试、`fallback_count == 0` 且 `zotero_results.csv` 不存在时，以排他创建模式写入 UTF-8-SIG 的五列表头，已有文件不覆盖，有 fallback 时不创建。
- 修改原因：原命令使用相对脚本名和双引号，不能保证从任意工作目录安全执行；原错误提示无法给出可操作错误码；无 fallback 时仍要求初学者手工创建 CSV，容易产生表头或编码错误。
- 如何运行：`..\\..\\.venv\\Scripts\\python.exe paper_batch.py --help`；运行 `start` 或 `resume` 后可直接复制 CLI 输出的 PowerShell 命令。CLI 测试命令为 `..\\..\\.venv\\Scripts\\python.exe -m unittest tests.test_batch_workflow.BatchCliTests -v`。
- 生成的输出文件：仅在 `fallback_count == 0`、无需先重试且目标不存在时创建 `working/zotero_results.csv`，编码为 UTF-8-SIG，唯一数据行为表头 `task_id,zotero_item_id,attachment_path,status,reason`；不会覆盖已有结果文件。测试临时输出仍位于忽略的 `.codex-test-tmp/`。
- 如何检查是否成功：严格 TDD 先观察命令格式、错误映射、缺失表头文件和文件写入异常用例失败，再实现至 `BatchCliTests` 12 项通过；PowerShell help 命令从另一临时工作目录执行成功；Task4 38 项、Task5 24 项通过；全套 280 项通过（跳过 2 项）；help 中文正常，compileall 退出码 0。
- 注意事项或潜在风险：错误提示只允许显示 `ERROR_HINTS` 白名单中的首个安全错误码，绝不回显异常余文；CSV 使用排他创建避免并发覆盖，但磁盘权限或目录错误仍会安全返回错误码 2。未联网、未读取真实 Cookie、未操作真实 Zotero 附件、未重新打包。

## 2026-07-11 04:49:37 +08:00 — Task 7 Zotero 批处理 Skill 协议

- 本次任务目标：为 `paper-download` 增加项目优先、仅对失败项执行 Zotero 回退的可恢复批处理协议，并补齐初学者使用说明、人工 QA 与离线合同测试。
- 新增、修改或删除的文件：修改 `skills/paper-download/SKILL.md`、`tests/test_skills_packaging.py`、`README.md`、`README_zh.md`、`MANUAL_QA.md`、`CHANGELOG.md`；更新本地 `.superpowers/sdd/task-7-report.md`。未删除文件，未修改原始输入、PDF、Cookie 或打包文件。
- 具体修改内容：Skill 规定 `paper_batch.py start`、有数据时一次人工暂停与一次 `resume`、读取 `zotero_fallback.csv`、批量 Zotero 查重/导入/集合/标签、一次可用 PDF 请求、五列 `zotero_results.csv` 与 `finalize`；覆盖空回退、连接不可用、元数据不确定、PDF 路径校验和非覆盖复制。双语 README 新增 start/resume/finalize、输出树、临时集合和只复制 PDF 的说明；MANUAL_QA 新增七项离线人工验收场景；测试增加 Skill 合同断言和禁止字符串检查。
- 修改原因：旧 Skill 不能把项目失败项交给 Zotero，也未定义一次重试、批量确认、结果 CSV 或不可用时的可恢复行为。
- 如何运行：`..\\..\\.venv\\Scripts\\python.exe -m unittest tests.test_skills_packaging -v`；`..\\..\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`；使用 `rg` 检查 Skill、README 和 MANUAL_QA 中的批处理字段及禁止字符串。
- 生成的输出文件：真实使用时由 `paper_batch.py` 在 `results\\paper_batch_YYYYMMDD_HHMMSS\\` 生成 `pdfs\\`、`reports\\` 和 `working\\zotero_fallback.csv/zotero_results.csv`；本次仅产生测试临时目录，未生成真实下载文件。
- 如何检查是否成功：严格 TDD 的 RED 阶段中新增合同测试因旧 Skill 缺少 `paper_batch`/Zotero 协议而失败 25 项；实现后聚焦测试 18 项通过，全量离线测试 281 项通过（跳过 2 项）；文本扫描确认关键协议字段存在且 Skill 不含三项禁止字符串。
- 注意事项或潜在风险：未联网、未调用真实 Zotero、未读取 Cookie、未处理真实 CAPTCHA、未打包。真实 Zotero 可用 PDF 的结果仍取决于用户的本地文库、连接状态和合法可访问来源；不可用时必须保持批次可恢复，不能报为完成。

## 2026-07-11 05:05:27 +08:00 — Task 7 独立审查修复

- 本次任务目标：修复 Task 7 独立审查和 Skill 前向测试发现的完成状态误报及 Zotero 协议歧义，保持兼容解析状态不收紧。
- 新增、修改或删除的文件：修改 `paper_batch.py`、`tests/test_batch_workflow.py`、`skills/paper-download/SKILL.md`、`tests/test_skills_packaging.py`、`CHANGELOG.md` 和 `.superpowers/sdd/task-7-report.md`；未修改 README/MANUAL_QA，未删除文件。
- 具体修改内容：CLI 仅在 `failed_count == 0` 且 `zotero_fallback_count == 0` 时打印“批次已完成”；否则打印“报告已更新/批次未完成且可恢复”、未解决数量和最终 PDF 目录，且不输出 resume 命令。Skill 明确 UTF-8-SIG/Python CSV 数据行规则、活动个人文库选择、固定 `libraryID`、collection/search/import/tag 完整参数、NFKC 题名与作者规范化、排他结果文件及时间戳重试文件恢复策略，并区分协议生成的六状态与解析器兼容的三状态。
- 修改原因：旧 CLI 对任意 finalize 结果无条件报完成；旧 Skill 未给出可直接执行的 MCP 参数形状，多文库、题名匹配、CSV 空白行和已有结果文件恢复行为不明确，且状态说明与 Task 5 兼容白名单不一致。
- 如何运行：`..\\..\\.venv\\Scripts\\python.exe -m unittest tests.test_batch_workflow.BatchCliTests -v`；`..\\..\\.venv\\Scripts\\python.exe -m unittest tests.test_skills_packaging -v`；`..\\..\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`；`git diff --check`；使用 `rg` 扫描 Skill 禁止字符串和关键协议参数。
- 生成的输出文件：真实流程仍只在批次目录生成 `pdfs\\`、`reports\\`、`working\\zotero_results.csv` 或 `working\\zotero_results_retry_YYYYMMDD_HHMMSS.csv`；本次仅生成系统临时测试文件，没有真实下载或 Zotero 写入。
- 如何检查是否成功：CLI RED 为 `BatchCliTests` 13 项中 1 项失败，明确捕获未解决 finalize 误报；Skill review RED 为 19 项测试中的新合同产生 23 个缺失断言。修复后 CLI 13 项、Skill 19 项均通过，全量离线测试 283 项通过（跳过 2 项）。
- 注意事项或潜在风险：CLI 退出码仍为 0，表示报告成功生成而非全部论文成功；调用方必须读取输出和报告判断是否仍可恢复。Skill 是编排合同，真实 Zotero 工具返回结构仍需在用户环境中按协议校验。未联网、未调用真实 Zotero、未读取 Cookie、未自动处理 CAPTCHA、未打包。

## 2026-07-11 05:22:20 +08:00 — Task 7 第二轮 stale 结果文件修复

- 本次任务目标：阻止空 fallback 流程复用陈旧或格式不严格的 canonical Zotero 结果文件，并修正 Skill 对 pending/result CSV 空白记录及 Zotero ID 返回边界的描述。
- 新增、修改或删除的文件：修改 `paper_batch.py`、`tests/test_batch_workflow.py`、`skills/paper-download/SKILL.md`、`tests/test_skills_packaging.py`、`CHANGELOG.md` 和 `.superpowers/sdd/task-7-report.md`；未修改 README/MANUAL_QA，未删除文件。
- 具体修改内容：canonical 仅在含 UTF-8 BOM、可严格解码且 `csv.reader(strict=True)` 只得到一行精确 `ZOTERO_RESULT_FIELDS` 时复用；其他内容原样保留并排他创建 `zotero_results_retry_YYYYMMDD_HHMMSS[_N].csv` 仅表头文件，finalize 命令使用实际选中路径；同秒冲突递增后缀且不覆盖。Skill 分离 pending 可忽略 blank 与 result 必须拒绝物理空白/全空白数据行的规则，并要求 Zotero numeric ID 显式返回或可验证、缺失/歧义时 fail closed；本地 CSV 使用标准库 `csv.writer`、`x` 模式、`newline=""`、`utf-8-sig`，写前完整校验 task IDs，PDF/reparse 仍由 finalize 复验。
- 修改原因：旧 `_ensure_header_only_zotero_results()` 对任意已存在 canonical 直接返回，且旧 `_finalize_command()` 固定指向 canonical；Skill 旧文字把 pending 与严格 result 的 blank 规则混为一谈，并可能让执行者假设工具返回 schema 或猜测 ID。
- 如何运行：`..\\..\\.venv\\Scripts\\python.exe -m unittest tests.test_batch_workflow.BatchCliTests -v`；`..\\..\\.venv\\Scripts\\python.exe -m unittest tests.test_skills_packaging -v`；`..\\..\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`；`git diff --check`；使用 `rg` 扫描 Skill 禁止字符串与关键边界。
- 生成的输出文件：空 fallback 且 canonical 无效时，新建 `working\\zotero_results_retry_YYYYMMDD_HHMMSS.csv`；同秒冲突依次使用 `_2`、`_3` 等后缀。canonical 与其他已有结果文件保持不变。本次仅生成测试临时文件，无真实 PDF/Zotero 输出。
- 如何检查是否成功：CLI RED 为 16 项中 stale、物理空白行、同秒冲突 3 项失败；合法 header-only canonical 测试保持通过。Skill RED 为 20 项中的新增合同产生 15 个缺失断言。修复后 CLI 16 项、Skill 20 项通过，全量离线测试 287 项通过（跳过 2 项）。
- 注意事项或潜在风险：严格复用有意拒绝无 BOM、附加空白行或任何数据行的 canonical；它们不会被删除或覆盖，而会留存供审计。时间戳冲突后缀没有固定上限，会持续使用排他创建直到获得安全文件名。未联网、未调用真实 Zotero、未读取 Cookie、未自动处理 CAPTCHA、未打包。
## 2026-07-11 05:33:13 +08:00 — Task 8 离线端到端验收

- 本次任务目标：为批处理工作流补充离线端到端验收，覆盖 `start`、唯一一次 `resume`、Zotero 结果导入和重复 `finalize` 的安全行为。
- 新增、修改或删除的文件：修改 `tests/test_batch_workflow.py`（新增 `FakeBatchGateway.retry_calls` 只读测试辅助属性和 `BatchEndToEndTests.test_start_resume_finalize_produces_one_manifest_and_valid_pdfs`）；新增 `.superpowers/sdd/task-8-report.md`；追加本 `CHANGELOG.md`。未修改产品代码，未删除文件。
- 具体修改内容：测试使用 3 条确定性规范化输入；第 1 条由项目流程复制有效 PDF，后两条经同一次 `resume` 后进入 Zotero 回退。模拟 Zotero 对第 2 条提供有效附件、对第 3 条提供 `no_pdf/no_available_pdf`。断言重试次数为 1、成功/失败数为 2/1、`pdfs/` 恰有 2 个有效 PDF、`final_manifest.xlsx` 存在、摘要含 `no_available_pdf`、最终 CSV 清单含全部 3 个 `task_id`，并以 SHA-256 校验项目/Zotero 源 PDF 字节未变。第二次 `finalize` 后再次比较最终 PDF 名称和字节，确认不重复且不覆盖。
- 修改原因：将 Task 4/5/7 的单元与协议验证串联为可重复执行的离线验收证据，并防止未来变更破坏恢复、汇总和非破坏性复制边界。
- 如何运行：
  - `..\..\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchEndToEndTests -v`
  - `..\..\.venv\Scripts\python.exe -m compileall paper_batch.py paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation`
  - `..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  - `rg -n "Sci-Hub|scihub|Anna's Archive|annas_archive|LibGen|apply_auto_fallback" paper_batch.py paper_automation sd_institutional_skill.py paper_skill.py doi_batch_utils.py skills/paper-download/SKILL.md`
  - `git diff --check`
- 测试输出：focused 验收为 `Ran 1 test in 0.629s`、`OK`；完整离线套件为 `Ran 288 tests in 14.492s`、`OK (skipped=2)`；`compileall` 与 `git diff --check` 均退出码 0；影子来源扫描无匹配（`rg` 退出码 1）。
- 生成的输出文件：仅创建测试临时目录内的模拟批次 `pdfs/`、`reports/final_manifest.csv/.xlsx`、`run_summary.txt` 和状态文件，退出测试后自动清理；审计证据写入 `.superpowers/sdd/task-8-report.md`。
- 如何检查是否成功：focused 测试全部断言通过，并且完整离线测试套件、语法检查和差异检查均成功；查看 `task-8-report.md` 可追溯每项证据。
- 注意事项或潜在风险：本次严格离线，未联网、未调用真实 Zotero、未读取 Cookie/密码、未安装 Skill、未打包。真实 Zotero 的个人文库、PDF 可用性、机构授权、登录/CAPTCHA 与手工验收仍需用户在授权的应用环境中完成；未修改原始输入或实际 PDF。

## 2026-07-11 05:43:23 +08:00 — Task 8 离线验收审查修复

- 本次任务目标：修复 Task 8 审查指出的离线验收证据不足，严格验证两个最终 PDF 的不同来源、最终清单行唯一性，以及重复 `finalize` 的报告、状态和 PDF 幂等性。
- 新增、修改或删除的文件：修改 `tests/test_batch_workflow.py`、`CHANGELOG.md` 和 `.superpowers/sdd/task-8-report.md`；未新增或删除产品文件，未修改产品代码。
- 提交前工作树状态：本隔离工作树进入本轮审查修复前 `git status --short --untracked-files=all` 无输出，现有未提交文件为无。
- 具体修改内容：新增最终 PDF 内容 SHA-256 集合断言，要求恰好等于 `project_payload` 与 `zotero_payload` 的两个哈希；新增 `final_manifest.csv` 行数等于 3 及 `assertCountEqual` 重数断言，保证每个 `task_id` 恰好出现一次；首次 `finalize` 后保存六份报告、state 和最终 PDF 的 bytes，第二次 `finalize` 后验证五份字节稳定报告、state 与最终 PDF 全部逐字节不变，并验证 XLSX 工作表值不变。
- XLSX 实际行为验证：诊断测试在两次 `finalize` 间隔 2.1 秒时，聚合字节比较按预期失败；核对后仅 `final_manifest.xlsx` 的 ZIP/工作簿时间元数据变化。当前产品每次以 `openpyxl.Workbook` 新建 XLSX，设计未保证包级字节确定性，因此测试保留首次/二次 XLSX 原始 bytes，但只对工作表值做语义幂等断言，不伪造字节幂等结论。
- 修改原因：原测试只检查 PDF 数量和有效性，不能排除同一来源被复制两次；只比较 task ID 集合不能排除重复行；只比较 PDF 名称和 bytes 不能证明报告与 state 在重复 finalize 后保持稳定。
- 如何运行：`..\..\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchEndToEndTests -v`；`..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v`；`git diff --check`。
- 测试输出：最终 focused 为 `Ran 1 test in 0.632s`、`OK`；完整离线套件为 `Ran 288 tests in 14.350s`、`OK (skipped=2)`。诊断阶段曾得到 1 个预期失败，用于确认 XLSX 包元数据非确定性，最终测试未保留该人为延迟。
- 生成的输出文件：测试仅在临时目录生成并自动清理两份源 PDF、两个最终 PDF、六份报告、Zotero 结果 CSV 与 batch state；审查证据更新至 `.superpowers/sdd/task-8-report.md`。
- 如何检查是否成功：确认最终 PDF 哈希集合含两个不同预期哈希、manifest 恰有三行且 task ID 重数一致、五份稳定报告/state/PDF bytes 在第二次 finalize 后完全相同、XLSX 工作表值一致，并确认 focused/full/diff check 通过。
- 注意事项或潜在风险：真实 Zotero 未验收不是本离线测试缺陷，保留给后续手工步骤。本次未联网、未操作真实 Zotero、未读取 Cookie/密码、未安装 Skill、未打包，也未修改原始输入或实际 PDF。

## 2026-07-11 05:51:00 +08:00 — 安装 Skill 并检查 Zotero 可用性

- 本次任务目标：把已验证的 `paper-download` Skill 安装到个人 Codex Skills，并在任何 Zotero 写入前检查活动文库是否可用。
- 新增、修改或删除的文件：项目内仅追加 `CHANGELOG.md` 和 `.superpowers/sdd/task-8-report.md`；项目外备份旧版 `C:\Users\wkguopro\.codex\skills\paper-download\SKILL.md`，再只替换该 Skill 文件，未改动另外两个已安装 Skill。
- 具体修改内容：先运行 `install_codex_skills.ps1 -DryRun` 确认目标；正式安装时把旧 Skill 备份到 `C:\Users\wkguopro\.codex\skill-backups\paper-download\20260711_055044\SKILL.md`，复制新 Skill，并把用户环境变量 `PAPER_SCRAPER_DOI_ROOT` 指向隔离工作树。
- 修改原因：让新 Codex 任务能够使用项目优先、一次重试、仅失败项进入 Zotero 的统一协议，同时用备份避免丢失旧版 Skill。
- 如何运行：`powershell -ExecutionPolicy Bypass -File .\install_codex_skills.ps1 -DryRun`；安装后调用 `library_search(entity:"libraries", mode:"list")` 做只读可用性检查。
- 测试输出：安装源和目标 SHA-256 均为 `83339B36E5B6ADBA3F214187C47CF18AF56B830D107C90EBDF47C06C0036303E`；Zotero 检查返回 `No active library available`。
- 生成的输出文件：生成一份个人 Skill 备份并更新个人 `paper-download/SKILL.md`；未生成或下载 PDF，未创建 Zotero 集合或条目。
- 如何检查是否成功：目标 Skill 哈希与项目源文件一致；环境变量指向当前隔离工作树；Zotero 不可用时未发起任何写入、导入或附件检索。
- 注意事项或潜在风险：需要打开 Zotero 并激活个人文库后才能继续真实验收。当前批次保持未完成且可恢复；未读取密码/Cookie，未自动处理 CAPTCHA，未打包。

## 2026-07-11 07:28:10 +08:00 — Zotero 写确认 UI 验收修复

- 本次任务目标：根据真实 Zotero 验收证据，修复 `paper-download` Skill 对“可读但普通写入确认 UI 不可用”的处理，保持批次可恢复且不绕过确认。
- 新增、修改或删除的文件：修改 `skills/paper-download/SKILL.md`、`tests/test_skills_packaging.py`、`README.md`、`README_zh.md`、`MANUAL_QA.md`、`.superpowers/sdd/task-8-report.md` 和 `CHANGELOG.md`；未新增或删除产品代码文件，未修改原始数据、PDF、Cookie 或打包文件。
- 具体修改内容：先新增 Skill 包装合同测试，要求精确识别 `Zotero MCP confirmation UI is unavailable for this Codex turn. Start a new Codex turn from Zotero and try again.`；Skill 规定首次普通写入 `collection_update(action:"create", ...)` 出现该错误后立即停止其余 Zotero 写入，不得用 `zotero_script` 绕过 collection/import/tag 确认。它只提示一次：从 Zotero Codex 面板新开回合并说“继续该批次”；保留 `run-dir`、`zotero_fallback.csv` 和已有结果，从 library check/collection creation 继续，不重跑项目下载、不执行第二次 `resume`。`zotero_script(mode:"write")` 仍仅可用于带 `env.addUndoStep` 的单次 `Zotero.Attachments.addAvailablePDF` 批处理；新回合仍不可写时写入 `zotero_unavailable` 结果并保持可恢复。README 英中与 MANUAL_QA 同步加入该边界和验收场景。
- 修改原因：真实证据显示 `envLibraryID=1`、`userLibraryID=1`，且显式 `libraryID=1` 可列出 1,244 条，说明个人文库可读；候选 item `304` 已有 PDF、`349` 无 PDF、PLOS DOI 未入库。但首次 `collection_update` 返回确认 UI 不可用，Zotero 未执行集合创建，完成写入数为 0。这是普通写确认 UI 的回合来源限制，不是文库读取失败。
- 如何运行：先运行 `..\..\.venv\Scripts\python.exe -m unittest tests.test_skills_packaging.SkillPackagingTests.test_paper_download_skill_stops_for_unavailable_zotero_write_confirmation -v`；再运行 `..\..\.venv\Scripts\python.exe -m unittest tests.test_skills_packaging -v`、`..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v`，最后运行 `git diff --check`。
- 生成的输出文件：本次只修改上述文档和离线合同测试；真实运行时，若 Zotero-origin 回合仍无法写入，将按既有恢复规则在 `<run-dir>\working\zotero_results.csv` 或时间戳 retry 文件写入 `zotero_unavailable` 行，不覆盖原有结果。
- 如何检查是否成功：RED 阶段该 focused 测试因缺少 11 个合同片段失败；补充协议后同一 focused 测试通过。完整测试与差异检查结果见本次提交前验证；`MANUAL_QA.md` 的第 8 项可在授权的 Zotero 面板中复核一次提示、零后续写入和可恢复结果。
- 注意事项或潜在风险：本回合未联网、未调用 Zotero、未读写 Cookie、未下载论文、未打包，也没有以 `zotero_script` 绕过普通写确认。必须从 Zotero 的 Codex 面板发起新回合；若该回合仍没有确认 UI，不能反复请求新回合，应生成可恢复的 `zotero_unavailable` 结果。

## 2026-07-11 07:34:00 +08:00 — 写确认恢复协议前向验证

- 本次任务目标：验证 Skill 遇到 Zotero 写确认 UI 不可用时，代理实际会停止写入并按一次提示规则恢复，而不只是包含相关文字。
- 新增、修改或删除的文件：仅追加 `CHANGELOG.md` 和 `.superpowers/sdd/task-8-report.md`；未修改产品代码、Skill 协议或测试代码。
- 具体修改内容：全新代理仅读取更新后的 `paper-download/SKILL.md`，模拟第一次和 Zotero-origin 新回合第二次都收到相同确认 UI 错误。
- 修改原因：独立审查指出静态字符串测试不能单独证明执行行为，需要 Skill 前向测试补充行为证据。
- 如何运行：向全新代理提供确认 UI 错误场景，要求列出后续工具调用、提示次数、保留文件和第二次失败后的结果状态。
- 测试输出：前向测试 `PASS`；第一次错误后后续 Zotero 写入为 0，不调用 collection membership/import/search/script/tag；整批只提示一次。第二次错误后写 3 行 `zotero_unavailable`，执行一次 `finalize`，状态为未完成且可恢复，不输出第二次 `resume`。
- 生成的输出文件：仅记录审计证据；模拟测试未创建真实集合、条目、标签、附件或 PDF。
- 如何检查是否成功：核对前向测试明确列出 0 次后续写入、不绕过确认、保留 `run-dir`/fallback/结果文件、不重跑项目或第二次 `resume`。
- 注意事项或潜在风险：真实写确认仍必须由用户从 Zotero Codex 面板发起下一回合验证；本次未联网、未调用真实 Zotero 写入、未打包。

## 2026-07-11 08:23:22 +08:00 — Zotero 9 本地桥接设计确认

- 本次任务目标：设计一个不依赖 LLM for Zotero 写确认 UI 的 Zotero 9.0.6 本地桥接，使用户提供文献清单后，项目优先下载、Zotero 只处理失败项，并以每批一次确认自动返回 PDF 附件结果。
- 新增、修改或删除的文件：新增 `docs/superpowers/specs/2026-07-11-zotero9-local-bridge-design.md`；追加本 `CHANGELOG.md`；未修改产品代码、测试、原始数据或 PDF，未删除文件。
- 具体修改内容：比较文件队列、Zotero 内部 HTTP 和 Web/Local API 混合三种方案，确定采用当前用户本地应用数据目录中的原子 JSON 文件队列；定义请求/结果 schema、项目与插件职责、每批一次确认、查重/导入/可用 PDF 检索顺序、状态机、幂等恢复、安全边界、测试配置验收和主配置安装门禁。
- 修改原因：现有 MCP 路径可以读取个人文库，但桌面 Codex 回合无法显示普通 Zotero 写入确认 UI；官方本地 API不能直接承担所需写入和“查找可用 PDF”动作，需要由 Zotero 9 插件在应用内部通过 JavaScript API执行。
- 如何运行：本次为设计文档，无可执行命令；后续实施计划将以 `.\.venv\Scripts\python.exe paper_batch.py zotero --run-dir "<run-dir>"` 作为目标项目入口。
- 生成的输出文件：仅生成上述设计规格；没有创建桥接任务、Zotero 集合、条目、附件、结果 CSV 或最终 PDF。
- 如何检查是否成功：阅读设计规格，核对方案选择、固定数据合同、一次确认、非破坏性复制、恢复规则、测试范围和安装门禁是否覆盖用户目标；运行 `git diff --check` 检查文档差异格式。
- 注意事项或潜在风险：本次没有实现或安装插件；Zotero 的具体内部 API仍需在 9.0.6 测试配置中做功能检测和真实验收。不会直接修改 SQLite，不开放网络端口，不读取密码/Cookie，不使用影子来源，不自动处理 CAPTCHA，也不自动打包。

## 2026-07-11 08:50:13 +08:00 — 默认 Chrome/Chromium，禁止隐式启动 Edge

- 本次任务目标：响应用户“不要调用 Edge，优先 Chrome/Codex App 内置浏览器”的要求，避免项目在未明确指定浏览器时自动启动 Edge。
- 新增、修改或删除的文件：修改 `windows_paths.py`、`tests/test_windows_paths.py`、`README_zh.md`、`WINDOWS_UI_README.md` 和本 `CHANGELOG.md`；未新增或删除产品数据、PDF、Cookie、插件或打包文件。
- 具体修改内容：Windows 自动候选顺序改为 Chrome/Chromium（含 Playwright Chromium）优先，并移除 Edge/Edge Beta/Dev/SxS 与 `msedge` 的隐式候选；`browser_bin()` 保留用户显式 `--browser-exe` 或 `PAPER_SCRAPER_BROWSER_EXE` 指向 Edge 的兼容性。同步测试为“不会自动选 Edge”及 Chrome profile 优先，中文说明明确 Codex App 内置浏览器由代理控制，Python 下载器不能直接接管其登录会话。
- 修改原因：真实批次在没有显式浏览器路径时启动了临时 Edge 调试实例；用户明确要求不再发生该行为。
- 如何运行：`..\\..\\.venv\\Scripts\\python.exe -m unittest tests.test_windows_paths -v`；完整回归可运行 `..\\..\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`。
- 生成的输出文件：本次仅生成测试运行时的临时文件；不会启动浏览器、不会生成 PDF、不会写入 Zotero 文库或更改原始输入。
- 如何检查是否成功：在测试中同时模拟 Chrome 与 Edge 时必须选择 Chrome；只模拟 Edge 时也不得返回 Edge 路径；显式传入 Edge 路径的 profile 测试仍通过。查看文档可确认 Edge 仅在用户显式指定时使用。
- 注意事项或潜在风险：若系统没有 Chrome/Chromium，默认路径会是 Chrome 的预期路径，随后由原有启动错误提示处理；这比在未获用户同意时自动改用 Edge 更符合当前要求。Codex App 内置浏览器仍需由本会话的浏览器控制能力登录，不能被 Python 的 CDP 下载器直接复用。未自动打包。

## 2026-07-11 08:55:49 +08:00 — ScienceDirect 下载异常的可恢复报告

- 本次任务目标：修复真实批次中 ScienceDirect 下载器在机构访问确认后抛出 `FileNotFoundError` 时，子流程没有生成 PDF 报告、上层只能记录笼统 `stage_exception_FileNotFoundError` 的问题。
- 新增、修改或删除的文件：修改 `sd_institutional_skill.py`、`tests/test_sd_institutional_skill.py` 和本 `CHANGELOG.md`；未修改原始输入、实际 PDF、Cookie、浏览器配置、Zotero 文库或打包文件。
- 具体修改内容：为 `scraper.download_pdfs_devtools()` 增加异常边界；任何普通异常都按当前已解析 DOI 逐篇生成 `PdfDownloadRecord(status="failed")`，原因只记录异常类型，例如 `download_exception_FileNotFoundError`，随后继续生成 `pdf_download_report.csv`、学生交接文件和汇总。新增最小回归测试，使用 1 条 DOI 与模拟下载器抛出 `FileNotFoundError`，断言主入口退出码为 0、报告有 1 条失败记录且 JSON 摘要 `pdf_failed=1`。
- 修改原因：真实运行已证明下载器异常可能发生在 `sd_institutional_skill.main()` 内部；以前异常越过报告层，被 `paper_automation.batch_stages` 捕获后丢失了逐篇失败原因和恢复文件。
- 如何运行：`..\\..\\.venv\\Scripts\\python.exe -m unittest tests.test_sd_institutional_skill.InstitutionalSkillIntakeTests.test_main_writes_failed_pdf_report_when_devtools_download_raises_file_not_found -v`；`..\\..\\.venv\\Scripts\\python.exe -m unittest tests.test_batch_workflow.BatchStageTests.test_sciencedirect_adapter_reports_missing_report tests.test_batch_workflow.BatchStageTests.test_sciencedirect_adapter_reports_nonzero_exit_without_report -v`；完整回归使用 `..\\..\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`。
- 生成的输出文件：真实异常时会生成或保留 `pdf_download_report.csv`、`run_summary.txt`、`run_summary.json` 与学生交接文件；本次仅在测试临时目录生成并自动清理这些文件。
- 如何检查是否成功：回归测试先在修复前稳定抛出 `FileNotFoundError`（RED），修复后验证报告状态为 `failed`、原因精确为 `download_exception_FileNotFoundError`、摘要失败数为 1（GREEN）；上层批处理随后可读取报告并把条目交给后续 Zotero 回退，而不是因缺失报告抛异常。
- 注意事项或潜在风险：异常类型会保留用于排查，但不写入异常消息、路径、Cookie 或机构会话信息。已下载的部分结果若下载器在抛错前未返回结构化结果，出于安全性会被记录为失败而不推测成功。未联网、未启动 Edge/Chrome、未自动处理 CAPTCHA、未打包。

## 2026-07-11 09:01:41 +08:00 — Zotero 9 本地桥接实施计划

- 本次任务目标：把已确认的 Zotero 9 本地桥接设计拆分为可独立验收的项目端、插件端和端到端集成实施计划，供后续逐任务编码与测试使用。
- 新增、修改或删除的文件：新增 `docs/superpowers/plans/2026-07-11-zotero9-project-bridge.md`、`docs/superpowers/plans/2026-07-11-zotero9-plugin.md`、`docs/superpowers/plans/2026-07-11-zotero9-bridge-integration.md`；追加本 `CHANGELOG.md`；未修改产品逻辑、数据、PDF、Zotero 配置或打包文件。
- 具体修改内容：项目端计划定义 LocalAppData 文件队列、严格 JSON schema、原子发布、重复作业保护、结果 CSV 转换与 `paper_batch.py zotero`；插件计划定义 Zotero 9 生命周期、纯 JS 合同测试、一次确认、条目解析、可用 PDF、检查点和受限撤销；集成计划定义离线假插件验收、Skill/文档迁移以及只针对 `Zotero test` 配置的显式安装门禁。计划自检修正了测试 fixture 的完整 BatchOptions 合同和原子发布避免可见空结果文件的要求。
- 修改原因：正常 LLM for Zotero 写入确认 UI 在桌面 Codex 回合不可用，用户已同意开发更稳定的本地桥接；实现需要在不触碰主 Zotero 文库前先锁定可测试的接口与验收边界。
- 如何运行：本次为计划文档，无运行产物；后续按文档逐项执行 `..\\..\\.venv\\Scripts\\python.exe -m unittest ...` 与 `node --test ...`。任何 XPI 生成或测试配置安装都必须在文档 Task 4 的用户明确批准后才执行。
- 生成的输出文件：仅生成上述 Markdown 计划；没有创建桥接 JSON、CSV、PDF、XPI、Zotero 集合、条目或附件。
- 如何检查是否成功：三份计划均具备标准 Header、Goal、Architecture、Tech Stack、Global Constraints 和可勾选任务；占位词扫描无匹配，计划内容覆盖 schema、一次确认、恢复、PDF 复验、安全约束、离线测试、测试配置验收和主配置门禁。
- 注意事项或潜在风险：计划本身不等于实现；当前仍不安装插件、不生成 XPI、不操作主 Zotero 配置。未自动打包。

## 2026-07-11 09:16:00 +08:00 — Zotero 9 bridge multi-chunk contract revision

- 任务目标：补齐实施计划中的大批量回退文献分块边界，确保超过 100 条时仍只出现一次 Zotero 确认。
- 修改文件：`docs/superpowers/specs/2026-07-11-zotero9-local-bridge-design.md`、三份 `docs/superpowers/plans/2026-07-11-zotero9-*.md` 与本 `CHANGELOG.md`；未改动产品代码、原始数据、PDF、Zotero 配置或打包文件。
- 具体修改：请求合同新增 `chunk_index/chunk_count`；项目端将以 `working\zotero_bridge_jobs.json` 保存有序清单，分块为每件最多 100 条；插件须在所有分块完整到达后再显示一次确认；项目端仅在所有结果验证后创建一份五列 CSV。
- 修改原因：旧计划只持久化单个 job，无法安全恢复超过 100 条的逻辑批次，并可能导致分块逐个到达时重复确认。
- 如何运行：本次仅更新设计与实施计划；后续按计划中的 Python/Node 离线测试命令执行。
- 输出与检查：未生成队列、CSV、PDF、XPI 或 Zotero 写入；审查请求字段、清单、插件分组、集成测试和手工验收项是否都覆盖 101 条两分块场景。
- 注意事项：未联网、未启动 Edge 或 Chrome、未操作 Zotero、未处理 CAPTCHA，且未自动打包。

## 2026-07-11 09:35:42 +08:00 — Task 1 Zotero 本地桥接请求合同

- 本次任务目标：为批量下载流程定义严格、离线可测的 Zotero 本地桥接路径与请求合同；支持每个作业最多 100 条、101 条按原 CSV 顺序拆为 100/1 两个分块，并为同一逻辑批次共享运行标识、集合名和时间戳。
- 新增、修改或删除的文件：新增 paper_automation/zotero_bridge.py 与 tests/test_zotero_bridge.py；仅追加本 CHANGELOG.md；未删除或修改原始实验数据、既有产品模块、插件、Skill、README 或打包配置。
- 具体修改内容：新增冻结的 BridgePaths、BridgeJob、BridgeBatch 数据类；新增 LocalAppData 默认根目录与桥接路径构造；从 <run-dir>/working/batch_state.json 和 zotero_fallback.csv 读取当前回退项并要求 CSV 表头严格等于 NORMALIZED_FIELDS；构造仅含 task_id/doi/title/authors/year 的请求项；实施 UUID-v4、字段集、长度、库 ID、分块索引、重复任务 ID、作业条数和 SHA-256 规范化载荷校验；新增 4 项临时目录 unittest 覆盖默认路径、单作业元数据、未知字段/重复任务拒绝与 101 条稳定分块。
- 修改原因：Zotero 回退批次需要在不读取 Cookie、不操作真实文库且不产生重复确认的前提下，向后续本地插件提供稳定、可验证的请求边界。
- 输入与输出：输入为已有批次状态和 working/zotero_fallback.csv；输出为内存中的桥接请求字典或字典列表，以及供后续流程使用的路径/作业数据类。本任务未向真实 LOCALAPPDATA 队列写入 JSON，也未生成 PDF、结果 CSV、XPI 或打包文件。
- 如何运行：
  - RED：..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge.ZoteroBridgeRequestTests -v
  - GREEN：..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge.ZoteroBridgeRequestTests -v
  - 现有状态回归：..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge.ZoteroBridgeRequestTests tests.test_batch_workflow.BatchFileTests tests.test_batch_workflow.BatchRunTests -v
  - 编译与完整离线回归：..\..\.venv\Scripts\python.exe -m compileall paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation；..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v
- 如何检查是否成功：RED 阶段在新模块创建前按预期报告 ModuleNotFoundError；GREEN 阶段 4 项通过；替代状态回归共 68 项通过（1 项因 Windows 符号链接权限按既有条件跳过）；完整离线回归为 Ran 294 tests ... OK (skipped=2)，编译命令退出码为 0；提交前另执行 git diff --check。
- 注意事项或潜在风险：简报指定的 tests.test_batch_workflow.BatchStateTests 在当前基线不存在，直接运行会报 AttributeError，故以实际覆盖状态持久化与恢复验证的 BatchFileTests 和 BatchRunTests 替代；所有测试仅使用临时目录或 mock/fake 边界，未联网、未启动浏览器、未访问 Zotero、未读写 Cookie、未写真实 LocalAppData 队列，且未自动打包。

## 2026-07-11 13:06:58 +08:00 — Task 1 桥接请求合同复审加固

- 本次任务目标：补强 Zotero 本地桥接请求合同的输入完整性，防止任意元数据、重复作业 ID 或非规范时间戳进入后续文件队列。
- 新增、修改或删除的文件：修改 `paper_automation/zotero_bridge.py`、`tests/test_zotero_bridge.py`、`docs/superpowers/plans/2026-07-11-zotero9-project-bridge.md` 与本 `CHANGELOG.md`；未删除文件，未修改原始文献数据、PDF、Zotero 配置或打包产物。
- 具体修改内容：要求 supplied rows 严格等于当前 `zotero_fallback.csv` 中对应 chunk 的原始顺序切片，并与 `batch_state.json` 行完全一致；拒绝重复 job ID；只接受以 `Z` 结尾、有效且严格递增的 UTC 时间；拒绝把 Python 布尔值当作 JSON 整数；同步修正计划中的实际状态回归测试类名。
- 修改原因：独立复审会话未能返回报告前的主控差异审查发现，原先可选 rows 参数、重复 ID 和时间类型边界仍可能使后续队列合同不够严格。
- 如何运行：`..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge.ZoteroBridgeRequestTests -v`；`..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge.ZoteroBridgeRequestTests tests.test_batch_workflow.BatchFileTests tests.test_batch_workflow.BatchRunTests -v`；随后运行完整离线回归与 `git diff --check`。
- 生成的输出文件：测试仅在系统临时目录创建短暂文件；未创建真实 LocalAppData 桥接 JSON、Zotero 集合/条目/附件、PDF、结果 CSV、XPI 或打包文件。
- 如何检查是否成功：新增测试必须覆盖 101 条 100/1 分块、任意 rows 注入、state 不匹配、重复 UUID、非 UTC/倒置时间和布尔整数；所有离线测试通过且差异检查为空。
- 注意事项或潜在风险：本次仍未联网、未启动 Chrome/Edge/Codex 浏览器、未访问或写入 Zotero、未处理 CAPTCHA、未读取 Cookie，且未自动打包；真实队列发布和 Zotero 插件处理仍属于后续任务。

## 2026-07-11 13:19:16 +08:00 — Ask Matt 工程协作配置

- 本次任务目标：按用户确认的 `$ask-matt` 流程，为本项目建立 GitHub Issues、默认 triage 标签和单上下文领域文档的协作约定。
- 新增、修改或删除的文件：修改 `AGENTS.md` 与本 `CHANGELOG.md`；新增 `docs/agents/issue-tracker.md`、`docs/agents/triage-labels.md`、`docs/agents/domain.md`；未删除任何文件。
- 具体修改内容：在既有项目规则中增加 Agent skills 索引；记录 GitHub Issues 为 tracker、PR 不作为自动 triage 来源、五个默认标签和单上下文领域文档读取规则。
- 修改原因：后续 `/implement`、`/tdd`、`/code-review` 等 Matt 工程流程需要明确的 tracker、标签和领域文档位置。
- 如何运行：本次为本地文档配置，无需运行产品命令；可阅读上述文件确认配置内容。
- 生成的输出文件：仅生成协作配置 Markdown；未创建 GitHub issue、PDF、桥接 JSON、XPI、Zotero 集合/条目/附件或打包文件。
- 如何检查是否成功：`AGENTS.md` 包含唯一的 `## Agent skills` 区块，三份 `docs/agents/*.md` 文件存在并准确指向 GitHub Issues、默认标签和单上下文规则。
- 注意事项或潜在风险：未联网、未调用 `gh` 写入、未启动浏览器、未访问 Zotero、未读取 Cookie，且未自动打包；GitHub 中的实际标签仅在后续明确需要时创建或变更。

## 2026-07-11 13:26:43 +08:00 — Task 2 Zotero 桥接原子批次发布

- 本次任务目标：为已验证的 Zotero 回退请求增加清单优先、可恢复、幂等且并发安全的本地文件队列发布。
- 新增、修改或删除的文件：修改 `paper_automation/zotero_bridge.py`、`tests/test_zotero_bridge.py` 与本 `CHANGELOG.md`；未删除文件。
- 具体修改内容：新增严格的批次清单及 SHA-256 校验、原子排他 JSON 发布、已有 inbox/processing/archive 请求的同摘要复用、基于清单的请求重建与回退清单变更时的失败关闭；101 条回退记录稳定拆分为 100/1 两个子作业。
- 修改原因：防止并发或中途崩溃时产生新的作业 ID、覆盖请求或让不完整分块被 Zotero 过早确认。
- 如何运行：`..\\..\\.venv\\Scripts\\python.exe -m unittest tests.test_zotero_bridge.ZoteroBridgeRequestTests -v`；压力验证：`1..50 | ForEach-Object { ..\\..\\.venv\\Scripts\\python.exe -m unittest tests.test_zotero_bridge.ZoteroBridgeRequestTests.test_queue_publishes_a_stable_two_chunk_manifest }`。
- 生成的输出文件：测试仅在临时目录创建并清理桥接 JSON；未写入真实 `%LOCALAPPDATA%`、Zotero、PDF、Cookie、XPI 或打包文件。
- 如何检查是否成功：13 项聚焦测试通过，50 次独立压力运行均通过；每次仅有一个清单、两个一致的请求文件且无 `.tmp` 残留。
- 注意事项或潜在风险：本阶段只发布项目侧请求，尚未接收插件结果或启动真实 Zotero；插件仍必须以 `chunk_index/chunk_count` 作为一次确认的分块屏障。

## 2026-07-11 13:37:10 +08:00 — Task 3 Zotero 桥接结果校验与汇总 CSV

- 本次任务目标：仅在全部 Zotero 分块结果通过严格校验后，将其转换为现有 finalizer 可消费的五列 CSV。
- 新增、修改或删除的文件：修改 `paper_automation/zotero_bridge.py`、`paper_automation/batch_workflow.py`、`tests/test_zotero_bridge.py`、`tests/test_batch_workflow.py` 与本 `CHANGELOG.md`；未删除文件。
- 具体修改内容：新增插件结果字段、时间、身份、任务集合和状态白名单校验；新增清单/请求身份复核；使用临时文件、`fsync` 与硬链接原子发布完整 CSV，并在同名文件存在时创建不覆盖的 retry CSV；扩展插件端失败状态为 `user_cancelled`、`job_expired`、`job_id_conflict`、`plugin_error`。
- 修改原因：保证少任何一个分块、字段被篡改、结果任务不匹配或旧结果文件存在时，都不会误把不完整或覆盖性的 CSV 交给最终 PDF 汇总。
- 如何运行：`..\\..\\.venv\\Scripts\\python.exe -m unittest tests.test_zotero_bridge.ZoteroBridgeResultTests tests.test_batch_workflow.BatchFinalizeTests -v`。
- 生成的输出文件：测试在临时目录创建桥接 JSON、结果 JSON 和 CSV 后自动清理；未写入真实 `%LOCALAPPDATA%`、Zotero、PDF、Cookie、XPI 或打包文件。
- 如何检查是否成功：43 项聚焦测试通过；缺失第二分块时 canonical CSV 不存在，既有 CSV 保持字节不变，原子发布前读者看不到目标 CSV，恶意 `https://` 附件路径最终被标为 `not_pdf_response`。
- 注意事项或潜在风险：桥接层有意不信任或复制附件路径，实际 PDF 安全复核仍由既有 `finalize_batch()` 完成；真实插件结果和最终 CLI 编排属于后续任务。

## 2026-07-11 13:50:35 +08:00 — Task 4 Zotero 桥接恢复命令

- 本次任务目标：提供可重复执行的 `paper_batch.py zotero` 命令，使项目可在不重跑下载阶段的前提下排队、等待插件确认、接收结果并调用现有最终汇总。
- 新增、修改或删除的文件：修改 `paper_automation/zotero_bridge.py`、`paper_automation/batch_workflow.py`、`paper_batch.py`、`tests/test_zotero_bridge.py`、`tests/test_batch_workflow.py` 与本 `CHANGELOG.md`；未删除文件。
- 具体修改内容：新增 `BridgeRunResult` 和 `run_zotero_bridge()`；新增安全的公开批次路径/状态汇总辅助函数；第一次调用仅发布同一批次的固定作业，返回等待确认；随后同命令在结果齐全时合并 CSV 并调用 `finalize_batch()`；新增 `zotero --run-dir --library-id --wait-seconds` 子命令和无敏感内容的错误提示。
- 修改原因：让用户只需在 Zotero 中确认一次后重复同一条命令，无需手动管理 JSON、CSV、子作业 ID 或重新运行 OA/机构下载阶段。
- 如何运行：`..\\..\\.venv\\Scripts\\python.exe paper_batch.py zotero --run-dir "<已有批次目录>"`；如需在命令中等待结果，可加 `--wait-seconds 60`（范围 0–86400）。
- 生成的输出文件：实际运行时仅在 `%LOCALAPPDATA%\\PaperScraperDOI\\zotero-bridge\\v1` 建立桥接队列，并在批次 `working` 下安全创建结果 CSV；本次测试只使用临时目录，未写入真实 Zotero、PDF、Cookie、XPI 或打包文件。
- 如何检查是否成功：70 项桥接/CLI 聚焦测试、`compileall` 和 `git diff --check` 通过；完整离线回归为 344 项通过、2 项 Windows 符号链接权限跳过。首次命令应返回 3 并提示“请在 Zotero 中确认一次”，结果完整后同命令返回 0 并更新报告。
- 注意事项或潜在风险：若回退 CSV 被清空但批次状态仍有待 Zotero 条目，命令会以 `bridge_fallback_state_mismatch` 停止，避免误报完成；不会启动 Chrome/Edge、读取 Cookie 或自动打包。Zotero 9 插件实现和真实队列验证仍属于后续任务。

## 2026-07-11 14:13:25 +08:00 — Task 5 项目侧复审加固

- 本次任务目标：按 Ask Matt 的规格/规范双轴复审结果，加固项目侧 Zotero 桥接的恢复性、公开接口和错误提示覆盖。
- 新增、修改或删除的文件：修改 `paper_automation/zotero_bridge.py`、`paper_automation/batch_workflow.py`、`paper_batch.py`、`tests/test_zotero_bridge.py`、`tests/test_batch_workflow.py` 与本 `CHANGELOG.md`；未删除原始数据或用户文件。
- 具体修改内容：抽取共享的原子排他写入函数；公开 `publish_zotero_results_csv()`；消费结果时重新在 inbox/processing/archive 查找同一作业请求；完成汇总后将当前清单硬链接归档至 `working\\zotero_bridge_history\\` 并移除当前清单，以便剩余失败项生成新的作业 ID；finalize 后同步重写生成的 pending CSV；为每个桥接校验码提供显式的安全提示，并用测试防止遗漏。
- 修改原因：独立复审发现等待期间请求被插件移动后可能无法消费，以及插件失败结果会使下一次同命令恢复因旧回退 CSV/清单而失败；同时补齐计划声明的公共 CSV 接口和错误提示契约。
- 如何运行：`..\\..\\.venv\\Scripts\\python.exe -m unittest tests.test_zotero_bridge tests.test_batch_workflow.BatchCliTests -v`；完整回归：`..\\..\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`。
- 生成的输出文件：真实完成的桥接批次会在批次 `working\\zotero_bridge_history\\` 保存不可覆盖的旧清单硬链接；本次测试仅在系统临时目录创建并自动清理文件，未写入真实 Zotero、PDF、Cookie、XPI 或打包文件。
- 如何检查是否成功：双轴复审无硬性规范违规；修复后聚焦桥接/CLI 测试 75 项通过，完整离线回归连续两次各 348 项通过、2 项 Windows 符号链接权限跳过；安全扫描未匹配命令执行、网络下载、影子文献源或 SQLite 访问。
- 注意事项或潜在风险：归档只处理项目自动生成的 `zotero_bridge_jobs.json`，不会移动 Zotero 附件或用户 PDF；桥接结果完成后若仍有失败项，下一次 `zotero` 命令会创建新的确认批次。真实 Zotero 9 插件、测试配置文件安装和真实文献下载仍未执行。

## 2026-07-11 14:20:01 +08:00 — Zotero 9 插件 Task 1 骨架与生命周期

- 本次任务目标：建立只兼容 Zotero 9.0.x 的本地桥接插件骨架、菜单生命周期和可离线验证的 Node 测试入口。
- 新增、修改或删除的文件：新增 `zotero_bridge_plugin/manifest.json`、`bootstrap.js`、`content/bridge-runtime.js`、`locale/zh-CN/bridge.ftl`、`tests/plugin-structure.test.cjs`、`package.json`；修改本 `CHANGELOG.md`；未删除文件。
- 具体修改内容：固定插件 ID 与 Zotero 9.0.x 兼容范围；添加 install/startup/shutdown 等生命周期钩子和“立即检查/状态/撤销”Tools 菜单；运行时暂只维护定时器与中文状态提示，尚未处理队列或 Zotero 文库；添加中文 Fluent 文案及无 npm 依赖的测试脚本。
- 修改原因：先建立可加载、可测试且不含网络能力的最小容器，再逐步加入严格契约和受确认保护的写入逻辑。
- 如何运行：`node --test zotero_bridge_plugin/tests/plugin-structure.test.cjs`；可选语法检查：`node --check zotero_bridge_plugin/bootstrap.js` 与 `node --check zotero_bridge_plugin/content/bridge-runtime.js`。
- 生成的输出文件：仅新增插件源码和测试文件；未创建 XPI、未安装插件、未改写 Zotero 配置/数据库/集合/条目/附件，也未读取 Cookie 或启动浏览器。
- 如何检查是否成功：结构测试验证 manifest 仅目标 Zotero 9.0.x，bootstrap 包含完整生命周期且不含 `fetch`、`XMLHttpRequest`、`ServerSocket` 或 `WebSocket`；本次 2 项测试和语法检查均通过。
- 注意事项或潜在风险：当前 `scanNow()` 仍为空实现，菜单不会导入或下载文献；XPI 构建与安装仍需后续明确的集成审批，且本项目不会自动打包。

## 2026-07-11 14:47:34 +08:00 — Zotero 9 插件 Task 2 纯 JavaScript 契约核心

- 本次任务目标：在任何 Zotero 写入或用户确认之前，用可离线测试的纯 JavaScript 核心严格复核项目侧桥接请求，并提供确定性的条目匹配和结果行构造规则。
- 新增、修改或删除的文件：新增 `zotero_bridge_plugin/content/bridge-core.js` 与 `zotero_bridge_plugin/tests/bridge-core.test.cjs`；修改 `zotero_bridge_plugin/bootstrap.js` 和本 `CHANGELOG.md`；未删除文件。
- 具体修改内容：新增 UMD 形式的纯函数核心，严格校验请求字段、UUID v4、UTC 时间、分块参数、任务数量/长度、重复任务、过期时间和 `payload_sha256`；以稳定递归键排序和 UTF-8 Web Crypto SHA-256 与 Python 端规范 JSON 保持逐字节一致；新增 DOI、NFKC 标题、第一作者规范化及“标题 + 年份或第一作者”的唯一候选匹配；新增恰好五个字符串字段的成功/失败结果行辅助函数；bootstrap 在运行时之前加载该核心。
- 修改原因：让插件在接触真实 Zotero 文库前即可拒绝未知字段、篡改、过期、重复或歧义请求，并确保 JavaScript 与项目侧 Python 对同一请求计算相同摘要。
- 如何运行：`node --test zotero_bridge_plugin/tests/bridge-core.test.cjs`；结构回归：`node --test zotero_bridge_plugin/tests/plugin-structure.test.cjs`；可选语法检查：`node --check zotero_bridge_plugin/content/bridge-core.js`。
- 生成的输出文件：仅新增插件源码与离线测试；未创建桥接队列、结果 JSON、Zotero 条目/集合/附件、PDF、Cookie、XPI 或打包文件。
- 如何检查是否成功：5 项核心测试和 2 项结构测试均通过；固定跨语言样本摘要为 `a937810801620e767e03abb42e5af6699a2e7a3102a0252aed610144c0864219`，Node 与 Python 一致；`git diff --check` 退出码为 0。
- 注意事项或潜在风险：`validateRequest()` 因使用 Web Crypto 为异步函数，后续运行时必须 `await`；当前核心不读写文件、不联网、不调用 SQLite、`eval` 或外部命令，也尚未提示确认、处理队列或写入真实 Zotero。未启动 Chrome/Edge/Codex 浏览器，未安装或打包插件。

## 2026-07-11 15:01:54 +08:00 — Zotero 9 插件 Task 3 文件队列、分块屏障与一次确认

- 本次任务目标：让 Zotero 插件安全消费固定的本地桥接队列，只在同一 `run_id` 的全部分块完整且一致时确认一次，并保证取消时不产生任何 Zotero 文库写入。
- 新增、修改或删除的文件：重构 `zotero_bridge_plugin/content/bridge-runtime.js`；新增 `zotero_bridge_plugin/tests/bridge-runtime.test.cjs`；修改本 `CHANGELOG.md`；未删除文件。
- 具体修改内容：将运行时改为 Node/Zotero 共用的依赖注入工厂；固定 `%LOCALAPPDATA%\PaperScraperDOI\zotero-bridge\v1` 的 inbox/processing/outbox/archive/state 路径；使用严格文件名、JSON、请求摘要与状态文件校验；按 `run_id` 聚合并校验共享文库、集合、时间、分块总数、唯一分块位置和跨分块任务 ID；不完整批次原地等待，不一致批次不弹窗并输出 `plugin_error`；完整批次只显示一次含文库名称/ID、总条数、集合名和“现有附件不会被修改”的原生确认；取消时为每项生成 `user_cancelled` 严格结果并归档请求；确认凭据仅在作业 ID 与摘要数组完全相同时复用；并发扫描合并为同一个内存 Promise，防止定时器积压。
- 修改原因：避免分块尚未齐全、请求被篡改、状态损坏、重复扫描或用户取消时误写 Zotero，同时为后续条目解析和 PDF 获取提供可恢复的 processing 状态。
- 如何运行：`node --test zotero_bridge_plugin/tests/bridge-runtime.test.cjs`；全部插件测试：`node --test zotero_bridge_plugin/tests/*.test.cjs`；语法检查：`node --check zotero_bridge_plugin/content/bridge-runtime.js`；压力测试可将运行时测试循环执行 50 次。
- 生成的输出文件：真实启用后可在固定桥接根目录原子创建 `plugin-state.json` 和 `<job_id>.result.json`，并在队列目录间排他移动请求；本次测试全部使用内存假 I/O，未写真实 `%LOCALAPPDATA%`、Zotero 文库、集合、条目、附件、PDF、Cookie、XPI 或打包文件。
- 如何检查是否成功：13 项运行时测试与插件侧合计 20 项测试通过；测试确认不完整分块零提示、无效/不一致分块零 Zotero 写入、取消逐任务返回、状态精确持久化、并发扫描共享一个 Promise、结果文件不覆盖既有字节且临时文件通过 `noOverwrite` 移动发布；本机 Zotero 9.0.6 自带源码静态核对确认 `IOUtils.move(..., { noOverwrite: true })`、`mode: "create"`、`tmpPath` 与 `PathUtils.filename()` 可用。
- 注意事项或潜在风险：当前已确认批次会安全停留在 processing，真正的 Zotero 条目解析、集合写入和可用 PDF 操作属于 Task 4，尚未执行；进度检查点与撤销账本属于后续任务。插件仍未打包或安装，未启动 Chrome/Edge/Codex 浏览器，未联网、未读取 Cookie，也未调用真实 Zotero 写 API。

## 2026-07-11 15:19:25 +08:00 — Zotero 9 插件 Task 4 条目解析、标识符导入与可用 PDF

- 本次任务目标：在一次批次确认之后，安全查找已有 Zotero 条目、必要时按 DOI 调用 Zotero 标识符导入、加入批次集合，并仅为缺少本地 PDF 的条目调用一次 Zotero“可用 PDF”能力。
- 新增、修改或删除的文件：修改 `zotero_bridge_plugin/content/bridge-runtime.js`、`zotero_bridge_plugin/tests/bridge-runtime.test.cjs` 与本 `CHANGELOG.md`；未新增或删除其他文件，未修改原始文献清单或 PDF。
- 具体修改内容：新增并公开 `resolveItem()`、`findPDFAttachment()`、`importByDOI()`、`ensureCollection()`、`addAvailablePDFOnce()` 和 `processItem()`；DOI 查找使用目标 `libraryID` 内的精确条件并再次规范化复核，多个精确命中返回 `metadata_uncertain`；无 DOI 时只使用有年份或第一作者佐证的严格标题匹配；排除 feed、附件/笔记/批注等非普通条目、已删除条目及跨文库候选；导入使用 `Zotero.Translate.Search.setIdentifier({ DOI })` 与 `translate({ libraryID, collections: [collectionID], saveAttachments: false })`，导入后再次核验 DOI；集合使用 Zotero 9.0.6 的 `Collections.getByLibrary()` 精确查名，避免把条目搜索结果误当集合 ID；已有本地 PDF 直接返回 `existing_pdf`，否则只调用一次 `Attachments.addAvailablePDF()`，成功返回 `downloaded`，无附件返回 `no_pdf`；每个条目独立捕获安全错误，单条失败不会中止后续条目。
- 修改原因：实现用户“给清单后尽量自动获得最终 PDF”的 Zotero 端核心动作，同时避免模糊匹配、重复 DOI、错误文库、非本地路径或既有附件被改写；本机 Zotero 9.0.6 静态源码核对发现原计划的集合搜索示例会混淆条目 ID 与集合 ID，因此改用其真实集合 API。
- 如何运行：聚焦测试 `node --test zotero_bridge_plugin/tests/bridge-runtime.test.cjs`；全部插件回归 `node --test zotero_bridge_plugin/tests/*.test.cjs`；语法检查 `node --check zotero_bridge_plugin/content/bridge-runtime.js`。
- 生成的输出文件：真实启用后每个作业会在 outbox 原子发布严格结果 JSON，并把处理完的请求移入 archive；成功行只返回 Zotero 条目 ID 与现有/新下载附件的绝对 Windows 路径。此次测试仅使用内存 Zotero/文件系统替身，未创建真实集合、条目、附件、PDF、队列文件、Cookie、XPI 或打包文件。
- 如何检查是否成功：23 项运行时测试和插件侧合计 30 项测试全部通过；覆盖已有 PDF 零导入/零下载调用、集合成员只加一次、标识符导入不保存翻译器附件、导入 DOI 二次校验、候选资格过滤、重复 DOI/标题歧义零写入、单条异常隔离、无 PDF、API 缺失零 Zotero 写入，以及 URL/相对路径/非 PDF 附件拒绝；语法、差异与安全扫描均通过。另已从本机 Zotero 9.0.6 自带源码确认 Translate 选项、`getByLibrary()`、`addAvailablePDF()`、附件路径方法和集合成员方法签名。
- 注意事项或潜在风险：本阶段尚未安装或调用真实插件，因此 Zotero 的登录状态、机构授权、网络、出版商限制与 CAPTCHA 仍未实测且不会被绕过；`addAvailablePDF()` 真实运行时可能联网，但本次没有联网或启动 Chrome/Edge/Codex 浏览器。崩溃发生在 Zotero 写入之后、结果 JSON 发布之前时的逐项检查点，以及新建条目/附件/集合成员的可审计撤销账本仍属于 Task 5；在该保护完成前不会打包或安装插件。

## 2026-07-11 15:48:04 +08:00 — Zotero 9 插件 Task 5 断点恢复、状态与安全撤销

- 本次任务目标：使已确认批次在 Zotero 或插件中断后从最后一个完整条目继续，保证结果不重复覆盖，并为本批次新建条目、附件及集合成员关系提供可审计、不可重复的二次确认撤销。
- 新增、修改或删除的文件：修改 `zotero_bridge_plugin/content/bridge-runtime.js`、`zotero_bridge_plugin/tests/bridge-runtime.test.cjs`、`zotero_bridge_plugin/locale/zh-CN/bridge.ftl` 与本 `CHANGELOG.md`；未删除文件，未修改原始文献数据或 PDF。
- 具体修改内容：为每个作业新增严格的 `processing\<job_id>.progress.json`，精确保存请求身份、已完成结果行、批次创建的条目/附件 ID 和新增集合成员关系；每完成一项即原子替换进度，重启时只接受与请求 job/hash 和任务顺序完全一致的进度；完整结果存在时复核身份及逐行内容并保持原字节，不覆盖或删除唯一结果；全部任务完成后将 run 标记为 `completed`，保存跨作业撤销账本并依次归档 progress/request；状态菜单可从持久化状态恢复并显示批次、等待/运行/完成/撤销阶段及总数/成功/失败；撤销前显示三类精确数量并再次确认，先移除仅对预存条目新增的成员关系，再删除账本记录且身份仍匹配的新附件和新条目，预存 ID、跨文库/已移动对象和活动批次均不处理，撤销结果持久化后禁止重复执行。
- 修改原因：防止 Zotero 网络请求、应用退出或文件发布中断导致整批重跑、重复导入、重复下载、结果覆盖或误删用户已有资料，并让用户能在菜单中直接判断批次是否仍需等待。
- 如何运行：聚焦测试 `node --test zotero_bridge_plugin/tests/bridge-runtime.test.cjs`；全部插件回归 `node --test zotero_bridge_plugin/tests/*.test.cjs`；语法检查 `node --check zotero_bridge_plugin/content/bridge-runtime.js`；安全扫描 `rg -n "zotero\.sqlite|executeTransaction|queryAsync|eval\(|Function\(|fetch\(|XMLHttpRequest|WebSocket|ServerSocket" zotero_bridge_plugin/content zotero_bridge_plugin/bootstrap.js`。
- 生成的输出文件：真实启用后会生成/更新 `plugin-state.json`、`processing\<job_id>.progress.json`、`outbox\<job_id>.result.json`，并把完成的请求和进度移至 archive；撤销只修改账本授权且身份仍匹配的 Zotero 对象。本次测试仅使用共享内存文件系统和假 Zotero，对真实 `%LOCALAPPDATA%`、Zotero 文库、PDF、Cookie、XPI 与安装配置均无写入。
- 如何检查是否成功：32 项运行时测试及插件侧合计 39 项测试连续运行两次均通过；覆盖三条任务在第一条后中断并无二次确认续跑、进度 task ID 篡改拒绝、已发布结果原字节重放、完成状态/进度归档、实际生成账本撤销“预存 + 导入”混合批次、撤销取消零写入、预存 ID 不删除、身份变化跳过并报告、活动批次阻止撤销、撤销不可重复，以及重启后状态摘要恢复；语法与差异检查通过，源码安全扫描零匹配，插件全目录唯一匹配来自测试自身的禁止字符串清单。
- 注意事项或潜在风险：真实 Zotero 写 API 返回与进度文件落盘之间仍存在极短的进程硬终止窗口；重启时会通过 DOI 查重、集合幂等和已有 PDF 复核避免重复动作，但极端断电下撤销账本可能需要真实配置测试确认完整性。当前仍未联网、未启动 Chrome/Edge/Codex 浏览器、未读取 Cookie、未安装或打包插件；真实机构授权、出版商限制和 CAPTCHA 不会被绕过，留待隔离测试配置验收。

## 2026-07-11 15:54:53 +08:00 — Zotero 9 插件 Task 6 手工构建器与初学者说明

- 本次任务目标：提供仅在用户明确运行时才创建 XPI 的白名单构建器，并给出面向初学者的测试、构建、批处理与安全检查说明；本阶段不实际打包或安装。
- 新增、修改或删除的文件：新增 `build_zotero_bridge_xpi.ps1`、`zotero_bridge_plugin/README.md`、`tests/test_zotero_bridge_packaging.py`；修改本 `CHANGELOG.md`；未删除文件，未修改现有启动、Skill 安装或 Windows UI 打包脚本。
- 具体修改内容：构建器要求显式 `-OutputDirectory`，默认拒绝覆盖并只在 `-Force` 时允许替换；拒绝输出目录位于插件源码内部；从 manifest 读取语义版本，只复制根级 `manifest.json`/`bootstrap.js` 和 `content`/`locale` 两个目录；显式排除 tests、package、Git、日志、状态/进度、Cookie 与环境文件；以随机临时 staging 和同输出目录临时 zip/xpi 工作，使用 `Compress-Archive` 后通过 `tar -tf` 验证根级入口和禁止项，最后同目录移动到版本化 XPI；finally 只清理经确认位于系统临时目录的随机 staging 与精确临时文件。README 说明 Zotero 9.0.x 范围、离线测试、需明确批准的手工构建命令、输入/输出/成功标准、最终批处理流程和禁止绕过访问控制。
- 修改原因：让后续集成验收具备可复现、可审计且不夹带测试/凭据/队列的打包方式，同时严格遵守“修改后不自动打包”和“先在独立 Zotero 测试配置验证”的要求。
- 如何运行：源码契约测试 `..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge_packaging -v`；插件测试 `node --test zotero_bridge_plugin/tests/*.test.cjs`；仅语法检查可调用 PowerShell AST `Parser.ParseFile()`。真正构建命令记录于插件 README，但本次未运行。
- 生成的输出文件：仅生成构建脚本、README 和测试源码；仓库内仍无 `.xpi`，`dist` 未因本任务创建或修改，也未安装任何 Zotero 扩展。
- 如何检查是否成功：构建契约先因脚本/README 缺失按预期 5 项失败，实施后 7 项全部通过；PowerShell AST 解析无语法错误；递归检查确认仓库内无 XPI；现有启动、Skill 安装和 UI 打包脚本均不引用该构建器。
- 注意事项或潜在风险：构建器本身尚未实际执行，因此真实 zip/xpi 内容和 Zotero 加载仍必须在用户明确批准打包后验证；`-Force` 会替换用户明确指定输出目录中的同版本 XPI，请仅在确认旧产物可替换时使用。未联网、未启动浏览器、未访问真实 Zotero/Cookie/PDF。

## 2026-07-11 17:18:52 +08:00 — Zotero 9 插件双轴复审与耐久性加固

- 本次任务目标：根据 Ask Matt 的 Standards/Spec 双轴独立复审，加固 Zotero 9 本地桥接在崩溃、取消、分块归档、撤销与构建替换边界上的可恢复性，并以生产适配器测试确认关键 Zotero 9 API 参数。
- 新增、修改或删除的文件：修改 `build_zotero_bridge_xpi.ps1`、`tests/test_zotero_bridge_packaging.py`、`zotero_bridge_plugin/README.md`、`zotero_bridge_plugin/content/bridge-runtime.js` 与 `zotero_bridge_plugin/tests/bridge-runtime.test.cjs`；新增 `zotero_bridge_plugin/tests/zotero-adapter.test.cjs`；修改本 `CHANGELOG.md`。未删除原始数据、PDF、Cookie、Zotero 条目或用户文件。
- 具体修改内容：构建器保留 Windows 卷根并用同卷 `File.Replace` 完成 `-Force` 原子替换，扩大队列/账本禁止项并动态验证输出落入源码树时会在归档前拒绝；取消标记在结果与归档前持久化，重启可无二次确认完成；导入条目、集合成员和新附件在每次 Zotero 写入后立即检查点；新建集合写入严格、不可变的 `.collection.json` 账本并按数值 ID 恢复；撤销在首次写入前持久化 `undo_started_at`，并发撤销共享一个 Promise，扫描与撤销串行；每个批次处理后重新加载 state，防止同次扫描覆盖前一批完成状态；确认批次及取消批次均可从严格身份账本补读已归档分块，修复“只归档第一块后崩溃”永久 `incomplete`；重启后的新附件仍保留“本批次创建”身份并可安全撤销；生产 IIFE 通过 VM 测试精确验证 `translate({ libraryID, collections: [id], saveAttachments: false })`、集合创建标志及 `Collections.getAsync([id])` 恢复调用。
- 修改原因：独立复审发现状态对象陈旧、逐次写入与检查点之间的恢复窗口、分块请求部分归档、取消批次缺少 state 身份、创建附件重启后被误列为预存、构建替换非原子等问题；这些问题可能导致重复提示、重复下载、账本遗漏、无法撤销或批次永久等待。
- 如何运行：`node --test zotero_bridge_plugin/tests/bridge-runtime.test.cjs`；`node --test zotero_bridge_plugin/tests/*.test.cjs`；`node --check zotero_bridge_plugin/content/bridge-runtime.js`；`..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge_packaging -v`；PowerShell AST 仅解析 `build_zotero_bridge_xpi.ps1`；安全扫描仅覆盖插件生产代码。
- 生成的输出文件：只新增或修改插件源码、构建脚本、说明和离线测试；测试使用内存文件系统或系统临时目录。未生成 XPI，未写真实 `%LOCALAPPDATA%` 队列、Zotero 主/测试配置、文库、附件、PDF 或 Cookie，也未启动浏览器。
- 如何检查是否成功：新增问题均先以失败用例复现再修复；当前运行时 43 项、插件合计 53 项通过，生产适配器 3 项通过；此前构建契约 10 项、PowerShell AST、源码安全扫描与递归无 XPI 检查均通过。最终提交前仍会再跑两次插件回归、完整 Python 回归、compileall、`git diff --check` 与无 XPI 检查。
- 注意事项或潜在风险：真实 Zotero 9 API、真实机构访问和真实磁盘崩溃窗口尚未在隔离配置中验收；必须获得用户下一次明确批准后才可生成测试 XPI，并且只能先安装到 `Zotero test` 配置。历史提交 `c14a75a` 只追踪 Task 1 变更记录中已列出的文件，没有额外内容修改或 Git 历史重写；真实构建仍按明确审批门禁延期。

## 2026-07-11 17:19:12 +08:00 — 项目—Zotero 桥接离线端到端验收

- 本次任务目标：通过公开 CLI/桥接接口验证“项目先下载，只有失败项进入 Zotero，结果回到项目并只复制最终 PDF”的完整离线路径，确认无需修改现有生产 Python 代码即可闭环。
- 新增、修改或删除的文件：新增 `tests/test_zotero_bridge_integration.py`；修改本 `CHANGELOG.md`。未修改项目生产 Python、原始文献清单或真实 PDF。
- 具体修改内容：新增三条端到端用例：其一组合项目已有 PDF、假 Zotero 已有 PDF 和 `no_pdf`，验证最终 `pdfs\` 只含两个内容哈希唯一的 PDF、源文件字节不变、报告齐全且重复运行完全幂等；其二注入摘要不匹配、未知字段、重复任务和超长非法附件路径，验证 state、PDF 与报告不被污染；其三把 101 条失败项分为 100/1 两个作业，验证部分结果不会创建 `zotero_results.csv` 或调用 finalize，齐全后按原任务顺序生成 101 行并且只 finalize 一次。
- 修改原因：把项目侧与插件侧此前分别验证的严格协议连成一个可复现的验收边界，防止“单模块测试通过但最终 PDF 汇总、分块屏障或幂等性失效”。
- 如何运行：`..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge_integration tests.test_zotero_bridge tests.test_batch_workflow.BatchEndToEndTests -v`；完整回归使用 `..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v`。
- 生成的输出文件：测试只在系统临时目录创建假批次、假 PDF、桥接 JSON/CSV 与报告并自动清理；不会联网、调用真实 Zotero、读取 Cookie、启动浏览器或生成 XPI。
- 如何检查是否成功：严格 TDD 的 RED 阶段先因集成测试模块缺失失败；实现后聚焦端到端/桥接/批次测试 59 项通过，随后完整 Python 离线回归 364 项通过、2 项按环境跳过。最终提交前将再次完整验证。
- 注意事项或潜在风险：离线替身能验证协议、排序、摘要、路径和非覆盖行为，但不能替代 Zotero 9 真实插件加载、权限、机构网络、出版社限制或 CAPTCHA 验收；这些仍受隔离测试配置与用户明确批准约束。

## 2026-07-11 17:21:18 +08:00 — paper-download bridge-first Skill 与新手文档

- 本次任务目标：把 `paper-download` 的正常 Zotero 回退从直接 LLM/MCP 写入改为项目—插件本地文件桥，并为已有批次提供不可歧义、最少人工操作的继续入口。
- 新增、修改或删除的文件：修改 `skills/paper-download/SKILL.md`、`tests/test_skills_packaging.py`、`README.md`、`README_zh.md` 与 `MANUAL_QA.md`；新增 `docs/zotero_bridge_beginner_guide.md`；修改本 `CHANGELOG.md`。未删除原始清单、PDF 或用户资料。
- 具体修改内容：正常流程固定为 `paper_batch.py start`、最多一次 `resume`、再执行 `paper_batch.py zotero`；只有 `working\zotero_fallback.csv` 行进入桥接，退出码 3 只要求保持 Zotero 打开并批准一次批次确认，随后重跑同一 `zotero` 命令自动消费结果和 finalize；禁止正常路径直接 Zotero MCP 写入、手工构造插件结果或重复导入。对已给出 `<run-dir>` 且人工 retry 已完成的场景，首要规则明确覆盖后续所有章节：不查看/运行 `paper_skill.py`，不猜 `zotero-fallback`、`--input`、`--wait`，第一条且唯一可执行命令就是 `paper_batch.py zotero --run-dir "<run-dir>"`。保留桥不可用时严格五列 CSV、排他创建和 `zotero_unavailable` 的可恢复分支。中英文 README、新手指南和隔离 QA 统一说明队列、最终 `pdfs\`/`reports\`、非覆盖边界与测试配置门禁。
- 修改原因：旧 Skill 依赖工具代理自行拼接 Zotero 操作，容易多次确认、猜错 CLI 或重跑已完成阶段；本地桥可把确认、分块、摘要、状态和 PDF 汇总交给确定性代码。
- 如何运行：`..\..\.venv\Scripts\python.exe -m unittest tests.test_skills_packaging -v`；`python -X utf8 C:\Users\wkguopro\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills\paper-download`；正向测试使用全新只读代理完整读取 Skill 后回答已有批次场景。
- 生成的输出文件：只新增/修改 Skill、测试和文档；没有创建真实批次、桥接队列、PDF、Cookie、XPI 或 Zotero 对象，也没有启动浏览器。
- 如何检查是否成功：Skill 合同 23 项通过，`quick_validate.py` 返回 `Skill is valid!`；初始正向测试暴露旧入口猜测后，新增首要覆盖规则和静态断言；最终全新代理只返回 `.\.venv\Scripts\python.exe paper_batch.py zotero --run-dir "C:\Research\results\paper_batch_20260711_090000"`，并把退出码 3 后的人工动作限定为保持 Zotero 打开和批准唯一一次确认。
- 注意事项或潜在风险：Skill 只能编排已实现的本地桥，不能替代尚未进行的真实 Zotero 9 插件加载验收；桥不可用、权限不足或无可用 PDF 时必须保留失败状态，不能报告为完成。文档不会授权绕过登录、CAPTCHA、机构权限或出版商限制。

## 2026-07-11 17:43:16 +08:00 — 第二轮安全复审：写前意图、撤销防重放与嵌套构建排除

- 本次任务目标：修复 Spec/Safety 复核发现的 Zotero 写入—账本极短窗口、撤销动作重放和允许目录内嵌套禁止项进入 XPI 三个边界问题。
- 新增、修改或删除的文件：修改 `zotero_bridge_plugin/content/bridge-runtime.js`、`zotero_bridge_plugin/tests/bridge-runtime.test.cjs`、`zotero_bridge_plugin/tests/zotero-adapter.test.cjs`、`zotero_bridge_plugin/README.md`、`build_zotero_bridge_xpi.ps1`、`tests/test_zotero_bridge_packaging.py`、`MANUAL_QA.md` 与本 `CHANGELOG.md`；未删除文件或用户数据。
- 具体修改内容：进度格式增加严格 `pending_write`，在集合创建、DOI translator 导入、集合成员保存和可用 PDF 写入前先原子记录意图；集合标记区分 `pending/complete`，附件意图记录写前 ID 快照；重启以 DOI、任务、文库、集合 ID、条目 ID、成员状态和新增附件差集对账，只有一致时才恢复本批所有权，歧义时保持可恢复并安全停止。撤销账本增加严格 `undo_progress`，每个成员删除、附件删除和条目删除前记录 `pending_action`，动作后逐项落盘；若崩溃后结果无法证明，重启把账本对象记为 `skipped` 且绝不重放破坏性动作。构建器新增 `Test-ForbiddenArchivePath`，对路径每一级 segment 应用 `tests`、`.git`、日志、状态/结果/Cookie 等禁止模式，并在 staging 与临时 archive 两次验证。
- 修改原因：只做“写后检查点”仍可能在 Zotero 已提交而文件账本尚未落盘时把本批对象误判为预存；撤销只记录开始/结束会在重启时再次删除用户刚恢复的成员关系；旧 glob 只覆盖根级或末尾名称，`content/tests/...` 与 `content/.git/...` 可能绕过。
- 如何运行：`node --test --test-name-pattern "ownership survives a crash" zotero_bridge_plugin/tests/bridge-runtime.test.cjs`；`node --test --test-name-pattern "never replays a membership removal" zotero_bridge_plugin/tests/bridge-runtime.test.cjs`；`node --test zotero_bridge_plugin/tests/*.test.cjs`；`..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge_packaging -v`；`node --check zotero_bridge_plugin/content/bridge-runtime.js`；PowerShell AST 解析构建器。
- 生成的输出文件：仅源码、说明与离线内存/静态测试发生变化；未构建 XPI，未写真实 Zotero、队列、PDF、Cookie 或浏览器配置。
- 如何检查是否成功：四种“Zotero 写入已发生、所有权检查点尚未完成”用例均先失败后通过；“成员已删除后崩溃、用户重新加入、重启不得再删”用例先失败后通过；生产适配器验证顺序为 `checkpoint:intent → translate → checkpoint:complete`；当前插件 59 项、运行时 48 项、生产适配器 4 项和构建契约 11 项全部通过，语法检查通过。提交前仍会运行第二遍插件测试及完整 Python 回归。
- 注意事项或潜在风险：写前意图能把进程崩溃窗口转为可审计对账，但真实 Zotero 9 在极端断电、外部并发人工编辑或 API 非标准返回下仍必须在隔离测试配置验证；无法唯一证明的对象会安全停止或标为跳过，而不会猜测所有权或删除。真实打包和安装继续等待用户明确批准。

## 2026-07-11 17:51:59 +08:00 — 取消恢复 archive 轮询与同名 state 身份加固

- 本次任务目标：消除 Zotero 插件空闲轮询对历史 archive 的无上限 I/O，并确保旧的同名 `run_id` state 不会阻止新取消批次的部分归档恢复。
- 新增、修改或删除的文件：修改 `zotero_bridge_plugin/content/bridge-runtime.js`、`zotero_bridge_plugin/tests/bridge-runtime.test.cjs` 与本 `CHANGELOG.md`；未删除文件或数据。
- 具体修改内容：内存 I/O 增加独立 list/read 审计；只有当活动 run 没有匹配的 state job/hash 身份、至少一个请求已在 processing、且活动 chunk 数少于声明数时才扫描取消标记；完全空闲、普通不完整 inbox 和已有匹配 state 的确认批次均不访问 archive。门控不再只看 `run_id` 名称，而是要求 state 中某个 `job_id` 及其对应 `payload_sha256` 与活动请求实际匹配；同名但不同身份时仍允许从严格取消标记恢复归档分块。
- 修改原因：插件每秒轮询，旧实现即使空闲也会重复列举并解析持续增长的历史取消标记；第一次门控又可能被同名旧 state 误导，使新的取消批次永久停在 `incomplete`。
- 如何运行：`node --test --test-name-pattern "idle polling never|old state with the same run id|multi-chunk cancellation interrupted" zotero_bridge_plugin/tests/bridge-runtime.test.cjs`；全套插件测试 `node --test zotero_bridge_plugin/tests/*.test.cjs`。
- 生成的输出文件：仅运行内存队列测试；未访问真实 archive、Zotero、PDF、Cookie、XPI 或浏览器。
- 如何检查是否成功：空闲回归在修复前记录 3 次 archive 枚举，修复后连续 3 次 scan 为 0 次枚举和 0 次历史标记读取；同名旧 state 用例在修复前 `completeRuns=0`，修复后 `completeRuns=1`、`incompleteRuns=0`、仅一次提示且两分块均归档；当前插件 61 项全部通过。
- 注意事项或潜在风险：真正需要恢复“取消后部分归档”的罕见场景仍会按需扫描 archive，这是找回未知首分块 job ID 所必需的审计路径；正常空闲轮询不会承担该成本。真实配置验收与 XPI 门禁不变。

## 2026-07-11 18:08:52 +08:00 — 并发歧义保守封存与 reparse 路径防护

- 本次任务目标：修正写前意图在外部并发编辑下仍可能误认所有权的问题，并阻止 junction/symlink 绕过构建器的源码目录保护。
- 新增、修改或删除的文件：修改 `zotero_bridge_plugin/content/bridge-runtime.js`、`zotero_bridge_plugin/tests/bridge-runtime.test.cjs`、`zotero_bridge_plugin/README.md`、`build_zotero_bridge_xpi.ps1`、`tests/test_zotero_bridge_packaging.py`、`MANUAL_QA.md` 与本 `CHANGELOG.md`；未删除文件或用户数据。
- 具体修改内容：本记录明确替代 17:43 记录中“根据当前 Zotero 状态恢复未完成写入所有权”的乐观策略。任何未完成 `pending_write` 或 pending collection marker 都不再读取当前对象来猜测归属，也不再重试 Zotero 写入；插件把“清除 pending + `plugin_error/write_outcome_uncertain` 行”放入同一次原子 progress 替换，随后只保留审计失败，所有 created/added 撤销账本为空。构建器新增 `Assert-NoReparsePointInPath`，在创建输出目录前逐级检查插件路径与输出路径的每个现存祖先，并递归拒绝源码树内任何 `FileAttributes.ReparsePoint`；因此外部 junction 指向插件源码和内部 symlink 均会停止。
- 修改原因：写前意图只能证明插件准备执行，不能证明随后观察到的对象一定由插件创建；外部并发新增会被误认并在撤销时删除，外部删除又可能触发二次 import、成员写入或 PDF 请求。词法 `GetFullPath` 也不能识别 junction 的最终目标，单纯字符串前缀检查可被绕过。
- 如何运行：`node --test --test-name-pattern "an uncertain" zotero_bridge_plugin/tests/bridge-runtime.test.cjs`；`node --test zotero_bridge_plugin/tests/bridge-runtime.test.cjs`；`..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge_packaging.ZoteroBridgePackagingTests.test_builder_rejects_reparse_points_before_creating_output tests.test_zotero_bridge_packaging.ZoteroBridgePackagingTests.test_reparse_guard_rejects_a_real_junction_without_building_xpi -v`；PowerShell AST 解析构建器。
- 生成的输出文件：离线运行时测试只使用内存对象；junction 反例只在忽略的 `.codex-test-tmp` 创建唯一临时 target/link，直接提取并执行保护函数，不执行构建器主体，随后用非递归删除清理。未生成 XPI、Zotero 对象、真实队列、PDF、Cookie 或浏览器状态。
- 如何检查是否成功：四个并发/删除反例修复前分别出现误认、二次 import/成员/PDF 写入，修复后全部得到 `write_outcome_uncertain`，Zotero 写调用不增加且撤销账本不认领对象；运行时 50 项通过。静态顺序测试确认 reparse 检查早于输出 `New-Item`，真实 junction 保护函数反例返回 `REPARSE_REJECT_OK`；构建器 AST 通过，仓库 XPI 数量为 0。
- 注意事项或潜在风险：该策略优先保护用户文库，代价是极罕见的写入—检查点崩溃任务会作为失败保留，可能需要在隔离配置中人工判断是否已有可用对象；插件不会自动猜测、自动重试或删除。真实 XPI 构建与安装仍等待用户明确批准。

## 2026-07-11 18:19:36 +08:00 — 最终离线验收与双轴复核结论

- 本次任务目标：在提交前汇总并复跑项目、插件、构建器、Skill 与安全边界，确认没有剩余审查 finding，且不越过真实 XPI/Zotero 测试配置审批门禁。
- 新增、修改或删除的文件：仅追加本 `CHANGELOG.md` 验证记录；本次验收未再修改生产代码、测试逻辑、原始清单或 PDF。
- 具体修改内容：最终 uncertain 恢复封存已提前到任何 `assertProcessingAPI()` 之前；同批仍有正常任务时，本次扫描只做本地原子封存并返回，下一次扫描才恢复 Zotero 访问。独立 Ask Matt Standards 与 Spec/Safety 审查者最终均明确返回 `no findings`；混合任务反例的 preflight 计数为 `1 → 1 → 2`。
- 修改原因：为后续隔离 Zotero 配置验收提供可审计基线，避免把单次聚焦测试、静态检查或审查中间状态误当成最终完成。
- 如何运行：Python 全套 `..\..\.venv\Scripts\python.exe -m unittest discover -s tests`；插件全套连续两次 `node --test zotero_bridge_plugin/tests/*.test.cjs`；构建器 `..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge_packaging -v` 与 PowerShell AST；`node --check zotero_bridge_plugin/content/bridge-runtime.js`；`git diff --check`；生产代码安全 `rg` 扫描；Skill 使用系统 `python -X utf8 ...\quick_validate.py skills\paper-download`；递归 XPI 计数。
- 生成的输出文件：测试仅使用系统临时目录、内存替身和已忽略的 `.codex-test-tmp`，临时 junction 已清理；没有生成 XPI、真实桥接队列、Zotero 条目/集合/附件、PDF、Cookie 或浏览器配置。
- 如何检查是否成功：Python 367 项通过、2 项按环境跳过；聚焦桥接/Skill/构建此前 93 项通过；插件连续两次各 61 项通过，其中 runtime 50 项、生产适配器 4 项；构建器 13 项通过；compileall、Skill validator、PowerShell AST、JavaScript 语法、`git diff --check` 与安全扫描均通过；XPI 数量为 0。完整 Python 测试中的 Edge/浏览器文字来自 mock 日志，本次未启动任何浏览器。
- 注意事项或潜在风险：项目 venv 缺少 Skill validator 所需的 `PyYAML`，因此使用机器上已配置且可成功校验的系统 Python，没有安装新依赖。所有结论仍是源码与离线替身层面的；真实 Zotero 9.0.x 加载、真实 API 行为、登录/机构授权、出版商限制和 PDF 可得性必须在用户明确批准后，仅于 `Zotero test` 配置验收。
## 2026-07-11 23:47:47 +08:00 — 整理并合并开发分支

- 本次任务目标：盘点本地 Git 分支，将完整的 Zotero 论文下载开发线安全合并到 `main`，并识别可清理的重复分支。
- 新增、修改或删除的文件：合并 `codex/zotero-paper-download` 中的 Zotero bridge、批处理流程、测试、文档和插件源码；解决 `CHANGELOG.md`、`WINDOWS_UI_README.md`、`paper_skill.py`、`skills/paper-download/SKILL.md`、`tests/test_windows_paths.py`、`windows_paths.py` 的合并冲突；未修改或删除原始实验数据。
- 具体修改内容：先将 `main` 原有 14 个未提交文件保存为独立安全提交；合并综合开发线；保留双方变更记录；保留 `main` 中默认 Chrome 且不隐式选择 Edge 的实现；采用 bridge-first PDF 下载 Skill 与合法开放获取描述；补充 Skill 描述中的显式 `PDF` 关键词以满足打包测试。
- 修改原因：综合分支包含最完整的统一批处理与 Zotero 9 本地桥接能力，其他两个分支与其存在大量共同或重复开发，需要先建立可验证的统一主线再清理。
- 生成的输出文件：无论文 PDF、实验数据或安装包；未自动打包项目。
- 如何检查是否成功：运行 `\.venv\Scripts\python.exe -m compileall paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation paper_batch.py`，再运行 `\.venv\Scripts\python.exe -m unittest discover -s tests -v`；两条命令均应返回退出码 0。
- 注意事项或潜在风险：本次仅整理本地分支，不推送远程；删除 worktree 和冗余分支前必须确认其工作区干净且功能已被 `main` 覆盖。
- 清理前补充保护：从综合 worktree 合入 Windows PowerShell 5.1 不支持 `System.IO.Path.GetRelativePath` 的兼容修复，并增加静态回归断言；将 beginner CLI worktree 中未跟踪的 Task 6 报告保存为 `.superpowers/sdd/task-6-report.md`，避免清理 worktree 时丢失记录。
- 补充检查方法：运行 `\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge_packaging -v`；测试不得在仓库中留下 `.xpi`。本次没有执行构建脚本，也没有自动打包。
- 最终清理结果：已移除 `.worktrees/codex-task6-beginner-cli`、`.worktrees/codex-zotero-paper-download`、`.worktrees/codex-zotero9-plugin-only`，并删除对应三个本地分支；保留 `main` 与 `origin/main`，未删除远程分支，未推送。
## 2026-07-12 00:16:19 +08:00 — 生成 Zotero 9 测试 XPI并启动测试配置

- 修改日期和时间：2026-07-12 00:16:19 +08:00。
- 本次任务目标：在用户明确批准后生成自研 Zotero 9 桥接插件测试 XPI，并仅针对独立 `Zotero test` 配置开始安装验收，不触碰主 Zotero 配置。
- 新增、修改或删除的文件：生成被 Git 忽略的 `dist/zotero-test/zotero-paper-download-bridge-0.1.0.xpi`；追加本 `CHANGELOG.md`；未删除或覆盖源码、原始数据、PDF、Cookie 或 Zotero 主配置文件。
- 具体修改内容：使用 `build_zotero_bridge_xpi.ps1` 的白名单构建流程生成 XPI；校验压缩包只含 `manifest.json`、`bootstrap.js`、`content/bridge-core.js`、`content/bridge-runtime.js` 和 `locale/zh-CN/bridge.ftl`；启动独立 `Zotero test` 实例并将 XPI 路径交给 Zotero。Zotero 未自动完成命令行安装，当前仍等待用户在“工具 → 插件”界面确认，未直接复制文件到 profile 绕过官方安装流程。
- 修改原因：真实 Zotero 9 加载验收必须先在隔离测试配置中进行；通过官方插件界面安装可以保留兼容性检查和用户确认，避免误装到主配置。
- 生成的输出文件：`dist/zotero-test/zotero-paper-download-bridge-0.1.0.xpi`，大小 22,788 字节，SHA-256 为 `756DC268536478A168D7C263F8EB0AEAC8A28BC7E8CA6B252B6BC7EB4EBE0F40`。
- 如何检查是否成功：运行 `tar -tf .\dist\zotero-test\zotero-paper-download-bridge-0.1.0.xpi` 应只列出上述 5 个运行文件；当前 `Zotero test` 的扩展目录仍只有 `autoclass@example.com.xpi`，因此安装尚未完成，不能报告为已加载。
- 注意事项或潜在风险：XPI 中的插件拥有 Zotero 插件权限，只能先安装到独立测试配置。主 Zotero 实例未关闭，主配置未修改；真实文库写入、可用 PDF、机构授权、重启恢复和撤销仍未开始验收。下一步需要用户在测试 Zotero 的插件界面确认安装，然后再检查扩展清单和运行日志。
## 2026-07-12 00:21:35 +08:00 — 修复 Zotero 9 测试 XPI兼容性清单

- 修改日期和时间：2026-07-12 00:21:35 +08:00。
- 本次任务目标：诊断 `0.1.0` 测试 XPI被 Zotero 9.0.6 报告为“不兼容”的原因，补齐清单元数据并生成不覆盖旧证据的 `0.1.1` 修复包。
- 新增、修改或删除的文件：修改 `zotero_bridge_plugin/manifest.json`、`package.json`、`README.md`、`tests/plugin-structure.test.cjs` 和本 `CHANGELOG.md`；生成被 Git 忽略的 `dist/zotero-test/zotero-paper-download-bridge-0.1.1.xpi`；未删除旧 `0.1.0`，因为它仍被 Zotero 安装错误窗口占用。
- 具体修改内容：确认实际 Zotero 为 9.0.6，版本范围 `9.0`–`9.0.*` 与 XPI 根目录结构均正确；对比测试配置 AutoClass 和主配置已加载插件后，发现所有可安装清单均含 `applications.zotero.update_url`，而 `0.1.0` 缺少该字段。先新增结构测试并确认旧清单失败，再添加安全占位地址 `https://example.invalid/zotero-paper-download-bridge/updates.json`，同步把 manifest/package 版本升至 `0.1.1`，并将 README 输出名改为按清单版本生成。
- 修改原因：Zotero 插件安装器对清单错误使用通用“不兼容”提示；补齐与官方示例及本机已加载插件一致的更新地址字段，避免清单在安装兼容性阶段被拒绝。占位域名 `.invalid` 不指向真实服务，不携带凭据或用户信息。
- 生成的输出文件：`dist/zotero-test/zotero-paper-download-bridge-0.1.1.xpi`，大小 22,831 字节，SHA-256 为 `7E7F71A8D6C624DEA49F5D5A5618F3DBA7E5F79C6EAAA999283222175BF760B6`；旧 `0.1.0` 保留为被拒绝证据。
- 如何运行：在独立 `Zotero test` 配置中打开“工具 → 插件 → 从文件安装插件”，只选择 `0.1.1` XPI。离线验证命令为 `node --test .\zotero_bridge_plugin\tests\*.test.cjs`。
- 如何检查是否成功：61 项插件测试应全部通过且 `fail` 为 0；`tar -xOf <0.1.1.xpi> manifest.json` 应显示版本 `0.1.1` 和上述 `update_url`；Zotero test 安装后应在插件列表出现 `Paper Download Bridge 0.1.1`，且测试配置 `extensions.json` 出现插件 ID `paper-download-bridge@wkguoo.local`。
- 注意事项或潜在风险：当前仅完成修复包生成，仍等待用户在 Zotero test 界面确认安装，尚不能声称真实加载成功。打包测试 13 项中 10 项构建契约通过，3 项因本次用户明确要求后仓库 `dist` 内存在测试 XPI而按其“仓库不得存在 XPI”断言失败，并非构建逻辑回归。主配置、主文库、Cookie、原始 PDF均未修改；真实队列、可用 PDF、重启恢复和撤销仍待后续隔离验收。
## 2026-07-12 00:24:23 +08:00 — Zotero test 安装状态验证通过

- 修改日期和时间：2026-07-12 00:24:23 +08:00。
- 本次任务目标：验证用户通过 Zotero 官方插件界面安装的 `Paper Download Bridge 0.1.1` 是否仅进入独立 `Zotero test` 配置并处于可加载状态。
- 新增、修改或删除的文件：仅追加本 `CHANGELOG.md`；Zotero 在测试配置扩展目录中新增 `paper-download-bridge@wkguoo.local.xpi`，未修改项目源码、主 Zotero 配置、原始数据或 PDF。
- 具体修改内容：读取测试配置 `extensions.json`，确认插件 ID 为 `paper-download-bridge@wkguoo.local`、版本 `0.1.1`、`active=true`、`userDisabled=false`、`appDisabled=false`、`softDisabled=false`、`seen=true`；校验安装副本大小与 SHA-256 均和项目生成包完全一致；检查 `%LOCALAPPDATA%\PaperScraperDOI\zotero-bridge\v1` 尚未创建，说明空闲启动没有生成任务或结果。
- 修改原因：仅看到安装成功提示不足以证明安装到了正确 profile、未被兼容性禁用或安装文件未被替换，因此需要用扩展清单和哈希做可复核验证。
- 生成的输出文件：测试配置新增 `extensions\paper-download-bridge@wkguoo.local.xpi`，大小 22,831 字节，SHA-256 为 `7E7F71A8D6C624DEA49F5D5A5618F3DBA7E5F79C6EAAA999283222175BF760B6`；项目侧没有新增桥接作业、结果 CSV 或 PDF。
- 如何运行：在 `Zotero test` 窗口打开“工具 → 文献下载桥接”，只点击“查看最近状态”完成无副作用 UI验收；当前不要点击“撤销最近批次新增”，也不要向主配置重复安装。
- 如何检查是否成功：测试配置插件列表应显示 `Paper Download Bridge 0.1.1` 且已启用；工具菜单应出现“文献下载桥接”及“立即检查任务”“查看最近状态”“撤销最近批次新增”三个子项；点击“查看最近状态”应显示当前没有活动批次或等价空闲状态。
- 注意事项或潜在风险：扩展清单证明安装与启用成功，但还不能证明 `bootstrap.js` 菜单注册和真实 Zotero API动作全部成功；仍需一次菜单可视确认，之后才进入测试文库的队列、已有 PDF、缺失 PDF、取消、重启恢复和撤销验收。主配置和主文库未修改。
## 2026-07-12 00:28:15 +08:00 — 修复 Zotero 热安装后工具菜单缺失

- 修改日期和时间：2026-07-12 00:28:15 +08:00。
- 本次任务目标：修复 `Paper Download Bridge 0.1.1` 已在 Zotero test 中启用但“工具”菜单不存在的问题，并生成可升级安装的 `0.1.2` 测试包。
- 新增、修改或删除的文件：修改 `zotero_bridge_plugin/bootstrap.js`、`manifest.json`、`package.json`、`README.md`、`tests/plugin-structure.test.cjs` 和本 `CHANGELOG.md`；生成被 Git 忽略的 `dist/zotero-test/zotero-paper-download-bridge-0.1.2.xpi`；未修改主 Zotero 配置、原始数据或 PDF。
- 具体修改内容：确认 `startup()` 只加载核心/运行时但未处理安装时已经打开的主窗口，导致 `onMainWindowLoad()` 不会为该窗口补注册菜单。先新增回归断言并确认旧实现失败，再在 `startup()` 中等待 `Zotero.initializationPromise`，启动运行时后遍历 `Zotero.getMainWindows()` 调用 `addMenu(window)`；保留 `onMainWindowLoad()` 处理以后新开的窗口；版本同步升至 `0.1.2`。
- 修改原因：Zotero 将插件标记为 active 只证明扩展已启用，不代表插件 UI 已附加到现有窗口；热安装必须主动处理当前窗口，不能只依赖未来窗口回调。
- 生成的输出文件：`dist/zotero-test/zotero-paper-download-bridge-0.1.2.xpi`，大小 22,872 字节，SHA-256 为 `01E24BBDE2116D27DA0FC090BBD28883D720EE4BE17BB35E903AC30B3052D1B7`。
- 如何运行：在 `Zotero test` 的“工具 → 插件 → 从文件安装插件”中选择 `0.1.2` XPI并确认升级；安装后重新打开“工具”菜单查看“文献下载桥接”。离线验证命令为 `node --test .\zotero_bridge_plugin\tests\*.test.cjs` 和 `node --check .\zotero_bridge_plugin\bootstrap.js`。
- 如何检查是否成功：61 项插件测试和语法检查均通过；升级后测试配置应显示版本 `0.1.2`、active 且未禁用；当前已打开的窗口应立即出现“文献下载桥接”菜单，不要求先关闭 Zotero。
- 注意事项或潜在风险：当前只完成修复包生成，仍等待用户通过官方插件界面升级，尚未验证真实窗口菜单。不要将 `0.1.2` 安装到主配置；显示菜单后先只运行“查看最近状态”，再进行任何会写入测试文库的队列验收。
## 2026-07-12 00:36:33 +08:00 — 加固 Zotero 运行时全局对象与启动失败可见性

- 修改日期和时间：2026-07-12 00:36:33 +08:00。
- 本次任务目标：继续诊断 `0.1.2` 重启后仍无“文献下载桥接”菜单的问题，消除 Zotero 9 全局对象能力误判，并确保运行时失败时菜单和安全错误码仍可见。
- 新增、修改或删除的文件：修改 `zotero_bridge_plugin/bootstrap.js`、`content/bridge-runtime.js`、`manifest.json`、`package.json`、`README.md`、`tests/plugin-structure.test.cjs` 和本 `CHANGELOG.md`；生成被 Git 忽略的 `dist/zotero-test/zotero-paper-download-bridge-0.1.3.xpi`；新增运行调试输出目录 `output/zotero-test-debug/`。
- 具体修改内容：确认 `0.1.2` 已安装 active，但运行时在创建桥接目录前静默中止；对比已加载 AutoClass 后发现 Zotero 9 提供 `IOUtils/PathUtils` 全局标识符，但运行时旧代码强制检查 `globalThis.IOUtils/PathUtils/Services`。`bootstrap.js` 现显式映射三个对象到 `globalThis`，先为现有窗口注册菜单，再加载核心/运行时；启动异常使用 `Zotero.logError()` 记录并保留菜单，菜单命令在运行时不可用时只显示安全码 `bridge_runtime_startup_failed`；生产结果版本同步升至 `0.1.3`。
- 修改原因：扩展 active 不代表运行时初始化成功；错误的全局属性检查可能在 Zotero 真实作用域中产生假阴性，而菜单后注册又会让错误完全不可见。双重保护可同时修复预期根因并为剩余真实 API差异提供可观察反馈。
- 生成的输出文件：`dist/zotero-test/zotero-paper-download-bridge-0.1.3.xpi`，大小 23,137 字节，SHA-256 为 `4CE16B46E626D9125D36AE87DB64D58438C426F7EE1931305160A1CA5C11387A`；`output/zotero-test-debug/stdout.log` 和 `stderr.log` 仅记录 Zotero test 启动日志，目前只有无关显卡/本地化警告。
- 如何运行：在当前 `Zotero test` 的“工具 → 插件 → 从文件安装插件”中选择 `0.1.3` XPI并确认升级；升级后查看“工具 → 文献下载桥接”。离线验证命令为插件 61 项 Node测试、JavaScript 语法检查，以及 `tests.test_zotero_bridge`/`tests.test_zotero_bridge_integration` 58 项 Python测试。
- 如何检查是否成功：61 项插件测试、58 项项目桥接测试和语法检查均通过；升级后菜单必须出现。若运行时正常，“查看最近状态”应报告没有待处理任务；若仍有真实 API问题，菜单仍应出现并显示 `bridge_runtime_startup_failed`，同时 Zotero 错误日志留下异常。
- 注意事项或潜在风险：当前仍等待用户升级安装 `0.1.3`，不能提前声称真实运行时已成功。只在独立 `Zotero test` 验收，不向主配置安装；不要点击撤销或提交真实文献批次，直到“查看最近状态”通过。

## 2026-07-12 00:45:45 +08:00 — 改用 Zotero 9 同步启动与窗口注入

- 修改日期和时间：2026-07-12 00:45:45 +08:00。
- 本次任务目标：修复 `Paper Download Bridge 0.1.3` 在 `Zotero test` 中显示已启用但“工具”菜单仍不出现的问题，并生成可升级安装的 `0.1.4` 测试包；本轮仍只做插件，不连接主项目、不提交文献任务。
- 新增、修改或删除的文件：修改 `zotero_bridge_plugin/bootstrap.js`、`content/bridge-runtime.js`、`manifest.json`、`package.json`、`README.md`、`tests/plugin-structure.test.cjs` 和本 `CHANGELOG.md`；新增 `zotero_bridge_plugin/tests/bootstrap-lifecycle.test.cjs`；生成被 Git 忽略的 `dist/zotero-test/zotero-paper-download-bridge-0.1.4.xpi`。未修改正式 Zotero 配置、主文库、原始数据、Cookie 或 PDF。
- 具体修改内容：确认测试配置中的 `0.1.3` 为 `active=true`，但调试日志没有插件错误且桥接根目录未创建；对比本机可工作的 Zotero 插件生命周期后，定位旧入口使用 `async startup()` 并等待 `Zotero.initializationPromise`，Zotero 9 的 bootstrap 加载器不会按该方式等待，代码可能停在首次菜单注册之前。现将入口改为同步 `startup(data, reason)`，立即通过 `Services.wm.getEnumerator(null)` 查找 `chrome://zotero/content/zoteroPane.xhtml` 主窗口并插入菜单，再以 Promise 后台启动运行时；`onMainWindowLoad/Unload` 改为 Zotero 9 的 `data.window` 调用形式；为菜单增加固定 ID、重复注册保护，以及 `bridge_runtime_starting`/`bridge_runtime_startup_failed` 两种可观察状态；生产版本同步升至 `0.1.4`。
- 修改原因：插件清单 active 只表示扩展被允许加载，不能证明 Zotero 已等待异步 bootstrap 钩子。菜单属于同步 UI 注册，必须在 `startup()` 返回前完成；运行时文件 I/O可继续异步执行，不能阻塞菜单可见性。
- 生成的输出文件：`dist/zotero-test/zotero-paper-download-bridge-0.1.4.xpi`，大小 23,548 字节，SHA-256 为 `39E588F50CD2693E26C8D3155997E65F8FFB9E2A806CCF71A7D5E1D430F3DED4`；包内仅含 `manifest.json`、`bootstrap.js`、两个 `content/*.js` 和 `locale/zh-CN/bridge.ftl`。
- 如何运行：在独立 `Zotero test` 中打开“工具 → 插件 → 齿轮 → 从文件安装插件”，选择上述 `0.1.4` XPI并确认升级。离线验证可运行 `node --test .\zotero_bridge_plugin\tests\*.test.cjs`，以及 `.\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge tests.test_zotero_bridge_integration -v`；本机 PowerShell 禁止执行 `npm.ps1`，因此使用等价的 `node --test` 命令。
- 如何检查是否成功：插件端 62 项 Node测试、主项目桥接端 58 项 Python测试和三个 JavaScript 文件语法检查均通过；新增回归测试证明即使运行时 Promise一直未完成，菜单也会同步出现。真实验收时插件列表应显示 `0.1.4`，随后“工具”菜单应立即出现“文献下载桥接”；菜单出现而运行时尚未完成时会显示 `bridge_runtime_starting`，真实启动错误则显示 `bridge_runtime_startup_failed`。
- 注意事项或潜在风险：当前只完成修复、测试与打包，尚未由用户在真实 `Zotero test` 窗口安装 `0.1.4`，因此不能提前宣称可视菜单验收通过。只升级测试配置，不安装到正式配置；菜单出现后先只点“查看最近状态”，不要点“撤销最近批次新增”，也不要创建真实桥接任务。

## 2026-07-12 01:00:47 +08:00 — 按 Zotero 9 官方插件接口修复入口与工具菜单

- 修改日期和时间：2026-07-12 01:00:47 +08:00。
- 本次任务目标：继续修复 `Paper Download Bridge 0.1.4` 在独立 `Zotero test` 中已安装、`active=true` 但仍无工具菜单的问题；查阅 Zotero 官方插件开发说明和官方示例，以实际 Zotero 9 加载器源码为准重写入口和菜单注册，生成 `0.1.5` 测试包。本轮仍不连接主项目、不提交文献任务。
- 新增、修改或删除的文件：修改 `zotero_bridge_plugin/bootstrap.js`、`content/bridge-runtime.js`、`locale/zh-CN/bridge.ftl`、`manifest.json`、`package.json`、`README.md`、`tests/bootstrap-lifecycle.test.cjs`、`tests/plugin-structure.test.cjs` 和本 `CHANGELOG.md`；生成被 Git 忽略的 `dist/zotero-test/zotero-paper-download-bridge-0.1.5.xpi`。未修改正式 Zotero 配置、主文库、原始数据、Cookie 或 PDF。
- 具体修改内容：核验测试配置中的 `0.1.4` 确为 active 且未禁用；查阅 Zotero 官方《Zotero 7 for Developers》《Zotero 8 for Developers》和官方 `zotero/make-it-red` 示例；进一步只读检查本机 Zotero 9.0.6 的 `app/omni.ja` 官方插件加载器，确认插件沙箱已经直接注入 `Services`、`IOUtils`、`PathUtils`，而平台 `omni.ja` 中不存在旧路径 `resource://gre/modules/Services.sys.mjs`。旧 `bootstrap.js` 在第一条手动导入语句即抛错，生命周期函数因而从未注册，这与 active、无菜单、无插件调试输出完全吻合。修复版移除全部手动 `Services` 导入和旧 DOM 菜单注入，改用官方 `Zotero.MenuManager.registerMenu()`、目标 `main/menubar/tools`；生命周期签名改为官方示例形式；当前和未来主窗口通过 `MozXULElement.insertFTLIfNeeded("bridge.ftl")` 加载本地化；菜单 Fluent 条目改用官方要求的 `.label` 属性；保留启动中与启动失败安全码，并增加 `Zotero.debug` 启动/就绪日志。版本同步升至 `0.1.5`。
- 修改原因：Zotero 8/9 基于更新的 Firefox 平台，官方明确要求移除手动 Services 导入；继续导入已不存在的模块会让整个 bootstrap 在函数声明前终止。Zotero 8 起已经提供受支持的菜单 API，应使用 MenuManager而不是依赖旧 XUL DOM节点 ID。
- 生成的输出文件：`dist/zotero-test/zotero-paper-download-bridge-0.1.5.xpi`，大小 23,320 字节，SHA-256 为 `E866198EAE3BB7688985606F2AFB66FBD1B7E8F5EAB62E7E4D850753F0FAD469`；包内仍仅含 `manifest.json`、`bootstrap.js`、两个 `content/*.js` 和 `locale/zh-CN/bridge.ftl`。包内入口复核确认包含 `Zotero.MenuManager.registerMenu` 和 `main/menubar/tools`，不再包含 `Services.sys.mjs` 或 `ChromeUtils.importESModule`。
- 如何运行：只在独立 `Zotero test` 中打开“工具 → 插件 → 齿轮 → 从文件安装插件”，选择上述 `0.1.5` XPI并确认升级。离线验证命令为 `node --test .\zotero_bridge_plugin\tests\*.test.cjs`，以及 `.\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge tests.test_zotero_bridge_integration -v`。官方参考为 `https://www.zotero.org/support/dev/zotero_8_for_developers`、`https://www.zotero.org/support/dev/zotero_7_for_developers` 和 `https://github.com/zotero/make-it-red/tree/main/src-2.0`。
- 如何检查是否成功：插件端 63 项 Node测试、主项目桥接端 58 项 Python测试、三个 JavaScript 语法检查和 `git diff --check` 均通过；真实升级后插件列表应显示 `0.1.5`，工具菜单应出现“文献下载桥接”。运行调试模式时还应出现 `Paper Download Bridge: Starting 0.1.5`，运行时完成后出现 `Paper Download Bridge: Ready 0.1.5`；随后只点击“查看最近状态”检查空闲状态。
- 注意事项或潜在风险：当前只完成官方规范核对、代码修复、离线测试与打包，尚未在真实 Zotero test 窗口安装 `0.1.5`，因此不能提前宣称 UI验收通过。只升级测试配置，不安装到正式配置；菜单出现后先不要点击“立即检查任务”或“撤销最近批次新增”，也不要创建真实桥接队列。

## 2026-07-12 11:19:00 +08:00 — 修复 MenuManager 空白标签并暴露运行时错误码

- 修改日期和时间：2026-07-12 11:19:00 +08:00。
- 本次任务目标：处理用户反馈的 `0.1.5` 已出现工具菜单但菜单文字为空的问题，并继续定位运行时未创建桥接目录的真实错误；本轮仍只在独立 `Zotero test` 中验证，不连接主项目、不写入文献库。
- 新增、修改或删除的文件：修改 `zotero_bridge_plugin/bootstrap.js`、`content/bridge-runtime.js`、`manifest.json`、`package.json`、`README.md`、`tests/bootstrap-lifecycle.test.cjs` 和本 `CHANGELOG.md`；生成被 Git 忽略的 `dist/zotero-test/zotero-paper-download-bridge-0.1.6.xpi`。未修改正式 Zotero 配置、主文库、原始数据、Cookie 或 PDF。
- 具体修改内容：根据用户截图确认空白带箭头行就是 MenuManager 注册成功但本地化标签未显示；读取本机 Zotero 9 官方 `menuManager.js`，确认 `onShowing` 上下文提供 `menuElem`、`setEnabled`、`setVisible` 等官方操作。保留标准 `l10nID` 和 Fluent 文件，同时为顶层子菜单及三个菜单项增加 `onShowing` 标签回退，直接设置官方 `context.menuElem` 的 `label`，避免现有窗口本地化源未及时刷新时出现空白。记录运行时启动错误码到 `bridgeRuntimeError`，错误菜单提示现在会显示 `bridge_runtime_startup_failed:<具体错误码>`；版本同步升至 `0.1.6`。
- 修改原因：`0.1.5` 的空白截图表明 MenuManager 已执行，问题已经从“插件未加载”缩小为“动态本地化未落到现有窗口”。同时此前检查发现桥接根目录仍未创建，必须把真实运行时异常从泛化提示中暴露出来，才能继续修复而不猜测。
- 生成的输出文件：`dist/zotero-test/zotero-paper-download-bridge-0.1.6.xpi`，大小 23,669 字节，SHA-256 为 `DB9BDFBF2F5D6E4E4902C2C39FF0BCF13322CDFB6A8BCD2D4776C40036FCD8D5`；包清单版本为 `0.1.6`，仍只包含白名单入口、核心、运行时和中文 Fluent 文件。
- 如何运行：在独立 `Zotero test` 中打开“工具 → 插件 → 齿轮 → 从文件安装插件”，选择上述 `0.1.6` XPI并确认升级。安装后重新打开“工具”菜单，空白项应显示“文献下载桥接”；展开后应显示“立即检查任务”“查看最近状态”“撤销最近批次新增”。如果运行时仍失败，点击“查看最近状态”会显示具体错误码。
- 如何检查是否成功：63 项插件 Node测试、58 项主项目桥接 Python测试、三个 JavaScript 语法检查均通过；定向回归测试验证 MenuManager 的 `onShowing` 会写入顶层和子菜单标签。升级后还应检查 `%LOCALAPPDATA%\PaperScraperDOI\zotero-bridge\v1` 是否创建；若未创建，请把菜单弹出的完整错误码反馈回来。
- 注意事项或潜在风险：当前只完成代码修复、测试与打包，尚未由用户安装 `0.1.6`；不能提前声称运行时已成功。只升级 `Zotero test`，不要安装到正式配置，也不要点击“立即检查任务”或“撤销最近批次新增”。

## 2026-07-12 11:28:31 +08:00 — 修复 XPI 内部脚本加载方式

- 修改日期和时间：2026-07-12 11:28:31 +08:00。
- 本次任务目标：根据用户提供的 `0.1.6` 错误截图继续修复插件运行时启动失败；错误码为 `Error_opening_input_stream_invalid_filename_jar_file_...Profiles_elpj7iql...`，目标是让 Zotero 9 正确加载 XPI 内的 `content` 脚本。
- 新增、修改或删除的文件：修改 `zotero_bridge_plugin/bootstrap.js`、`manifest.json`、`package.json`、`content/bridge-runtime.js`、`README.md`、`tests/bootstrap-lifecycle.test.cjs`、`tests/plugin-structure.test.cjs` 和本 `CHANGELOG.md`；生成被 Git 忽略的 `dist/zotero-test/zotero-paper-download-bridge-0.1.7.xpi`。未修改正式 Zotero 配置、主文库、原始数据、Cookie 或 PDF。
- 具体修改内容：将 `Services.scriptloader.loadSubScript()` 改为 Zotero 9 官方插件加载器实际使用的 `loadSubScriptWithOptions(uri, { target: globalThis, charset: "UTF-8", ignoreCache: true })`；新增回归断言检查 XPI 脚本加载选项和插件沙箱目标；保留可见启动错误码和 `bridge_runtime_startup_failed:<具体错误码>` 提示；版本同步升至 `0.1.7`。
- 修改原因：用户截图明确显示 `loadSubScript()` 解析 `jar:file:///...xpi!/` 资源时抛出 `invalid_filename_jar_file`。本机 Zotero 9 的官方 `plugins.js` 也使用 `loadSubScriptWithOptions()` 加载插件 bootstrap 及资源，改为同一调用方式可避免简化接口对 XPI JAR URL 的解析差异。
- 生成的输出文件：`dist/zotero-test/zotero-paper-download-bridge-0.1.7.xpi`，大小 23,723 字节，SHA-256 为 `594E5C903748E1CDDE220511A8EE7C94F0DA6492F6AAE2E3778215A437A42472`；包内入口已确认包含 `loadSubScriptWithOptions` 和 `target: globalThis`，不包含失效的 `Services.sys.mjs` 导入。
- 如何运行：在独立 `Zotero test` 中打开“工具 → 插件 → 齿轮 → 从文件安装插件”，选择上述 `0.1.7` XPI并确认升级。升级后打开“工具 → 文献下载桥接”，先点击“查看最近状态”；如果启动仍失败，把提示中的完整错误码反馈回来。
- 如何检查是否成功：63 项插件 Node测试、58 项主项目桥接 Python测试、三个 JavaScript 语法检查均通过；成功时 `%LOCALAPPDATA%\PaperScraperDOI\zotero-bridge\v1` 应被创建，且不再出现 `invalid_filename_jar_file`。
- 注意事项或潜在风险：当前只完成代码修复、测试与打包，尚未由用户安装 `0.1.7`；不能提前声称真实运行时已成功。只升级 `Zotero test`，不要安装到正式配置，也不要创建或撤销真实桥接任务。

## 2026-07-12 11:59:23 +08:00 — 改用标准 ZIP 生成 XPI

- 修改日期和时间：2026-07-12 11:59:23 +08:00。
- 本次任务目标：继续修复 `invalid_filename_jar_file` 启动失败；排查发现代码入口已进入但读取 XPI 内部资源失败，进一步验证 XPI 归档格式兼容性，并生成标准 ZIP 格式的测试包。
- 新增、修改或删除的文件：修改 `build_zotero_bridge_xpi.ps1`、`tests/test_zotero_bridge_packaging.py`、`manifest.json`、`package.json`、`content/bridge-runtime.js`、`README.md` 和本 `CHANGELOG.md`；生成被 Git 忽略的 `dist/zotero-test/zotero-paper-download-bridge-0.1.8.xpi`。未修改正式 Zotero 配置、主文库、原始数据、Cookie 或 PDF。
- 具体修改内容：将构建器的 PowerShell 压缩步骤改为 Windows 自带 `tar -a -c -f` 标准 ZIP 写入，保留源目录白名单、禁止重解析点、禁止覆盖、临时文件和归档内容校验；静态打包测试同步检查新命令并禁止回退到旧压缩器；版本同步升至 `0.1.8`。对照包包含显式 `content/`、`locale/` 目录条目，符合标准 XPI/ZIP 结构。
- 修改原因：Zotero 官方论坛对同类 `Error opening input stream (invalid filename?): jar:file:///...xpi` 的解释是 XPI 文件损坏或不兼容；官方开发指南的打包示例使用标准 `zip -r`。当前旧构建器使用 PowerShell 压缩器，虽然普通 ZIP 工具可以读取，Gecko JAR 资源读取可能更严格，因此改用标准 ZIP 写入器。
- 生成的输出文件：`dist/zotero-test/zotero-paper-download-bridge-0.1.8.xpi`，大小 24,537 字节，SHA-256 为 `7490459C69885F10E446AC06A6F53267BF021C5E5A7762E24BAD6A48BB6015D6`；归档包含根目录 `manifest.json`、`bootstrap.js`，以及带目录条目的 `content/` 和 `locale/`。
- 如何运行：在独立 `Zotero test` 中打开“工具 → 插件 → 齿轮 → 从文件安装插件”，选择上述 `0.1.8` XPI并确认升级；如 Zotero 提示重启，重启测试配置后再查看菜单。随后点击“查看最近状态”，成功时应不再出现 `invalid_filename_jar_file`，并创建 `%LOCALAPPDATA%\PaperScraperDOI\zotero-bridge\v1`。
- 如何检查是否成功：63 项插件 Node测试、58 项主项目桥接 Python测试、3 项打包器静态测试、三个 JavaScript 语法检查和 `git diff --check` 均通过；XPI 可由 tar 列出并显示标准目录条目。真实验收仍需用户安装 `0.1.8`，这是当前唯一未完成的外部验证项。
- 注意事项或潜在风险：当前不能仅凭离线 ZIP 检查声称 Gecko 已接受该包；只升级 `Zotero test`，不要安装到正式配置，也不要创建或撤销真实桥接任务。若 `0.1.8` 仍失败，请提供完整错误码，以区分归档兼容性问题和 Zotero API 问题。

## 2026-07-12 12:36:38 +08:00 — 使用 RECOMMENDED_MISSING_PAPERS.md 完成全量下载测试

- 修改日期和时间：2026-07-12 12:36:38 +08:00。
- 本次任务目标：以 `D:\桌面\文献下载\RECOMMENDED_MISSING_PAPERS.md` 为输入，对清单中可唯一识别的 8 篇文献进行合法下载测试；不修改原始 Markdown，不覆盖原始文献库 PDF。
- 新增、修改或删除的文件：新增 `results/recommended_missing_download_test/all_identified_papers.txt`、`results/recommended_missing_download_test/sciencedirect_papers.txt`；生成 `results/recommended_missing_download_test/legal_oa/`、`results/recommended_missing_download_test/sciencedirect/all_identified/` 下的下载结果和报告；追加本条 `CHANGELOG.md`。未修改 `D:\桌面\文献下载\RECOMMENDED_MISSING_PAPERS.md`。
- 具体修改内容：先对原始 Markdown 做预览，发现整份说明文档会产生大量非文献 `needs_review` 行；随后按清单中的正式条目补全 Shen 2023、Jaladurgam 2021/2022 DOI，建立干净 DOI 清单。3 篇公开合法 OA 文献通过 `paper_skill.py` 下载；4 篇 Elsevier 文献通过 `sd_institutional_skill.py` 和机构访问下载；Science 2020 论文的正式 PDF 入口返回 HTTP 403，按规则保留失败记录。
- 修改原因：避免把 Markdown 标题、操作说明和主题标签误当成论文，同时确保用户要求的“提到的文献都尝试下载”覆盖所有可唯一识别条目。
- 生成的输出文件：共 7 个可读 PDF；合法 OA 报告为 `legal_oa/metadata/manifest.csv`、`manifest.json`，ScienceDirect 报告为 `sciencedirect/all_identified/pdf_download_report.csv`、`run_summary.txt`、`run_summary.json`；预览和失败报告也保存在对应输出目录。机构访问产生的 `_auth/sciencedirect_cookies.json` 属本地凭证缓存，不得提交或分享。
- 如何运行：在项目根目录执行 `\.venv\Scripts\python.exe paper_skill.py --input results\recommended_missing_download_test\all_identified_papers.txt --out results\recommended_missing_download_test\legal_oa`；执行 `\.venv\Scripts\python.exe sd_institutional_skill.py --input results\recommended_missing_download_test\sciencedirect_papers.txt --out results\recommended_missing_download_test\sciencedirect --run-name all_identified --no-download-supplements`。
- 如何检查是否成功：ScienceDirect 报告显示 4/4 成功、0 失败；合法 OA 清单显示 3 篇下载、4 篇无合法 OA PDF，其中 Science 论文另记录为 HTTP 403；7 个 PDF 均以 `%PDF-` 开头并包含 `%%EOF` 文件结束标记，文件大小均大于 1 MB。
- 注意事项或潜在风险：本次结果保存于项目 `results/`，没有自动复制回 `F:\1_Nb_HEA\05_references\01_pdfs\`；Science 论文仍需通过用户有权使用的机构入口或出版社可用会话补下载。不要把 `_auth` 目录、Cookie、PDF 或个人机构会话提交到 GitHub。

## 2026-07-12 12:57:45 +08:00 — 收敛为唯一统一下载入口

- 修改日期和时间：2026-07-12 12:57:45 +08:00。
- 本次任务目标：只保留 `paper-download` / `paper_batch.py` 作为用户可见的统一文献下载入口，使公开 OA、机构访问、一次人工重试和 Zotero 回退进入同一批次状态流程。
- 新增、修改或删除的文件：修改 `README.md`、`README_zh.md`、`skills/paper-download/SKILL.md`、`skills/sciencedirect-doi-download/SKILL.md`、`skills/legal-oa-paper-download/SKILL.md`、`docs/sciencedirect_skill_beginner_guide.md`、`install_codex_skills.ps1`、`tests/test_skills_packaging.py` 和本 `CHANGELOG.md`；未删除 `paper_skill.py` 或 `sd_institutional_skill.py`，因为它们仍作为统一流程的内部适配器使用。
- 具体修改内容：README 和统一 Skill 不再把 OA/ScienceDirect 独立命令列为用户流程；安装脚本只安装 `paper-download`；两个旧 Skill 标记为内部兼容参考；旧 GUI/CLI 保留但明确不属于推荐入口；同步调整 Skill 打包测试以验证新的单一入口约束。
- 修改原因：此前直接运行 `paper_skill.py` 或 `sd_institutional_skill.py` 会绕过统一批次状态和 `zotero_fallback.csv`，导致失败文献不会自动进入 Zotero 回退。统一入口可保留同一批次的失败、重试、桥接和最终报告。
- 生成的输出文件：本次没有生成 PDF 或下载结果；仅更新项目文档、安装脚本、Skill 说明和测试约束。旧的 `C:\Users\wkguopro\.codex\skills\sciencedirect-doi-download` 与 `legal-oa-paper-download` 用户目录副本未删除，等待明确确认后再处理。
- 如何运行：执行 `\.venv\Scripts\python.exe paper_batch.py start --input "文献清单" --out "results"`；安装 Skill 前可运行 `powershell -ExecutionPolicy Bypass -File .\install_codex_skills.ps1 -DryRun`，预期只显示 `paper-download`。
- 如何检查是否成功：`paper_batch.py --help` 显示 `start`、`resume`、`zotero`、`finalize`；`tests.test_skills_packaging` 共 23 项通过；安装脚本 dry-run 只显示 `paper-download` 且不修改文件或环境变量；`git diff --check` 和 Python 语法检查通过。
- 注意事项或潜在风险：不要直接运行底层脚本，否则失败项不会进入统一 Zotero 回退队列。删除用户目录中已有旧 Skill 属外部文件删除操作，当前未执行；项目仓库中的底层脚本也未删除，以保持统一流程可运行。

## 2026-07-12 13:15:20 +08:00 — 外部浏览器改为 Edge 优先

- 修改日期和时间：2026-07-12 13:15:20 +08:00。
- 本次任务目标：保留 Codex 内置浏览器作为登录/验证首选；仅当内置浏览器不可用或本地项目无法使用其会话时启动外部浏览器，并将 Windows 外部浏览器默认顺序改为用户显式指定 → Edge Stable → Edge Beta/Dev/Canary → Chrome/Chromium → Playwright Chromium。
- 新增、修改或删除的文件：修改 `windows_paths.py`、`paper_batch.py`、`sd_institutional_skill.py`、`sd_scraper.py`、`tests/test_windows_paths.py`、`README.md`、`README_zh.md`、`skills/paper-download/SKILL.md`、`skills/sciencedirect-doi-download/SKILL.md`、`docs/sciencedirect_skill_beginner_guide.md` 和本 `CHANGELOG.md`；未删除文件，未打包项目。
- 具体修改内容：加入 Edge Stable、Beta、Dev、SxS 标准安装路径，并确保所有 Edge 通道整体排在 Chrome 之前；保留 `PAPER_SCRAPER_BROWSER_EXE`、`--browser-exe`、`chrome_bin()` 兼容别名和 Edge/Chrome profile 自动匹配；统一入口、Skill、ScienceDirect 文档和帮助文本明确内置浏览器优先及 Edge 外部回退顺序；显式指定 Chrome 时仍使用 Chrome。现有状态日志继续记录实际浏览器名称、可执行文件、profile 和调试端口。
- 修改原因：使外部调试会话符合“Edge 优先”的项目要求，同时不接管或扩大 Codex/本机浏览器 Cookie 自动读取范围，也不输出 Cookie 值。
- 生成的输出文件：本次没有生成 PDF、Cookie、浏览器 profile 或打包文件；仅修改源码、测试和说明文档。工作区中 `dist/zotero-test` 的 9 个旧 `.xpi` 为此前 Zotero 任务留下的被 Git 忽略产物，未擅自删除。
- 如何运行：`\.venv\Scripts\python.exe paper_batch.py start --help`；需要显式浏览器时传入 `--browser-exe "C:\\Path\\to\\chrome.exe"`，或设置 `$env:PAPER_SCRAPER_BROWSER_EXE`。未指定时由 `windows_paths.py` 按上述顺序解析。
- 如何检查是否成功：`py_compile windows_paths.py paper_automation\\institutional\\browser_session.py sd_institutional_skill.py` 通过；定向测试 `tests.test_windows_paths tests.test_institutional_browser tests.test_batch_workflow` 共 156 项通过、2 项因 Windows 符号链接权限跳过；`git diff --check` 通过；统一入口和两个 ScienceDirect CLI 的帮助文本均显示 Edge→Chrome。完整测试集共 367 项，其中 362 项通过、2 项跳过、3 项因既有 `dist/zotero-test/*.xpi` 违反现有“仓库不应有 XPI”测试约束而失败，非本次 Edge 改动引起。
- 注意事项或潜在风险：显式浏览器参数始终覆盖自动选择；外部浏览器 profile 和机构会话属于本机凭据状态，不应提交或分享。若要使完整测试集恢复全绿，需要先由用户确认后清理/隔离上述旧 XPI 产物；本次未执行删除操作。

## 2026-07-16 — 减少手动操作的批次优化（Elsevier 不动）

### 变更摘要
- **A1/B1.1 输入**：默认只保留 DOI 任务；过滤 Markdown 章节/备注；可选题名+DOI 行合并题名。
- **A4 DOI 预检**：默认开启（`--no-doi-preflight` 关闭）；失败 fail-open；严重题名/DOI 不匹配标 `metadata_uncertain`。
- **A2/B3.1 失败路由**：仅有 DOI 且可桥接的失败进 Zotero；`metadata_uncertain` 不进桥接。
- **B2.1**：无适配器条目不启动机构浏览器。
- **B2.3**：同 adapter 连续失败熔断（默认 3 次）。
- **B2.4**：仅有 supported 时启动/复用调试浏览器。
- **A5**：`retry-failed` 默认仅网络/捕获类；`--retry-all-failed` 恢复宽集。
- **B3.3**：有界 OA 仅对 OA 信号行；`start` 可自动补救。
- **Zotero**：插件 0.2.0 默认自动确认；CLI 默认 `--auto-zotero` + `--wait-seconds 600`。

### 关键文件
- `paper_automation/failure_routing.py`（新）
- `paper_automation/batch_workflow.py` / `batch_stages.py` / `doi_preflight.py` / `oa_recovery.py`
- `paper_automation/institutional/workflow.py`
- `paper_batch.py`
- `zotero_bridge_plugin/*` 0.2.0
- `skills/paper-download/SKILL.md`, `README.md`, `README_zh.md`
- `tests/test_failure_routing_and_intake_filters.py`

## 2026-07-22 17:23:46 +08:00 — 第一阶段论文与文件数据完整性修复

- 修改日期和时间：2026-07-22 17:23:46 +08:00。
- 本次任务目标：以 `df912c0` 为基线，修复固定批次忽略新输入、不同论文串用 PDF、PDF 非原子写入、最终交付缺少复验，以及重新发布误删用户文件的问题；保持统一批次界面和“年份-作者-题名.pdf”交付命名不变。
- 新增、修改或删除的文件：新增 `paper_automation/artifact_store.py`、`tests/test_integrity_phase1.py`；修改 `paper_automation/batch_stages.py`、`paper_automation/batch_workflow.py`、`paper_automation/delivery_refresh.py`、`paper_automation/downloader.py`、`paper_automation/institutional/workflow.py`、`paper_automation/oa_recovery.py`、`paper_automation/workflow.py`、`paper_automation/zotero_bridge.py`、`paper_batch.py`、`sd_institutional_skill.py`、`sd_scraper.py`、`sd_supplements.py`、`tests/test_batch_workflow.py`、`tests/test_paper_automation.py` 和本 `CHANGELOG.md`；未删除文件。
- 具体修改内容：将 `batch_state.json` 升级为兼容 v1 的 v2，并记录输入类型、原始 SHA-256、规范化 SHA-256、任务集合 SHA-256 和条目数；固定批次输入任务变化时返回 `input_changed_for_existing_run`，相同任务可按原顺序续跑，v1 仅在确认匹配后原子升级。新增 DOI→PII→题名优先级的论文身份和 `paper-0001_<identity-hash>.pdf` 内部命名，统一批次的 OA、OA recovery、非 Elsevier 机构、ScienceDirect 与 Zotero 工件均启用身份隔离。新增共享 PDF 发布器，使用同目录临时文件、`flush/fsync`、PDF 头尾校验、SHA-256、排他发布和哈希冲突后缀，不覆盖任何同名不同内容文件。最终交付前重新检查普通文件、symlink/reparse、同一文件句柄快照、最小大小、`%PDF-`、`%%EOF` 和复制前后哈希；失败行降级为 `not_pdf_response` 并写回状态。新增 `working/delivery_owned.json`，按 generation、相对路径、SHA-256、task_id 和文件类型管理程序文件；重发时递归保留手工 PDF、非 PDF、补充材料、空目录和用户修改文件，冲突文件改用 `_manual_<hash>`，并将 `结果/`、`下载清单.csv` 与所有权清单作为同一可回滚事务发布。
- 修改原因：旧固定目录可能把新输入当作旧任务续跑；显示文件名和跨论文内容复用不足以证明论文身份；直接写入或覆盖可能留下半文件或破坏原文件；仅在下载时校验不能保证最终交付仍可信；清空重建 `结果/` 会误删用户手工整理内容。
- 生成的输出文件：项目内仅新增源码和测试文件，没有生成真实 PDF、Cookie、机构会话、结果批次或打包文件。全量测试在排除 `.git`、`.venv`、`dist`、`results` 的系统临时副本中运行；未修改、删除或重新生成现有 XPI。
- 如何运行：正常入口仍为 `.\.venv\Scripts\python.exe paper_batch.py start --input "papers.xlsx" --out "results" --email "you@example.com"`。若固定批次输入任务集合已经变化，使用 `--fresh` 新建批次，或指定新的 `--run-name`；不要手工合并不同任务集合的 `batch_state.json`。
- 如何检查是否成功：项目要求的 `compileall` 通过；完整性专项测试共 15 项，其中 13 项通过、2 项因当前 Windows 符号链接权限跳过；排除现有 `dist/*.xpi` 的临时副本中，全量离线测试共 431 项，其中 427 项通过、4 项按环境条件跳过；`git diff --check` 通过。现有 `dist/zotero-paper-download-bridge-0.2.0.xpi` 的 SHA-256 仍为 `D1C0C0E93228EF050FD674FCBE201731793EA19C4933C32747880043F474A460`。
- 注意事项或潜在风险：本轮未进行真实机构下载、未自动打包、未提交或推送，也未新增解析器级页数检查。Windows 当前权限不能创建测试 symlink，因此相关拒绝逻辑由静态路径检查和可用环境下的跳过测试覆盖；真实机构会话仍需后续手工 QA。元数据缓存、结构化网络错误、retry 租约、浏览器实例身份、`--auto-zotero`、`recover-oa` 退出码和解析器级 PDF 校验仍按计划留待后续阶段。

## 2026-07-22 19:34:05 +08:00 — 第二阶段恢复能力、元数据缓存与可信下载闭环

- 修改日期和时间：2026-07-22 19:34:05 +08:00。
- 本次任务目标：在第一阶段工作区上补齐批次尝试租约、结构化元数据缓存、全路径流式下载限额、DevTools 流式捕获、解析器级 PDF 复验，以及插件供应链 CI；保持统一批次界面、目录和“年份-作者-题名.pdf”交付命名不变。
- 新增、修改或删除的文件：新增 `paper_automation/metadata_cache.py`、`tests/offline_network_guard.py`、`tests/sitecustomize.py`、`tests/test_000_offline_network.py`、`tests/test_recovery_phase2.py`；扩展第一阶段新增的 `paper_automation/artifact_store.py`；修改 `.github/workflows/tests.yml`、`.gitignore`、`requirements.txt`、`paper_batch.py`、`sd_scraper.py`、`sd_scraper_en.py`、`sd_supplements.py`、`sd_institutional_skill.py`、`paper_automation/` 下的批次、元数据、OA、机构、Zotero、下载与 PDF 校验模块，以及相关测试、`README.md`、`README_zh.md` 和本文件。未删除用户文件。
- 具体修改内容：为 `batch_state.json` v2 增加可选 `active_attempts`，实现 5 分钟租约、30 秒续租、过期回收、`attempt_id` 结果栅栏、`attempting` 持久状态和原失败原因保留；新增带文件锁、逐行追加和 `fsync` 的 `working/metadata_cache.jsonl`，使用 `LookupOutcome` 区分 `ok/not_found/timeout/rate_limited/network_error/invalid_response`，成功与未找到缓存 30 天，临时错误缓存 5 分钟，并允许忽略最后一条崩溃残缺记录；DOI-only 输入不再进行联网预检，仅在存在独立题名时检查严重冲突。所有正文与补充材料下载统一进入分块流式发布器，在响应头和读取过程中双重限制大小，PDF 默认 256 MB、补充材料 2 GB、元数据 JSON 8 MB，并对中断、HTML、截断、超限和哈希异常执行临时文件清理；ScienceDirect DevTools 捕获改用 `Fetch.takeResponseBodyAsStream` 与 `IO.read`。最终交付快照使用 `pypdf>=6,<7` 深检可打开且页数大于零的 PDF，失败项原子降级并记录内部解析错误。插件 CI 使用 Node 24，运行完整 65 项测试、检查关键源码被 Git 跟踪，并只在 CI 临时目录构建和检查 XPI 根目录内容；默认 Python 测试阻断未 mock 的公网 socket，但允许本机回环地址。
- 修改原因：避免异常退出造成任务永久卡住或重复下载，防止旧进程迟到结果覆盖新结果；避免把超时、限速和网络故障误报为“未找到”；避免整块响应占用过多内存或超大文件突破磁盘边界；确保结构上看似 PDF 的损坏、零页或不可解密文件不能进入最终成功清单；确保插件 manifest/package metadata 不再被宽泛 JSON 忽略规则漏掉，并在 Windows CI 中持续验证完整供应链。
- 生成的输出文件：仅新增或修改源代码、测试、CI、依赖和说明文件；测试使用系统临时目录及项目内排除 XPI 的临时副本，未生成真实论文 PDF、Cookie、机构会话或新的持久 XPI。现有 `dist/zotero-paper-download-bridge-0.2.0.xpi` 未修改，SHA-256 仍为 `D1C0C0E93228EF050FD674FCBE201731793EA19C4933C32747880043F474A460`。
- 如何运行：安装依赖后仍使用 `\.venv\Scripts\python.exe paper_batch.py start --input "papers.xlsx" --out "results" --email "you@example.com"`；恢复失败项使用 `retry-failed`，活跃租约冲突会返回 `batch_attempt_in_progress` 和退出码 2，过期租约会自动回收。开发验证可运行项目 README 中列出的 `compileall`、完整 Python 离线测试和 `node --test zotero_bridge_plugin/tests/*.test.cjs`。
- 如何检查是否成功：项目要求的 `compileall` 通过；插件 Node 24 环境下 65/65 项测试通过；排除现有 XPI 的临时副本中完整 Python 测试共 449 项，445 项通过、4 项按环境条件跳过、0 失败；`git diff --check` 通过；关键插件 manifest、package、bootstrap、核心脚本与本地化文件均被 Git 跟踪；现有 XPI 哈希与修改前一致。
- 注意事项或潜在风险：本轮未进行真实机构下载、未自动打包、未提交或推送；真实出版社与机构端的流式接口仍需后续手工 QA。`pypdf` 深检提高交付可信度，但不能证明论文语义内容与 DOI 必然一致；缓存文件如出现非末尾损坏会明确报错，需要保留文件后人工排查，不应直接删除。浏览器实例身份、`--auto-zotero`、`recover-oa` 退出码、`status` 命令和 UI 服务层仍不在本阶段范围内。

## 2026-07-22 20:06:42 +08:00 — 第三阶段 CLI 语义、浏览器身份与统一状态服务

- 修改日期和时间：2026-07-22 20:06:42 +08:00。
- 本次任务目标：修复 Zotero 自动参数语义和 `recover-oa` 恒为零的退出码；增加只读批次状态、统一 CLI/UI 请求边界和受控共享机构浏览器身份验证，同时保持批次目录、状态 v2、交付命名、兼容页面及现有 XPI 不变。
- 新增、修改或删除的文件：新增 `paper_automation/batch_app.py` 和 `tests/test_phase3_cli_browser_status.py`；修改 `paper_batch.py`、`paper_scraper_ui.py`、`paper_automation/batch_stages.py`、`paper_automation/batch_workflow.py`、`paper_automation/institutional/browser_session.py`、`paper_automation/institutional/workflow.py`、相关既有测试、`.github/workflows/tests.yml`、`README.md`、`README_zh.md`、`MANUAL_QA.md`、`skills/paper-download/SKILL.md` 和本文件。未删除用户文件。
- 具体修改内容：将 `start`、`retry-failed`、`recover-oa` 的 `--auto-zotero/--no-auto-zotero` 改为互斥且由单一布尔值控制，默认自动排队，所有 Zotero 入口默认 `--wait-seconds 0`；`recover-oa` 按无目标/全部成功、验证错误、等待桥接、确定性未解决和可恢复网络故障分别返回 0/2/3/4/5。新增类型化 `BatchCommandRequest`、`BatchCommandResult`、`BatchStatusSummary`，统一批次 UI 的六个动作共用请求构造与参数合同。新增 `paper_batch.py status --run-dir ... [--json]`，在状态锁内读取并验证前后字节完全一致，只输出汇总计数和下一步，不回收租约、不暴露 Cookie、附件路径或逐篇元数据。新批次允许 `debug_port=0` 动态分配；机构浏览器使用 `%LOCALAPPDATA%\PaperScraperDOI\browser-session\v1` 专用共享 profile、进程锁和原子实例描述文件，复用前同时验证 PID、浏览器路径、profile、`DevToolsActivePort`、端口及 browser ID，未知固定端口会拒绝接管。补充面向用户的租约、响应大小、元数据缓存和浏览器身份错误提示，并在 CI 编译列表中显式加入 `paper_batch.py`。
- 修改原因：旧 `--auto-zotero` 未实际参与决策且默认等待 600 秒容易表现为卡死；`recover-oa` 两个分支均返回 0，无法供脚本判断失败；仅凭固定 CDP 端口复用浏览器可能连接或关闭无关会话；UI、CLI 和自动化需要一个不修改状态的稳定进度接口与一致参数来源。
- 生成的输出文件：仅新增或修改源代码、测试、CI 和说明文件；未生成真实论文 PDF、Cookie、机构会话、Zotero 数据或新 XPI。测试在项目内排除 XPI 的临时副本和系统临时目录运行，临时副本在验证后清理。
- 如何运行：新批次仍使用 `.\.venv\Scripts\python.exe paper_batch.py start --input "papers.xlsx" --out "results" --email "you@example.com"`；有 fallback 时默认立即排队并以 3 返回，稍后运行 `.\.venv\Scripts\python.exe paper_batch.py zotero --run-dir "<run-dir>"`。状态检查使用 `.\.venv\Scripts\python.exe paper_batch.py status --run-dir "<run-dir>"`，自动化可追加 `--json`；只有希望当前进程等待时才显式传 `--wait-seconds N`。
- 如何检查是否成功：第三阶段专项测试覆盖互斥参数、默认零等待、OA 退出码、状态只读性/JSON、六个 UI 动作、浏览器身份字段、未知端口拒绝、动态端口和并发实例锁；项目 `compileall` 通过；排除现有 XPI 的临时副本中完整 Python 测试共 462 项，458 项通过、4 项按环境条件跳过、0 失败；Node 24 插件测试 65/65 通过；`git diff --check` 通过。现有 `dist/zotero-paper-download-bridge-0.2.0.xpi` SHA-256 仍为 `D1C0C0E93228EF050FD674FCBE201731793EA19C4933C32747880043F474A460`。
- 注意事项或潜在风险：本轮未进行真实机构下载、未启动或接管真实调试浏览器、未操作真实 Zotero 文库、未自动打包、未提交或推送。真实 Chrome/Edge 的动态 `DevToolsActivePort`、进程路径查询、机构登录复用和 Zotero 往返仍需按 `MANUAL_QA.md` 在隔离环境手工验收；实例描述文件不含 Cookie，但专用浏览器 profile 可能保存用户主动建立的登录会话，应按本机凭据目录保护。

## 2026-07-22 23:51:30 +08:00 — 修复 Windows CI 的 DevTools 捕获路径表示差异

- 修改日期和时间：2026-07-22 23:51:30 +08:00。
- 本次任务目标：修复 GitHub Actions `windows-tests` 在提交 `365f743` 上唯一失败的 `test_devtools_capture_uses_fetch_stream_and_io_reads`，使 Windows 短路径和长路径环境下的 DevTools PDF 捕获结果稳定。
- 新增、修改或删除的文件：修改 `sd_scraper.py` 和本 `CHANGELOG.md`；未新增或删除源码文件，未修改原始实验/文献数据。
- 具体修改内容：`_dt_capture_pdf` 发布 PDF 时继续让原子发布器使用规范化绝对路径进行安全写入，但返回调用者原始路径表达，仅替换可能因内容哈希冲突产生的文件名。这样不会改变文件内容、校验、哈希或交付位置，只避免 `C:\\Users\\RUNNER~1` 与 `C:\\Users\\runneradmin` 的字符串表示差异穿过调用边界。
- 修改原因：GitHub Windows runner 的临时目录可能以 8.3 短路径传入，而共享发布器内部 `Path.resolve()` 会返回长路径；远端测试因此出现同一实际文件的路径字符串断言失败。
- 生成的输出文件：未生成论文 PDF、Cookie、机构会话或打包文件；仅使用项目 `.codex-test-tmp\\paper-scraper-doi-ci-check-20260722-235100` 的干净源码副本进行验证。
- 如何运行：定向测试使用 `.\\.venv\\Scripts\\python.exe -m unittest tests.test_recovery_phase2.StreamingAndParserTests.test_devtools_capture_uses_fetch_stream_and_io_reads -v`；完整验证还运行项目 `compileall`、Python 全量 `unittest discover -s tests -v` 和 `node --test zotero_bridge_plugin/tests/*.test.cjs`。
- 如何检查是否成功：定向回归测试通过；干净源码副本中 Python 全量测试为 `Ran 462 tests ... OK (skipped=4)`，Node 插件测试为 `65/65` 通过，Python 编译检查通过，`git diff --check` 通过。
- 注意事项或潜在风险：本机项目中已有的被 Git 忽略旧 `.xpi` 未删除或移动；本次未自动打包、未提交、未推送，GitHub Actions 仍需在推送修复后的提交后重新运行确认。

## 2026-07-23 00:14:27 +08:00 — 修复 Node 24 插件测试计数校验

- 修改日期和时间：2026-07-23 00:14:27 +08:00。
- 本次任务目标：修复 GitHub Actions `windows-tests` 在提交 `976beee` 上因 Node.js 24 TAP 输出格式变化而误判失败的问题。
- 新增、修改或删除的文件：修改 `.github/workflows/tests.yml` 和本 `CHANGELOG.md`；未新增或删除源码文件，未修改原始实验/文献数据。
- 具体修改内容：插件测试仍要求完整的 65 项测试，但计数校验同时接受旧格式 `# tests 65` 和 Node 24 使用的 `ℹ tests 65`，并保持失败测试由 Node 退出码直接判定。
- 修改原因：Run 21 的实际结果为 `tests 65`、`pass 65`、`fail 0`，但 workflow 只匹配 `# tests 65`，导致 PowerShell 在 Node 返回成功后再次抛出“Expected the complete 65-test plugin suite.”。
- 生成的输出文件：未生成论文 PDF、Cookie、机构会话或 XPI 打包文件。
- 如何运行：在 `zotero_bridge_plugin` 目录运行 `node --test tests/*.test.cjs`，并检查 Node 24 输出中的 `ℹ tests 65`、`ℹ pass 65`、`ℹ fail 0`；随后运行项目既有的 Python 编译和测试检查。
- 如何检查是否成功：本地 Node v24.18.0 测试退出码为 0，65 项全部通过；workflow 正则可匹配 `ℹ tests 65`；提交后需以 GitHub Actions `windows-tests` 成功为最终确认。
- 注意事项或潜在风险：本次只调整 CI 输出解析，不改变插件业务逻辑、测试内容或交付文件；未自动打包 XPI，未修改现有被 Git 忽略的 XPI。

