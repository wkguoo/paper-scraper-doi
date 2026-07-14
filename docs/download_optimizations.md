# 下载流程优化说明（复盘 1/2/3/4/5/9/10）

对应 `本次下载复盘报告` 中的优化项，已落地到代码默认行为。

## 变更一览

| # | 优化 | 默认行为 | 开关 |
| --- | --- | --- | --- |
| 1 | 跳过 DOI 预检 / 题名联网增强 | **关闭** preflight；intake 不做题名联网 | `--doi-preflight`、`--resolve-title-metadata` 可开 |
| 2 | 智能路由 + 顺序 | **先 Elsevier 机构**，再其它（gold OA→OA，其余→适配器） | `--no-smart-route` 时仍先 Elsevier，非 Elsevier 再全体试 OA |
| 3 | SD 限速 | 每 **8** 篇成功后歇 **60 s**（原 150 s） | `--session-break-seconds` / `--session-break-every` |
| 4 | 补充材料 | **默认下载** | `--no-download-supplements` 关闭 |
| 5 | 断点续传 | SD 写 `pdf_download_checkpoint.jsonl`，重跑跳过已成功 DOI | `resume=True`（默认） |
| 9/10 | 下载即最终命名 | `年份-作者-题名.pdf` | 无额外开关 |

## 推荐命令

```powershell
.\.venv\Scripts\python.exe paper_batch.py start `
  --input "papers.csv" `
  --out "D:\Lit\results" `
  --email "you@example.com" `
  --cookies "cookie.json"
```

**默认固定交付目录**（避免多次运行产生一堆时间戳文件夹）：

- 目录：`out/<输入文件名>/`（或 `--run-name 自定义名`）
- 再次 `start` 同一输入/名称 → **续跑同一目录**（已成功的 PDF 保留）
- 用户交付：`下载清单.csv` + `结果\`
- 强制新开一批：加 `--fresh`（新建时间戳目录，旧目录保留）
- 恢复旧行为（每次时间戳）：`--no-fixed-run`

不需要补充材料时：

```powershell
... start ... --no-download-supplements
```

需要题名补 DOI / 预检时：

```powershell
... start ... --resolve-title-metadata --doi-preflight
```

## 涉及文件

- `paper_batch.py` — CLI 默认与新参数
- `paper_automation/batch_stages.py` — `BatchOptions`、路由、SD 参数传递
- `paper_automation/batch_workflow.py` — intake、`run_initial` 智能路由、预检默认关
- `sd_scraper.py` / `sd_institutional_skill.py` — 限速 60s、补材默认关、checkpoint
- `sd_supplements.py` / `paper_automation/file_manager.py` — `年份-作者-题名` 文件名
- `paper_scraper_ui.py` — 补材默认不勾选
- `tests/test_batch_optimizations.py` — 回归测试

## 注意

- 被封锁后的长等待（270s/420s）仍保留，与「固定 60s 歇息」无关。
- gold OA 启发式包含 MDPI/Frontiers/PLOS/BMC/部分 Nature 开放系列；其它 OA 可之后再扩名单。
- 旧 `batch_state.json` 会自动补全新 options 字段默认值。
