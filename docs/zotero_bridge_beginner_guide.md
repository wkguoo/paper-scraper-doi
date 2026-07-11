# Zotero 9 本地桥接新手指南

这套流程用于“项目先下载，Zotero 9 只补失败项”。插件安装并通过测试后，
你通常只需提供文献清单、在 Zotero 中确认一次，最后到批次的 `pdfs\` 取 PDF。

## 运行前准备

- 使用 Windows、Python 虚拟环境和 Zotero 9.0.x。
- Zotero 端需要启用“文献下载桥接”插件并保持 Zotero 打开。
- 本地队列固定在
  `%LOCALAPPDATA%\PaperScraperDOI\zotero-bridge\v1`，不要手工编辑其中的 JSON。
- 当前仍处于源码与离线测试阶段。仅在用户明确批准后才生成 XPI。

## 正常运行

在项目根目录打开 PowerShell：

```powershell
.\.venv\Scripts\python.exe paper_batch.py start --input "papers.xlsx" --out "results"
.\.venv\Scripts\python.exe paper_batch.py resume --run-dir "<run-dir>"
.\.venv\Scripts\python.exe paper_batch.py zotero --run-dir "<run-dir>"
```

按下面规则执行：

1. `paper_batch.py start` 先运行项目已有的 ScienceDirect、机构权限和公开资源流程。
2. 只有 `working\manual_retry.csv` 有数据、且你已经完成项目提示的浏览器操作时，
   才运行一次 `paper_batch.py resume`；永远不要运行第二次。
3. 只有 `working\zotero_fallback.csv` 的剩余行会进入 Zotero 桥接，不会再次发送
   整份原始清单。
4. 第一次运行 `paper_batch.py zotero` 若返回退出码 `3`，表示已排队。保持
   Zotero 打开，并接受 one confirmation（一次确认）；即使内部有多个分块，仍然
   是 one confirmation per batch。
5. Zotero 完成后，只重跑同一条 `paper_batch.py zotero` 命令。项目会校验所有
   JSON 身份和摘要、生成严格 CSV，并自动完成 PDF 复核与复制。

最终 PDF 位于 `<run-dir>\pdfs\`，审计报告位于 `<run-dir>\reports\`。
系统遵守 do not overwrite：不覆盖原始输入、Zotero 附件、已有结果或已有 PDF。

## 如何判断成功

- 命令不再返回退出码 `3`，而是报告已完成或仍有未解决项。
- `<run-dir>\reports\final_manifest.csv` 和 `final_manifest.xlsx` 已生成。
- `<run-dir>\pdfs\` 只包含经过 PDF 内容、普通文件和 reparse-point 复核的副本。
- `reports\failed.csv` 与 `run_summary.txt` 如实列出 `no_pdf`、取消或其他失败；
  未解决不等于完成。

## 常见恢复

| 情况 | 安全处理 |
| --- | --- |
| Zotero 没有打开或插件未启用 | 保留 `<run-dir>` 与队列，打开 Zotero 后只重跑 `paper_batch.py zotero`。不要重跑 `start`/第二次 `resume`。 |
| 作业过期（`job_expired`） | 保留报告；让项目为仍失败的行创建新桥接批次，不要手工改时间或旧 JSON。 |
| 插件版本/结果字段不匹配 | 停止消费并保留原文件；更新到与项目匹配的插件源码或测试 XPI 后再试。 |
| 用户取消 | 插件返回 `user_cancelled` 且不写 Zotero；确认需求后让项目创建新的失败项批次。 |
| Zotero 找不到 PDF | 保留 `no_pdf`/`no_available_pdf`，在 `reports\` 中查看；不要反复导入同一 DOI。 |
| 插件完全不可用 | 可按 Skill 的严格五列 CSV 规则生成 `zotero_unavailable` 恢复文件；这只更新未完成报告，不代表下载成功。 |

## Zotero 测试配置门禁

在真实使用前，只允许先验收 Zotero test profile（Zotero 测试配置）。当前约束是：

- do not install to the main profile yet；目前不要安装到主配置或主文库。
- 未经明确批准，不生成 XPI，也不修改任何 Zotero 配置。
- 获批后也只通过 `Zotero test` 配置的 Add-ons 界面安装，不直接复制 profile 文件。
- 测试配置通过现有 PDF、缺失 PDF、取消、分块一次确认、重启恢复与重复运行后，
  再单独征求主配置安装许可。

详细人工验收项见 [MANUAL_QA.md](../MANUAL_QA.md)。
