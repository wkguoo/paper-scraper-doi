# Zotero 文献下载回退集成设计

## 状态

- 日期：2026-07-10
- 状态：用户已确认
- 目标：用户只需提供文献清单，由 Codex 调用本项目和 Zotero 完成尽可能自动化的 PDF 获取，最终集中交付 PDF，并尽量减少人工操作。

## 需求摘要

1. 支持直接粘贴文献清单，或读取 TXT、Markdown、CSV、XLSX 文件。
2. 原始输入只读，不删除、不覆盖、不移动。
3. 项目下载流程优先；只有项目下载失败的文献才进入 Zotero 回退。
4. Zotero 使用临时集合保存回退条目，任务结束后保留集合和条目，不自动删除。
5. 遇到机构登录、CAPTCHA 或出版社验证时只暂停一次；用户处理后自动重试一次，仍失败则记录并继续。
6. 成功 PDF 统一复制到一个最终目录；Zotero 原附件只读，不移动、不覆盖。
7. 不使用 Sci-Hub、Anna's Archive、LibGen 或其他影子库，不绕过访问权限或验证码。

## 方案选择

采用“Codex 编排 + 项目下载器 + Zotero 失败回退”的混合方案。

未选择的方案：

- Zotero 优先：会导入全部文献，容易产生重复条目并增加文库噪声。
- 独立 Zotero 插件：可以提供更深的一键式界面，但开发和维护成本明显更高，不适合作为第一版。

## 架构

### 1. 项目层

项目层负责确定性、可测试的批次处理：

- 读取和标准化输入；
- 提取 DOI、题名、作者、年份；
- 去重并建立每篇文献的稳定任务记录；
- 调用现有 OA、ScienceDirect 和非 Elsevier 机构访问流程；
- 验证、命名和汇总 PDF；
- 写入可恢复状态和最终报告。

新增 `paper_batch.py` 作为批次 CLI，并使用三个明确命令：

- `start`：接收互斥的 `--input` 或 `--text` 以及 `--out`，执行项目侧下载并生成 Zotero 回退清单；
- `resume`：接收 `--run-dir`，从批次状态中第一个未完成的项目阶段继续；
- `finalize`：接收 `--run-dir` 和 `--zotero-results`，验证 Zotero 返回的附件并生成最终报告。

状态管理、结果合并和 PDF 校验放入 `paper_automation/batch_workflow.py`，避免把批次逻辑或 Zotero 逻辑塞入现有单一出版社下载器。

### 2. Codex Skill 层

`skills/paper-download/SKILL.md` 作为用户入口，负责：

- 接收用户提供的清单或文件路径；
- 调用项目批次入口；
- 读取项目生成的 Zotero 回退清单；
- 调用 Zotero 工具查找、导入和获取附件；
- 将 Zotero PDF 复制到批次目录；
- 调用项目层完成最终核验与报告合并。

Zotero 工具只能从 Codex 会话调用，因此完整的跨应用自动化入口是 `$paper-download`。独立运行 Python CLI 时仍可完成项目下载和报告，但不能自行调用 Zotero MCP。

### 3. Zotero 层

Zotero 只处理项目下载失败项。临时集合命名为 `Codex下载回退_YYYYMMDD_HHMMSS`，并保留任务结果标签。

处理顺序：

1. DOI 精确搜索现有条目。
2. 已有条目且已有 PDF 时，直接复制有效附件。
3. 已有条目但无 PDF 时，将条目加入临时集合并触发可用 PDF 检索。
4. 没有现有条目时，按 DOI 导入临时集合并检索 PDF。
5. 无 DOI 时，只有在规范化题名匹配且年份或第一作者至少有一项一致时才关联；否则标记 `metadata_uncertain`。

Zotero 原附件不移动、不改名、不删除。成功附件只复制到最终批次目录。

## 数据流

1. 创建带时间戳的批次目录和批次状态文件。
2. 读取输入并生成规范化、去重后的文献记录。
3. 检查本批次已有有效 PDF，跳过已成功记录。
4. 尝试公开 OA PDF。
5. 将仍失败的 Elsevier/ScienceDirect 记录交给 ScienceDirect 机构访问流程。
6. 将支持的其他出版社记录交给非 Elsevier 机构访问流程。
7. 登录、CAPTCHA 或出版社验证最多暂停一次，并在用户处理后重试一次。
8. 生成 `zotero_fallback.csv`，只包含剩余失败项。
9. Codex 调用 Zotero 查重、导入和检索附件。
10. Codex 写出 `zotero_results.csv`，固定列为 `task_id`、`zotero_item_id`、`attachment_path`、`status` 和 `reason`。
11. `finalize` 复制 Zotero 成功附件，验证 PDF 文件头、基本大小和哈希。
12. 按 `年份_第一作者_题名_短标识.pdf` 生成安全文件名；冲突时使用 DOI 或内容哈希短值区分。
13. 合并所有结果并生成最终报告。

## 状态与恢复

每篇文献在关键步骤后立即写入状态，支持中断后继续。建议的主要状态包括：

- `pending`
- `oa_downloaded`
- `institutional_downloaded`
- `zotero_existing_pdf`
- `zotero_downloaded`
- `metadata_uncertain`
- `no_open_pdf`
- `no_entitlement`
- `captcha_required`
- `zotero_unavailable`
- `not_pdf_response`
- `network_error`

再次运行同一批次时，不重复访问已成功记录；从第一个未完成阶段继续。

## 错误处理

- 单篇失败不终止整个批次。
- Zotero 未打开或没有活动文库时，项目下载部分照常完成；回退项保存为 `zotero_unavailable`，待 Zotero 可用后继续。
- 登录、CAPTCHA 或出版社验证只暂停和重试一次，不循环访问。
- HTML 登录页、Cloudflare 页面或其他非 PDF 响应不得保存为 `.pdf`。
- 同一 DOI、同一 Zotero 条目或相同文件哈希不得重复复制。
- 目标文件名冲突时生成新文件名，不覆盖已有 PDF。
- Cookie 值、账号信息和机构会话内容不得写入日志或报告。
- 无可靠 DOI 且题名证据不足时不猜测对应关系。

## 输出结构

```text
results\paper_batch_YYYYMMDD_HHMMSS\
├── pdfs\
├── reports\
│   ├── final_manifest.csv
│   ├── final_manifest.xlsx
│   ├── failed.csv
│   └── run_summary.txt
└── working\
    ├── batch_state.json
    ├── normalized_input.csv
    ├── zotero_fallback.csv
    └── zotero_results.csv
```

用户主要使用 `pdfs\`；`reports\` 用于核对结果，`working\` 用于恢复任务。

## 安全与访问边界

- 只使用公开 OA、出版社官网和用户已有的机构访问权限。
- 不使用或调用 Sci-Hub、Anna's Archive、LibGen 或其他影子库。
- 新流程必须绕开并停用当前活动路径中的影子库自动回退；自动测试需要验证该回退不会被调用。
- 不自动处理或规避 CAPTCHA。
- 不要求用户向 Codex 提供密码或 Cookie 内容。
- 不修改原始输入、Zotero 原附件或已有 PDF。

## 自动测试

默认测试全部离线，使用模拟下载器和 Zotero 结果，覆盖：

- TXT、Markdown、CSV、XLSX 和粘贴文本解析；
- DOI 与题名去重；
- OA、Elsevier、其他出版社和 Zotero 回退顺序；
- 单篇失败隔离；
- 中断恢复和成功项跳过；
- PDF 文件头、文件大小、文件哈希和文件名冲突；
- Zotero 已有条目、已有 PDF、无 PDF、新条目和连接不可用；
- 敏感信息不进入日志；
- 活动路径不调用影子库。

现有离线测试必须继续通过。

## 人工验收

使用少量测试清单完成一次端到端检查：

1. Zotero 临时集合创建并保留。
2. 已有 Zotero PDF 成功复制到最终目录。
3. 无附件条目能够触发可用 PDF 检索。
4. Zotero 未打开时保留状态，打开后可继续回退阶段。
5. 登录或 CAPTCHA 只暂停和重试一次。
6. 最终 `pdfs\` 中每个文件都能作为 PDF 打开。
7. `final_manifest.xlsx` 中每篇文献都有明确状态、来源和文件路径或失败原因。

## 完成标准

- 用户可以把清单直接交给 `$paper-download`，无需自己选择下载器。
- 项目成功项和 Zotero 成功项集中出现在同一 `pdfs\` 目录。
- 除一次必要登录或验证外，不要求逐篇手工操作。
- 失败项具有可执行、可追踪的原因。
- 自动测试和人工验收均通过。
- 不自动打包 Windows 项目。
