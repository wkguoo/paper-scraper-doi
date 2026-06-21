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
