# CHANGELOG

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
  - 统一混合文本解析中的 DOI 正则，允许合法圆括号，完整保留老 Elsevier DOI。
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
  - 新增 `paper-download` skill，按用户意图自动路由到 ScienceDirect 机构权限下载流程或合法 OA 下载流程。
  - 保留 `sciencedirect-doi-download` 和 `legal-oa-paper-download` 两个旧 skill，不删除、不破坏已有调用。
  - 在 README 和中文 README 中说明推荐使用 `$paper-download`，旧入口作为兼容入口继续可用。
  - 在 skill 打包测试中增加 `paper-download` frontmatter 检查，确保新增入口随 `skills/` 目录一起安装。
- 修改原因：
  - 原来 ScienceDirect 机构下载和合法 OA 下载是两个独立 skill，用户需要自行选择；新增统一入口可以减少选择成本，同时保持两条下载流程的权限边界清晰。
- 如何运行：
  - 安装 skill：`powershell -ExecutionPolicy Bypass -File install_codex_skills.ps1`
  - 使用统一入口：`Use $paper-download to download these papers: ...`
  - ScienceDirect 机构权限流程仍会调用 `sd_institutional_skill.py`。
  - 合法 OA 流程仍会调用 `paper_skill.py`。
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

- 本次任务目标：为 UI 新增合法 OA 下载模式，并修复 ScienceDirect PDF 文件名元数据缺失导致的 `unknown-year_Unknown_S...pdf` 问题。
- 新增、修改或删除的文件：
  - 修改 `paper_scraper_ui.py`
  - 修改 `sd_scraper.py`
  - 修改 `tests/test_doi_batch_utils.py`
  - 修改 `tests/test_sd_institutional_skill.py`
  - 修改 `README_zh.md`
  - 修改 `WINDOWS_UI_README.md`
  - 修改 `CHANGELOG.md`
- 具体修改内容：
  - UI 新增“合法 OA 下载”页，支持选择 `.txt/.md/.markdown/.csv` 文件或直接粘贴论文列表，调用 `paper_skill.py`。
  - 合法 OA 模式支持输出目录、邮箱、dry-run、覆盖已存在 PDF、limit 参数；不使用 Cookie JSON 或 Chrome/Edge 机构登录。
  - ScienceDirect DOI 解析时从页面 HTML 的 `citation_title`、`citation_author`、`citation_publication_date`、`citation_journal_title` 补全标题、作者、年份和期刊。
  - PDF 文件名生成改为优先使用 `年份_第一作者_标题_短hash.pdf`；没有元数据时用 DOI/PII 兜底，不再优先生成 `unknown-year_Unknown_S...pdf`。
  - 增加 UI 命令构造测试、ScienceDirect 元数据补全测试和无元数据文件名兜底测试。
- 修改原因：
  - Skill 已有 ScienceDirect 与合法 OA 两条下载路径，但 UI 之前只有 ScienceDirect 入口。
  - 部分 DOI 批量下载结果缺少标题、作者、年份，导致 PDF 文件名可读性差，不便于文献整理。
- 如何运行：
  - 启动 UI：`.\start_paper_scraper_ui.bat`
  - ScienceDirect：打开“DOI 批量下载”页，选择 DOI 表和 Cookie JSON，勾选“检索后下载 PDF”，点击“开始运行”。
  - 合法 OA：打开“合法 OA 下载”页，选择文件或粘贴论文列表，选择输出目录，按需勾选 dry-run，点击“开始运行”。
  - 语法检查：`.\.venv\Scripts\python.exe -m py_compile sd_scraper.py paper_scraper_ui.py sd_institutional_skill.py paper_skill.py`
  - 单元测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests -v`
- 生成的输出文件：
  - 本次没有正式下载论文，没有生成新的 PDF 结果目录。
  - ScienceDirect 运行时仍生成 `doi_batch_resolved.xlsx`、`doi_batch_failed.csv`、`pdf_download_report.csv`、`run_summary.txt` 和 `pdfs\`。
  - 合法 OA 运行时生成 `pdfs\`、`metadata\manifest.csv`、`metadata\manifest.json`、`failed\duplicates.csv` 等。
- 如何检查是否成功：
  - UI 命令预览中，ScienceDirect 页仍显示 `sd_scraper.py` 命令。
  - UI 命令预览中，合法 OA 页显示 `paper_skill.py --input ... --out ...` 或粘贴内容对应的临时输入文件。
  - ScienceDirect 下载出的 PDF 文件名应包含年份、第一作者和标题；缺少元数据时至少使用 DOI/PII 兜底，不再出现 `unknown-year_Unknown_S...` 作为优先形式。
  - 新增和完整单元测试应全部通过。
- 注意事项或潜在风险：
  - 本次不改变 ScienceDirect CDP/DevTools 下载机制，不改变机构权限和 Cookie 使用方式。
  - 合法 OA 模式只下载明确开放获取的 PDF；无法合法下载的论文会写入 manifest 的失败或待复核状态。
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
  - 对项目做公开发布前的稳妥硬化：降低合规误读风险，补充来源声明、License/NOTICE、CI 和发布安全说明，并修复大批量任务前期长时间无反馈的问题。
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
  - 将公开文档、帮助文本和源码注释中的高风险访问措辞改为中性表述，强调使用用户已授权的真实浏览器会话、Cookie 和 CDP 捕获有权限访问的 PDF。
  - 保留并强化合规边界：不绕过权限、不自动完成 CAPTCHA，不下载无合法访问权限的 PDF。
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
  - 项目准备公开发布，需要让 README、skill、源码注释和打包说明更清楚地表达合法使用边界，避免被误解为规避访问控制或破解验证。
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
  - 文案安全扫描不应命中把工具能力描述为规避检测的短语；只允许出现禁止性、安全边界类表述。
  - `git ls-files` 敏感产物扫描不应出现真实 `cookie.json`、PDF、`results/`、`.venv/`、`dist/` 等运行产物。
  - 运行 `--beginner --preflight` 时，应能先看到本地预览和去重报告，不默认进行联网元数据补全。
- 注意事项或潜在风险：
  - 本次不改变 ScienceDirect/CDP/机构权限下载核心流程，也不改变 Cookie、浏览器登录或 PDF 下载策略。
  - 本次没有重新打包 Windows UI；如需发布压缩包，应后续显式运行打包脚本，并再次检查包内是否包含敏感文件。
  - 本地未跟踪的 `cookie.json`、`results/`、PDF 和虚拟环境不应删除，但也不应进入 Git 或发布包。

## 2026-07-09 16:02:36

- 本次任务目标：
  - 根据当前项目与原项目的实际关系，完善公开来源声明和 MIT 修改版权表述。
  - 将用户可见的“合法 OA 下载”改为更审慎的“OA 资源辅助获取”，避免公开发布时被理解为法律保证。
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
  - README、Windows UI 文档和 UI 标签将“合法 OA 下载”统一改为“OA 资源辅助获取”，把“只下载公开合法 OA PDF”等绝对表述改为“仅尝试识别并下载公开开放获取的 PDF 候选资源”。
  - `paper_skill.py` 的命令行描述改为识别公开开放获取 PDF 候选资源并下载可访问文件。
  - Skill 文档改为“open-access PDF candidates / download assistance”等审慎表述；保留 `legal-oa-paper-download` 目录名和 skill name 作为兼容入口。
  - 更新测试，检查新版权声明、新来源声明、新 UI 摘要名称，并增加公开文案禁用短语检查。
- 修改原因：
  - 项目确实复用了原项目的实质性代码、结构或实现逻辑，因此公开声明应采用“基于并扩展”而不是“仅受启发”。
  - “合法 OA”容易被误解为工具对下载行为作出法律保证；公开发布时更适合使用“OA 资源辅助获取”和“公开开放获取 PDF 候选资源”。
- 如何运行：
  - 语法检查：`.\.venv\Scripts\python.exe -m py_compile paper_scraper_ui.py paper_skill.py`
  - 定向测试：`.\.venv\Scripts\python.exe -m unittest tests.test_doi_batch_utils tests.test_skills_packaging -v`
  - 完整测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  - 文案检查：`rg -n "合法 OA 下载|公开合法 OA|only legal open-access PDFs|legal open-access workflow" README.md README_zh.md WINDOWS_UI_README.md NOTICE paper_scraper_ui.py paper_skill.py skills docs`
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
  - `README.md` 聚焦项目用途、合规边界、快速开始、常用工作流、输出文件、安全提醒、开发检查和来源声明。
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
  - 新增 AAAS、Taylor & Francis、ACS、AIP 四类常用出版社的合法官网 PDF 候选链接适配，避免这些 DOI 直接落入 `unsupported_publisher`。
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
  - 这些修改只增加合法出版社官网候选链接，不绕过付费墙、不伪造权限、不跳过 `%PDF` 文件头校验。
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

- 本次任务目标：解析 `D:\桌面\文献下载\acta_v51_must_cite_100_high_level_references.md`，并下载其中可合法访问的论文 PDF。
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
- 修改原因：原始清单由 AAAS、Taylor & Francis、ACS、Springer、IUCr 和 AIP 等多个非 Elsevier 出版商组成，ScienceDirect 专用入口不适用，需要按出版商路由并使用合法机构访问或官方公开链接。
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
  - AIP 文献需要用户本人完成 Cloudflare Turnstile 验证；不得绕过验证码或付费墙。
  - 未修改原始 Markdown，未自动重新打包项目。

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
