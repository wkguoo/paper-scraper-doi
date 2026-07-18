# 下载流程优化说明

对应复盘优化项，已落地到代码默认行为。

## 变更一览

| # | 优化 | 默认行为 | 开关 |
| --- | --- | --- | --- |
| 1 | 跳过 DOI 预检 / 题名联网增强 | **关闭** preflight；intake 不做题名联网 | `--doi-preflight`、`--resolve-title-metadata` 可开 |
| 2 | 智能路由 + 顺序 | **先 Elsevier 机构**，再其它（gold OA→OA，其余→适配器）；**无适配器/抓取失败后 OA 直下** | `--no-smart-route` 时仍先 Elsevier，非 Elsevier 再全体试 OA |
| 3 | SD 限速 | 每 **8** 篇成功后歇 **60 s**（原 150 s） | `--session-break-seconds` / `--session-break-every` |
| 4 | 补充材料 | **默认下载** | `--no-download-supplements` 关闭 |
| 5 | 断点续传 | SD 写 `pdf_download_checkpoint.jsonl`，重跑跳过已成功 DOI | `resume=True`（默认） |
| 9/10 | 下载即最终命名 | `年份-作者-题名.pdf` | 无额外开关 |
| **A1** | 固定单 run + 耐久 `结果/` | `out/<run_name>/`；publish **merge-safe** 保留外部补入 PDF | `--fresh` / `--no-fixed-run` |
| **A2** | 失败阶梯 | 机构 → limited OA → `zotero_fallback`；`start`/`retry-failed`/`recover-oa` 默认可自动 Zotero | `--no-auto-zotero` |
| **A3** | 结果目录热刷新 | `refresh-delivery` 扫描 `结果/`、重命名、映射失败 DOI、刷新清单 | `paper_batch.py refresh-delivery` |
| **B4** | 平衡括号 DOI | `clean_doi` / `extract_doi_from_text` 保留 `()`，剥 `**` 等 markdown | 无开关 |
| **B5** | 文件名净化 | 剥 HTML/MathML/`iin-situ-i`/`sub2-sub` 残渣 | 无开关 |
| **C6** | IUCr 短试 | `10.1107` 机构失败 **1 次**熔断 → OA → Zotero | `--no-iucr-short-try` |

## 推荐命令

```powershell
.\.venv\Scripts\python.exe paper_batch.py start `
  --input "papers.csv" `
  --out "D:\桌面\文献下载" `
  --run-name "SAS" `
  --email "you@example.com" `
  --cookies "cookie.json"
```

交付路径：`D:\桌面\文献下载\SAS\下载清单.csv` + `D:\桌面\文献下载\SAS\结果\`

**默认固定交付目录**（避免多次运行产生一堆时间戳文件夹）：

- 目录：`out/<输入文件名>/`（或 `--run-name 自定义名`）
- 再次 `start` 同一输入/名称 → **续跑同一目录**（成功项保留）
- 用户交付：`下载清单.csv` + `结果\`（手动丢进 `结果/` 的 PDF 不会被下次 publish 清掉）
- 强制新开一批：加 `--fresh`
- 恢复旧行为（每次时间戳）：`--no-fixed-run`

手动补 PDF 后刷新清单/改名：

```powershell
.\.venv\Scripts\python.exe paper_batch.py refresh-delivery --run-dir "D:\桌面\文献下载\SAS"
```

不需要补充材料时：

```powershell
... start ... --no-download-supplements
```

关闭 IUCr 短试（完整多候选机构尝试）时：

```powershell
... start ... --no-iucr-short-try
```

## 涉及文件

- `paper_batch.py` — CLI：`start` / `retry-failed` / `recover-oa` / `refresh-delivery`
- `paper_automation/batch_stages.py` — `BatchOptions`、`is_iucr_doi`、机构传参
- `paper_automation/batch_workflow.py` — `run_post_download_ladder`、merge-safe `publish_user_delivery`
- `paper_automation/delivery_refresh.py` — A3 热刷新
- `paper_automation/institutional/workflow.py` — C6 IUCr short_try 熔断
- `doi_batch_utils.py` / `paper_automation/parser.py` — B4 DOI 抽取
- `paper_automation/file_manager.py` — B5 文件名净化
- `tests/test_batch_optimizations.py` / `tests/test_doi_batch_utils.py` — 回归

## 注意

- 被封锁后的长等待（270s/420s）仍保留，与「固定 60s 歇息」无关。
- gold OA 启发式包含 MDPI/Frontiers/PLOS/BMC/部分 Nature 开放系列。
- 旧 `batch_state.json` 会自动补全新 options 字段（含 `iucr_short_try`）默认值。
- A2 阶梯不替代 Zotero 桥接本身：需本机 Zotero + 插件在线；`--no-auto-zotero` 可只写 fallback。
- `metadata_uncertain` 仍默认不进 Zotero 队列（与既有 failure_routing 一致）。
