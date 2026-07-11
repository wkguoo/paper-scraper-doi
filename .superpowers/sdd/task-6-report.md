# Task 6 报告：初学者批次 CLI

## 范围

- 基线：`423f6a0`。
- 新增 `paper_batch.py`；仅扩展 `tests/test_batch_workflow.py` 的 `BatchCliTests`。
- 未修改 Task 4/5 工作流实现，未修改 Task 7 文档、技能、README 或打包文件。

## 实现

- 提供 `start`、`resume`、`finalize` 三个 argparse 子命令；`start` 的 `--input` 与 `--text` 严格互斥且必填。
- `start` 保留 `BatchOptions` 的 email、Cookie JSON 路径、浏览器、登录等待、调试端口和限速参数。
- 直接调用 `start_batch()`、`resume_batch()`、`finalize_batch()`；对 `ValueError`、`OSError`、`RuntimeError` 输出不含异常详情的中文错误码 2。
- 每个成功命令统一输出运行目录、最终 PDF 目录、六个统计/清单位置和报告目录；下一步命令采用 `sys.executable`、`paper_batch.py` 与双引号路径。
- Cookie 仅作为文件路径传递，CLI 不输出 Cookie 内容、state 内容或 traceback。

## TDD 与验证

- 红灯：新增 7 个 `BatchCliTests` 后，因 `ModuleNotFoundError: paper_batch` 预期失败。
- 绿灯：`python -m unittest tests.test_batch_workflow.BatchCliTests -v`，7 项通过。
- Task 4：`BatchRunTests`，38 项通过。
- Task 5：`BatchFinalizeTests`，24 项通过。
- 已执行 `paper_batch.py --help` 与 `paper_batch.py start --help`；输出为正常简体中文并列出安全工作流说明。
- 最终验证：全套离线测试 275 项通过（跳过 2 项）；`compileall` 和 `git diff --check` 退出码均为 0。

## 风险与限制

- 所有 CLI 测试均 patch 工作流函数，不联网、不读取真实 Cookie、不操作真实 Zotero 附件。
- 实际下载是否可用仍取决于合法 OA 来源或用户拥有的机构授权。

## 复审修复（第二提交）

- PowerShell 命令现在使用调用运算符 `&`、绝对 `sys.executable`、绝对 `Path(__file__).resolve()`；子命令、选项和值全部使用单引号，路径中的 `'` 转义为 `''`。离线 smoke 已从另一工作目录执行 `--help` 成功。
- 安全错误提示只提取异常文本开头的白名单错误码，并通过固定 `ERROR_HINTS` 给出中文修复建议；未知错误不显示异常文本，Cookie secret 回归用例未泄露。
- 无 fallback 且无需先重试时，缺失的 `working/zotero_results.csv` 自动以 UTF-8-SIG 和五列精确表头排他创建；已有文件保持原字节不变，有 fallback 时不创建。
- TDD：新断言先出现预期 RED；实现后 `BatchCliTests` 12 项、Task4 38 项、Task5 24 项、全套 280 项通过（跳过 2 项）；help 与 compileall 退出码为 0。
