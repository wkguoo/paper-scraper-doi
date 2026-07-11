# Zotero 9 本地文献下载桥接设计

## 状态

- 日期：2026-07-11
- 状态：用户已确认，进入实施计划阶段
- 目标环境：Windows、Zotero 9.0.6、Python 3
- 目标项目：`paper-scraper-doi`

## 目标

用户只提供文献清单。项目先通过已有的公开开放获取、出版社和用户已有机构权限流程下载 PDF；只有仍未解决的文献才交给 Zotero。Zotero 对整个批次只请求一次确认，随后自动查重、导入条目、查找可用 PDF，并把结果交回项目。项目最终把所有有效 PDF 非破坏性地汇总到同一个批次 `pdfs` 目录。

该设计消除正常工作流对 LLM for Zotero 写入确认界面的依赖，但保留现有严格 `zotero_results.csv` 接口、手工恢复能力和审计报告。

## 用户体验

推荐入口仍为 `$paper-download`。项目侧新增以下命令：

```powershell
.\.venv\Scripts\python.exe paper_batch.py zotero --run-dir "<run-dir>"
```

正常流程：

1. 用户把 DOI、题名列表或文献文件交给 Codex。
2. Codex 运行 `paper_batch.py start`，必要时只运行一次 `resume`。
3. 如果 `zotero_fallback.csv` 有数据，Codex运行 `paper_batch.py zotero`。
4. Zotero 显示一个批次确认窗口。用户只点击一次“确认执行”。
5. 插件处理整批文献，项目接收结果并自动调用现有 `finalize`。
6. 用户主要使用 `<run-dir>\pdfs\`，失败原因保存在报告中。

如果没有回退条目，`zotero` 命令不创建任务并直接完成现有报告。若 Zotero 未启动，命令保留任务和批次状态，用户打开 Zotero 后可继续，不重新执行项目下载。

## 方案比较

### 方案 A：本地文件队列桥接插件（采用）

Python 以原子方式写入固定目录中的 JSON 任务；Zotero 插件监视任务目录，确认后使用 Zotero JavaScript API 处理并写回 JSON 结果。

优点：

- 不依赖未公开的 Zotero HTTP 端点注册机制；
- 不需要开放新端口；
- 不需要 Web API 密钥；
- 请求、结果和恢复状态可审计；
- 容易离线测试、重放和幂等处理；
- 用户操作只有每批一次确认。

代价：插件需要短周期轮询任务目录，并需要维护一个很小的本地作业状态机。

### 方案 B：Zotero 内部 HTTP 端点

插件在 Zotero 的本地服务器中注册自定义写端点，Python 通过 `localhost` 调用。调用响应更直接，但自定义端点注册依赖未形成稳定公共合同的内部接口。Zotero 官方 Local API 当前适合快速本地读取，不提供该工作流需要的写入能力，因此不作为第一版基础。

### 方案 C：Zotero Web API 与 Local API 混合

Web API 可以修改文库，Local API 可以读取本机数据，但两者无法可靠替代桌面 Zotero 的“查找可用 PDF”动作，也会引入 API Key 管理和本地附件路径关联问题，因此不采用。

## 总体架构

```text
文献清单
  -> paper_batch start/resume
  -> working/zotero_fallback.csv
  -> paper_batch zotero
  -> 本地桥接 inbox/<job_id>.json
  -> Zotero 9 插件：一次确认、查重、导入、查找 PDF
  -> 本地桥接 outbox/<job_id>.result.json
  -> 项目验证并排他创建 zotero_results*.csv
  -> 现有 finalize
  -> pdfs/ + reports/
```

职责边界：

- 项目层负责批次状态、任务创建、结果验证、PDF 安全复制、最终报告和恢复。
- 插件层只负责 Zotero 文库内操作和返回附件的绝对本地路径，不复制最终 PDF。
- Zotero 原附件只读；项目只把验证后的内容复制到批次目录。
- Skill 只负责按顺序调用命令、向用户报告一次确认需求和交付结果，不再直接执行 Zotero 文库写入。

## 本地桥接目录

默认目录：

```text
%LOCALAPPDATA%\PaperScraperDOI\zotero-bridge\v1\
├── inbox\
├── processing\
├── outbox\
├── archive\
└── plugin-state.json
```

约束：

- 目录固定在当前 Windows 用户的本地应用数据中，不由任务载荷指定。
- 项目使用临时文件加同目录原子重命名发布任务。
- 插件只读取 `inbox`，只写 `processing`、`outbox` 和 `archive`。
- 项目不接受任务中指定任意插件输出目录。
- 文件名只允许小写 UUID job ID 和固定后缀。
- 插件不会执行载荷中的代码、命令、URL 或路径写入指令。

## 请求合同

请求 JSON 顶层字段固定为：

```json
{
  "schema_version": 1,
  "job_id": "uuid",
  "payload_sha256": "hex",
  "created_at": "ISO-8601",
  "expires_at": "ISO-8601",
  "run_id": "paper_batch_YYYYMMDD_HHMMSS",
  "library_id": 1,
  "collection_name": "Codex下载回退_YYYYMMDD_HHMMSS",
  "items": []
}
```

每个 `items` 元素只允许：

```json
{
  "task_id": "paper-0001",
  "doi": "10.xxxx/yyy",
  "title": "Paper title",
  "authors": "Author text",
  "year": "2025"
}
```

验证规则：

- `schema_version` 必须等于 1；
- 每批默认最多 100 条，超过时项目拆成多个子作业，但一个用户批次仍只进行一次总确认；
- `task_id` 必须在作业内唯一，并与当前 `zotero_fallback.csv` 完全对应；
- DOI 规范化后再计算载荷哈希；
- 题名、作者和年份都有长度上限；
- 请求有效期默认 24 小时；过期请求不执行，只返回 `job_expired`；
- `library_id` 必须是可编辑的用户文库，插件确认窗口显示文库名称与 ID；
- 相同 `job_id` 只能对应相同 `payload_sha256`，否则拒绝为 `job_id_conflict`。

## Zotero 插件行为

插件源代码放在项目的 `zotero_bridge_plugin/`，使用 Zotero 9 的 bootstrapped WebExtension 结构：

```text
zotero_bridge_plugin\
├── manifest.json
├── bootstrap.js
├── content\
│   ├── bridge.js
│   └── confirm.xhtml
├── locale\zh-CN\bridge.ftl
└── README.md
```

插件启动后：

1. 验证 Zotero 版本、所需 JavaScript API 和桥接目录。
2. 每秒检查一次 `inbox`；关闭时停止计时器。
3. 把完整且有效的任务原子移动到 `processing`。
4. 对同一用户批次聚合等待中的子作业，只显示一次确认窗口。
5. 确认窗口显示文库、文献数量、临时集合和可能执行的动作。
6. 用户确认后串行处理条目，避免给出版社或 Zotero 造成突发请求。
7. 每处理一条立即把进度写入临时结果，插件或 Zotero 异常退出后可继续。
8. 作业完成后原子发布结果到 `outbox`，请求和结果副本进入 `archive`。

用户取消时不执行任何文库写入，结果为 `user_cancelled`，批次保持可恢复。插件不会不断弹窗；同一 job 被取消或失败后，只有项目显式创建新的 retry job 才会再次请求确认。

## 条目解析与 PDF 检索

每篇文献按以下顺序处理：

1. DOI 精确查找现有普通条目，比较规范化 DOI。
2. 没有 DOI 时，以规范化题名为主键，并要求年份或第一作者至少一个一致；多条匹配时返回 `metadata_uncertain`。
3. 找到条目后检查子附件；选择第一个存在、可读且 MIME 类型或扩展名表示 PDF 的本地附件。
4. 已有 PDF 时返回 `existing_pdf`，不触发网络查找。
5. 已有条目但无 PDF 时，把条目加入临时集合并调用可用的 `Zotero.Attachments.addAvailablePDF`。
6. DOI 未入库时，使用 Zotero 搜索翻译器导入元数据到指定文库和临时集合；导入后再次按 DOI 校验，避免错误关联。
7. 对新条目调用一次可用 PDF 检索；不自动重复、不绕过登录或 CAPTCHA。
8. 成功后返回附件 ID 和 `getFilePath()` 得到的绝对路径。

所有非公开、可能变动的 Zotero API 都进行启动时功能检测。缺少关键 API 时整批返回 `zotero_api_unavailable`，不做部分写入猜测。数据库写入使用 Zotero 数据对象和事务 API，不直接修改 SQLite。

## 结果合同

插件结果 JSON 包含作业信息、插件/Zotero 版本、开始与结束时间，以及逐条结果。逐条固定字段：

```json
{
  "task_id": "paper-0001",
  "zotero_item_id": "304",
  "attachment_path": "C:\\...\\paper.pdf",
  "status": "existing_pdf",
  "reason": ""
}
```

插件允许的成功状态：

- `existing_pdf`
- `downloaded`

允许的失败或恢复状态：

- `metadata_uncertain`
- `no_pdf`
- `not_found`
- `user_cancelled`
- `zotero_unavailable`
- `zotero_api_unavailable`
- `job_expired`
- `job_id_conflict`
- `plugin_error`

项目端不直接信任插件结果。它必须：

- 校验 schema、job ID、payload hash、任务集合、唯一性和状态白名单；
- 把桥接状态映射到现有五列 Zotero CSV 状态；
- 对成功行要求显式且可验证的 Zotero item ID；
- 继续使用现有绝对路径、重解析点、稳定文件句柄、PDF 文件头和哈希校验；
- 排他创建 canonical 或时间戳 retry CSV，绝不覆盖已有结果；
- 校验完成后才调用现有 `finalize_batch()`。

## 状态机与恢复

项目状态：

```text
fallback_ready -> bridge_queued -> awaiting_confirmation
  -> bridge_running -> bridge_result_ready -> finalized
```

恢复规则：

- Zotero 未打开：任务留在 `inbox`，项目报告等待，不重跑下载。
- 用户取消：不写文库，批次保留，下一次重试使用新 job ID。
- Zotero/插件中断：`processing` 中的检查点保留；重启后按 job ID 继续。
- 项目中断：`outbox` 结果保留；再次运行 `paper_batch.py zotero` 会复用相同 job/result。
- 某篇失败：记录原因并继续下一篇。
- 同一 job 重放：返回已完成结果，不重复导入、集合写入或 PDF 查找。
- 同一 DOI 在一个批次重复出现：项目标准化阶段已去重；插件仍进行第二层防御。
- 结果无效：不修改批次 state、不调用 finalize，保留原始结果供审计。

临时集合和条目默认保留。插件提供“查看最近批次”和“撤销本批新增”菜单作为安全恢复能力；撤销只处理插件明确记录为本批新建的集合成员关系、条目或附件，绝不删除预先存在的条目或附件，而且必须再次由用户确认。

## 安全与隐私

- 只使用公开 OA、出版社官网和用户已有机构权限。
- 不使用 Sci-Hub、Anna's Archive、LibGen 或其他影子来源。
- 不自动解决 CAPTCHA，不请求或记录密码、Cookie、API Key、机构会话内容。
- 文件队列限定当前 Windows 用户本地目录；没有监听网络端口。
- JSON 解析使用严格 schema、大小限制、深度限制和未知字段拒绝。
- 不接受任意代码、命令、输出路径或 URL。
- 日志对题名做长度限制，不记录敏感环境变量或附件内容。
- 插件只向用户确认的可编辑文库写入。
- 原始文献清单、Zotero 原附件和已有最终 PDF均不修改、不移动、不覆盖。

## 项目改动范围

预计新增：

- `paper_automation/zotero_bridge.py`：目录、schema、原子队列、轮询和结果验证。
- `zotero_bridge_plugin/`：Zotero 9 插件源代码与说明。
- `tests/test_zotero_bridge.py`：项目端离线测试。
- `tests/fixtures/zotero_bridge/`：最小安全 fixture。
- `docs/zotero_bridge_beginner_guide.md`：安装、使用和故障恢复说明。

预计修改：

- `paper_batch.py`：新增 `zotero` 子命令。
- `skills/paper-download/SKILL.md`：优先使用桥接，保留严格手工 CSV 恢复。
- `tests/test_skills_packaging.py`：更新编排合同。
- `README.md`、`README_zh.md`、`MANUAL_QA.md`：同步工作流与验收。
- `CHANGELOG.md`：逐步追加记录。

第一版不修改 Tkinter UI；CLI 和 Skill 验收稳定后再决定是否增加 UI 按钮。不会自动运行现有 Windows 打包脚本，也不会自动生成发布包。

## 测试策略

### 项目端离线测试

- 请求 schema、严格字段、大小/数量限制和未知字段拒绝；
- 原子发布与并发读取；
- job ID、payload hash 和重放幂等；
- 等待、取消、超时、插件错误和部分结果恢复；
- 插件结果到严格五列 CSV 的完整映射；
- 恶意路径、相对路径、URL、重解析点、文件替换和非 PDF 拒绝；
- 不覆盖 canonical/retry 结果；
- 自动 finalize 和报告幂等；
- 现有全部离线测试继续通过。

### 插件端测试

- 纯 JavaScript schema、状态机、匹配和结果映射测试；
- 模拟 Zotero API 测试已有 PDF、无 PDF、导入、歧义、失败隔离和幂等；
- 启动/关闭计时器和中断恢复；
- 一批只确认一次，取消时零写入；
- 无任意代码执行、无任意路径写入、无直接 SQLite 修改。

### Zotero 9 测试配置人工验收

先只在 `elpj7iql.Zotero test` 配置中验收：

1. 安装插件后健康状态正常。
2. 使用小型测试批次验证一次确认。
3. 已有 PDF 条目正确返回且原附件哈希不变。
4. 无 PDF 条目触发一次可用 PDF 检索。
5. DOI 未入库时导入一次且不重复。
6. 取消确认时文库零写入。
7. 中途关闭 Zotero 后能恢复。
8. 项目最终 `pdfs` 和报告正确，重复运行不产生重复文件或条目。

测试配置验收通过并得到用户明确允许后，才安装到主 Zotero 配置。插件 XPI 或其他安装包只在安装验收需要且得到允许时生成；不触发项目 Windows 发布打包。

## 完成标准

- 用户可以只提供文献清单，不手工填写 Zotero CSV。
- 项目优先下载，只有失败项进入 Zotero。
- 每个用户批次最多一次 Zotero 执行确认。
- Zotero 能处理已有 PDF、无 PDF 现有条目和 DOI 新条目。
- 项目与 Zotero 成功 PDF 汇总到同一 `pdfs` 目录。
- 原始输入、Zotero 附件和已有 PDF 保持不变。
- 单篇失败可追踪且不终止整批；中断后可恢复。
- 不依赖 LLM for Zotero 写入确认 UI，不使用影子来源，不绕过 CAPTCHA。
- 离线自动测试、插件测试和 Zotero 9 测试配置人工验收均通过。
- 主 Zotero 安装必须另经用户确认，Windows 项目不自动打包。

