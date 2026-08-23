# CHANGELOG

## 2026-08-22 23:11（Asia/Shanghai）— ACTA 全量论文下载

- **任务目标：** 从 `D:\桌面\文献下载 - 副本\1-1\doi_summary下载用已去重.md` 读取 1789 个唯一 DOI，使用统一批次流程下载论文及补充材料到 `D:\桌面\文献下载\ACTA`。
- **新增、修改或删除的文件：** 新建本变更记录；项目代码、配置和原始输入未修改；未删除文件。
- **具体修改内容：** 启动前确认输入包含 1789 个唯一 DOI，且全部为 `10.1016/*`；目标目录为空；使用 `paper_batch.py start` 的固定批次、DOI 预检、Elsevier API 优先、机构访问、限时 OA 与自动 Zotero 兜底流程。
- **修改原因：** 按项目规范为每个项目维护独立、可追溯的任务记录，并确保下载任务可中断续跑。
- **生成的输出文件：** 执行中；预计生成 `D:\桌面\文献下载\ACTA\结果\`、`reports\`、`working\` 与内部 `pdfs\`。任务结束后追加实际结果。
- **如何检查是否成功：** 对照 `结果\下载清单.csv`、`reports\final_manifest.csv`、`reports\failed.csv` 和 `reports\run_summary.txt`；校验成功 PDF 的文件头和命名规则。
- **注意事项或潜在风险：** D 盘启动时剩余约 35.41 GB；低于 5 GB 时安全中止并保留批次状态。不会修改源 Markdown、自动打包或上传 Git，也不会绕过出版商访问控制。

### 2026-08-22 23:21 暂停记录

- **执行结果：** 用户要求暂停后，已向唯一下载会话发送 `Ctrl+C` 并确认无残留 Python 下载进程。
- **已生成文件：** `D:\桌面\文献下载\ACTA` 下已保留 `batch_state.json`、`working\`、`reports\sciencedirect\` 及 79 个阶段 PDF；尚未完成最终发布，因此 `结果\下载清单.csv` 和最终清单不能视为完成状态。
- **流程调整：** 为提速曾在用户提出“尽量提速”后改用 `--no-doi-preflight`；有效唯一 DOI 仍为 1789。Elsevier API 成功约 79 篇后，其余 1710 条进入浏览器兜底解析，随后按用户要求暂停。
- **检查结果：** D 盘剩余约 35.30 GB；下载进程数为 0；原始 Markdown 未修改；未自动打包、未上传 Git。
- **注意事项：** 部分 Markdown 表格字段在内部 intake 中被识别为混杂题名。继续任务前应先确定结构化输入/元数据校正方案，并按 DOI 复核最终交付命名；不得把当前内部阶段文件误报为最终成果。

## 2026-08-22 23:44（Asia/Shanghai）— ACTA 全量 DOI 元数据预检

- **任务目标：** 暂不下载 PDF；对源 Markdown 中全部 1789 个 DOI 做联网元数据预检，生成结构化、可供后续 API 下载使用的文件。
- **新增、修改或删除的文件：** 新增 `preflight_doi_metadata.py`、`tests/test_preflight_doi_metadata.py`、`processed_data/ACTA_preflight_review_overrides.csv`；追加本变更记录；未删除文件，未修改原始 Markdown。
- **具体修改内容：** 按源表实际稳定的 15 字段解析 Markdown（表头额外声明但数据缺失的 `Notes` 不参与定位）；使用最多 4 个并发 Crossref 请求核验 DOI并补全规范题名、作者、期刊和年份；每 25 条原子写入断点；输出保留源字段、HTTP 状态、题名相似度和预检原因。主智能体与两个 Luna 子智能体分别复核源表结构、项目预检路径和两条作者字段缺失记录。
- **修改原因：** 现有通用 Markdown intake 会把部分多列表格行识别成混杂题名，且项目没有“联网元数据预检但不下载”的独立 CLI；新增最小脚本以保证后续 API 输入规范、可追溯、可续跑。
- **生成的输出文件：** `D:\桌面\文献下载\ACTA\预检\ACTA_DOI预检完成.csv`（自动版）、`ACTA_DOI预检完成_复核.csv`（初次复核版）、`ACTA_DOI预检完成_最终复核.csv`（最终使用版）及 `.partial.csv` 断点文件。原先暂停的 79 个阶段 PDF 保持不变。
- **如何检查是否成功：** 最终使用版共 1789 行、1789 个唯一 DOI，与源表集合及顺序完全一致；`doi/title/authors/journal/year` 均无空值；UTF-8-SIG；无 HTML 标签或 `|` 题名污染；项目 `load_tabular_records()` 可读取 1789 条。离线测试 `python -m unittest tests.test_preflight_doi_metadata -v` 通过 2/2，`py_compile` 与 `git diff --check` 通过。
- **预检状态：** `verified_crossref=1787`；`verified_publisher_title=1`；`verified_publisher_title_metadata_uncertain=1`。后两条的 Crossref/OpenAlex `creator` 为空，作者由 Elsevier FULL XML 官方题名补全；其中 DOI `10.1016/0036-9748(74)90036-2` 页码为 `xxx`，且与另一 Acta DOI 同题同作者，记录性质保留不确定性，但 DOI 本身有效且不删除。
- **注意事项或潜在风险：** 本次只查询元数据，未恢复论文下载、未启动浏览器/Zotero、未修改或删除已有批次文件。后续若要求“API-only”，当前统一下载流程仍会在 API 失败后自动进入浏览器/OA/Zotero，需要在下一任务中显式设计并验证 API-only 门禁；不得直接用现有默认流程声称只走 API。

## 2026-08-22 23:50（Asia/Shanghai）— ACTA API-only 下载启动

- **任务目标：** 直接使用预检完成文件中的 1789 个 DOI 恢复下载，只允许 Elsevier API，不进入浏览器、机构网页、OA 或 Zotero 兜底。
- **新增、修改或删除的文件：** 修改 `paper_batch.py`、`sd_institutional_skill.py`、`paper_automation/batch_stages.py`、`paper_automation/batch_workflow.py`、`paper_automation/failure_routing.py`；追加本变更记录；未删除文件，未修改原始 Markdown 或预检 CSV。
- **具体修改内容：** 为统一批次新增 `--api-only` 门禁并保存到批次状态；API-only 时 Elsevier 阶段显式禁用浏览器兜底，批次阶段跳过非 Elsevier adapter、OA 恢复和 Zotero，且不生成待人工浏览器/Zotero 下载队列；保留 API 限流和熔断原因以便固定批次后续重试。
- **修改原因：** 原默认流程在 API 失败后会自动进入多级兜底，不符合本次“API-only”约束。
- **运行命令：** `paper_batch.py start --input "D:\桌面\文献下载\ACTA\预检\ACTA_DOI预检完成_最终复核.csv" --out "D:\桌面\文献下载\ACTA" --run-name "API下载" --api-only --no-doi-preflight --download-supplements --no-auto-zotero`。
- **生成的输出文件：** 固定批次目录 `D:\桌面\文献下载\ACTA\API下载`；下载进行中，PDF 先写入批次阶段目录，完成后统一发布到 `结果\pdf` 并生成清单和报告。
- **如何检查是否成功：** 离线语法检查通过；`tests.test_elsevier_api` 与 `tests.test_batch_optimizations` 共 39 项测试全部通过。运行中核对 API PDF 数量、文件头、最终清单、失败原因以及空的浏览器/Zotero 队列。
- **注意事项或潜在风险：** API 限流或无权限条目会如实保留为失败，不使用其他来源补齐；D 盘低于 5 GB 时应安全中止。未自动打包、未上传 Git。

### 2026-08-23 03:20 完成与异常恢复记录

- **执行结果：** 首轮 Elsevier API 下载成功 1778 条、失败 11 条；对全部 11 条失败执行一次 API-only 固定批次重试，恢复 4 条瞬时网络/504 失败。最终为 1789 条输入、1782 条成功、7 条失败。
- **突发情况及处理：** 首轮下载后 `batch_state.json` 已完整记录 1778 成功和 11 失败，但主进程约 15 分钟未进入最终报告阶段。确认下载状态完整且 PDF 已落盘后，使用 `Ctrl+C` 安全终止停滞进程，再运行 `paper_batch.py delivery --run-dir "D:\桌面\文献下载\ACTA\API下载"` 从现有状态生成交付；未重新下载成功项。随后使用 `retry-failed --retry-all-failed --no-auto-zotero` 做一次 API-only 重试。
- **生成的输出文件：** `D:\桌面\文献下载\ACTA\API下载\结果\pdf\` 共 1782 个 PDF；`结果\补充材料\` 共 405 个文件；`结果\下载清单.csv`、`reports\final_manifest.csv`、`reports\failed.csv` 和 `reports\run_summary.txt` 均已生成。
- **验收结果：** 下载清单与最终清单均为 1789 条；成功 1782、失败 7；1782 个交付 PDF 全部具有有效 `%PDF-` 文件头，且文件名全部符合 `年份-第一作者姓-题名.pdf`，无 `Unknown` 或任务编号占位名；Zotero 队列为 0。
- **剩余失败：** 5 条 Elsevier API 持续返回 HTTP 404；2 条持续返回 HTML 而非 PDF，均保留精确 `api_only_*` 原因。按用户限定未转浏览器、OA、机构网页或 Zotero。
- **磁盘与风险：** 完成后 D 盘剩余约 21.30 GB，高于 5 GB 中止阈值。未修改源 Markdown/预检 CSV，未删除下载内容，未自动打包、未上传 Git。

### 2026-08-23 08:59 第二次失败项 API-only 重试

- **任务目标：** 按用户要求，对剩余 7 条失败 DOI 再尝试一次 Elsevier API 下载。
- **执行方式：** 在固定批次 `D:\桌面\文献下载\ACTA\API下载` 上运行 `paper_batch.py retry-failed --retry-all-failed --no-auto-zotero`；沿用批次保存的 `api_only` 门禁，不启用浏览器、OA 或 Zotero。
- **执行结果：** 7 条均未恢复；最终统计保持 1789 条输入、1782 条成功、7 条失败、1782 个交付 PDF。
- **失败分类：** 5 条持续返回 `api_only_not_found:http_404`；2 条持续返回 `api_only_invalid_pdf:article_response_html`。失败原因与上次一致。
- **检查方法：** 重新读取 `结果\下载清单.csv` 并核对 `结果\pdf` 实体数量；下载清单 1789 行、成功 1782、失败 7、PDF 1782。
- **注意事项：** D 盘剩余约 21.22 GB；没有覆盖原始输入、没有删除文件、没有自动打包或上传 Git。
