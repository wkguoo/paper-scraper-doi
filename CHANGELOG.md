# CHANGELOG

## 2026-08-22 23:44（Asia/Shanghai）— 新增 DOI 元数据并发预检

- **任务目标：** 提供只核验和补全 DOI 元数据、不下载 PDF 的独立命令行流程，为后续统一批次下载生成结构化输入。
- **新增、修改或删除的文件：** 新增 `preflight_doi_metadata.py`、`tests/test_preflight_doi_metadata.py` 以及 `processed_data/` 下的元数据复核规则文件；追加本变更记录；未删除文件，未修改原始输入。
- **具体修改内容：** 按项目约定解析 Markdown DOI 表格，并发请求 Crossref 核验 DOI、补全规范题名、作者、期刊和年份；支持原子写入断点文件，输出保留源字段、HTTP 状态、题名相似度和预检原因。
- **修改原因：** 通用 Markdown intake 可能把多列表格内容误识别为混杂题名，且项目原先缺少“联网元数据预检但不下载”的独立 CLI。
- **生成的输出文件：** 在用户指定的输出目录生成预检 CSV 和可续跑的 `.partial.csv` 断点文件；本流程不生成 PDF。
- **如何检查是否成功：** 核对输出中的 `doi`、`title`、`authors`、`journal` 和 `year` 字段，确认文件使用 UTF-8-SIG 且题名无 HTML 或表格分隔符污染；运行 `python -m unittest tests.test_preflight_doi_metadata -v`、`python -m py_compile preflight_doi_metadata.py` 和 `git diff --check`。
- **注意事项或潜在风险：** Crossref 返回的元数据可能不完整或与输入题名存在差异；此类记录必须保留明确的复核状态，不能据此编造或删除文献条目。

## 2026-08-22 23:50（Asia/Shanghai）— 新增统一批次 API-only 模式

- **任务目标：** 为统一批次增加只使用 Elsevier API 的下载模式，禁止进入浏览器、机构网页、OA 或 Zotero 兜底流程。
- **新增、修改或删除的文件：** 修改 `paper_batch.py`、`sd_institutional_skill.py`、`paper_automation/batch_stages.py`、`paper_automation/batch_workflow.py`、`paper_automation/failure_routing.py`；追加本变更记录；未删除文件，未修改原始 Markdown 或预检 CSV。
- **具体修改内容：** 新增 `--api-only` 参数并将其保存到批次状态；启用后禁用浏览器兜底，跳过非 Elsevier adapter、OA 恢复和 Zotero 阶段，不生成浏览器或 Zotero 待处理队列，同时保留 API 限流、权限和熔断失败原因以支持后续重试。
- **修改原因：** 默认统一批次会在 API 失败后进入多级兜底，无法满足严格限制数据来源的批次需求。
- **生成的输出文件：** 成功下载的文件仍按统一批次规则发布到 `结果/pdf/`，并生成下载清单和审计报告；失败记录保留明确的 `api_only_*` 原因。
- **如何检查是否成功：** 运行语法检查以及 `tests.test_elsevier_api`、`tests.test_batch_optimizations`；确认 API-only 批次不会启动浏览器、OA 或 Zotero 阶段，且待处理队列为空。
- **注意事项或潜在风险：** API 限流、无权限、资源不存在或响应不是有效 PDF 时会如实保留失败，不会自动使用其他来源补齐。

## 2026-08-23 20:05（Asia/Shanghai）— 规范化项目变更记录

- **任务目标：** 清理项目级变更记录中的个人环境信息和与仓库代码变更无关的外部批次运行细节。
- **新增、修改或删除的文件：** 仅修改 `CHANGELOG.md`；未新增或删除文件，未修改项目代码、原始输入和外部批次结果。
- **具体修改内容：** 删除本机绝对路径、外部数据集名称、批次数量与下载结果、本机资源状态、进程操作过程和内部协作信息；将历史内容精简为 DOI 元数据并发预检与 API-only 模式两项可验证的项目变更。
- **修改原因：** 项目级日志应只记录仓库功能、代码、测试、文档和配置变化，不应暴露个人环境或混入外部任务的运行日志。
- **生成的输出文件：** 更新后的 `CHANGELOG.md`。
- **如何检查是否成功：** 全文检查不存在盘符绝对路径、身份信息、凭据、个人环境状态或内部协作信息；确认剩余记录均能对应到项目文件或公共命令行行为，并运行 `git diff --check`。
- **注意事项或潜在风险：** 本次仅清理项目日志，不移动或删除任何外部批次文件；批次级运行证据继续由对应运行目录中的状态和报告文件保存；未运行代码测试，未重新打包。

## 2026-08-23 20:13（Asia/Shanghai）— 清理旧上游公开归属

- **任务目标：** 将当前项目的公开许可证和产品说明统一为 `wkguoo` 身份，同时为仍保留的第三方兼容代码集中保存最低限度的 MIT 许可声明。
- **新增、修改或删除的文件：** 修改 `LICENSE`、`README.md`、`README_zh.md`、`WINDOWS_UI_README.md`、`make_windows_ui_package.bat` 和 `tests/test_skills_packaging.py`；新增 `THIRD_PARTY_NOTICES.md`；删除旧 `NOTICE`；追加本变更记录。
- **具体修改内容：** 根许可证改为 `Copyright (c) 2026 wkguoo`；三份公开说明删除旧来源定位并增加当前项目许可证入口；第三方来源、版权和完整 MIT 文本集中迁入第三方许可文件；Windows 发布清单与离线测试同步采用新文件名，并增加公开文档无旧归属残留的断言。
- **修改原因：** 项目功能与定位已经独立，旧公开文案会误导项目身份；仍继承的兼容代码需要继续随源码及发布包保留原许可文本。
- **生成的输出文件：** 新增 `THIRD_PARTY_NOTICES.md`；未运行打包脚本，未生成或更新 `dist/`。
- **如何检查是否成功：** 排除第三方许可文件后的全仓残留扫描无命中；`tests.test_skills_packaging` 26 项全部通过；项目规定的 `compileall` 通过；完整离线测试 458 项通过、2 项因 Windows 符号链接权限跳过；最终运行 `git diff --check`。
- **注意事项或潜在风险：** 本次未重写继承代码，因此第三方 MIT 声明不能删除；Git 历史、既有发布版本与附件均未修改；未自动打包、提交、推送或发布。

## 2026-08-23 20:36（Asia/Shanghai）— 精简 GitHub 首页并重组公开文档

- **任务目标：** 执行仓库首页优化的 P0/P1 阶段，减少根目录公开文件数量，让新用户先看到统一批次入口，同时保留完整中英文说明、人工 QA、安全策略和构建能力。
- **新增、修改或删除的文件：** 重写根 `README.md`；将原英文和中文长说明分别迁移为 `docs/user-guide/en.md`、`docs/user-guide/zh.md`；将 `WINDOWS_UI_README.md`、`MANUAL_QA.md`、`SECURITY.md` 分别迁移为 `docs/user-guide/windows-ui.md`、`docs/development/manual-qa.md`、`.github/SECURITY.md`；将两个构建脚本迁移到 `scripts/build/`；同步修改 `.gitignore`、`AGENTS.md`、`docs/zotero_bridge_beginner_guide.md`、`zotero_bridge_plugin/README.md` 及相关测试。
- **具体修改内容：** 根 README 改为中文优先的精简产品首页，集中展示 Latest Release、唯一推荐入口、快速开始、默认流程、交付目录和文档导航；完整说明保留在分类目录中；构建脚本从新位置自动解析项目根目录，`.gitignore` 显式保留 `scripts/build/` 中的源码脚本，Windows 源码包继续包含中英文指南、安全策略和人工 QA；测试中的路径与首页断言同步更新。
- **修改原因：** 原仓库根目录同时展示用户文档、开发文档、安全策略和构建脚本，首页层级不清晰；通过分类收纳减少视觉噪声，同时避免直接移动当前高度耦合的 Python 入口和兼容模块。
- **生成的输出文件：** 未生成运行结果或发布包；仅调整源码仓库内的文档、脚本位置与测试。
- **如何检查是否成功：** 项目规定的 `compileall` 通过；完整离线测试 458 项通过、2 项因 Windows 符号链接权限跳过；另有文档与构建路径专项测试 39 项通过；最终运行 `git diff --check` 并检查根目录文件清单。
- **注意事项或潜在风险：** 旧的构建命令需要改用 `scripts/build/` 路径；本次未自动执行打包、提交或推送。GitHub Description、Website 和 Topics 因当前环境缺少可用的 `gh`/Token，且已登录浏览器的页面控件读取超时，尚未修改远程设置。
