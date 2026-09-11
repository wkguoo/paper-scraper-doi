# Paper Scraper Windows UI

这个界面使用 Python 标准库 `tkinter` 编写，不需要额外安装 GUI 框架。推荐环境是 Windows 10/11 + Python 3.10 或 3.11。

**默认入口：统一批次（`paper_batch.py`）**——公开 OA → 机构访问 → **失败写入清单，默认不排队 Zotero 桥接**（默认无 `resume`）。GUI 已收口为统一批次和运行日志两个页签；ScienceDirect DOI 专用与 OA 专用能力仍作为命令行兼容入口保留。新任务请优先使用 `paper_batch.py`。

## 许可证

本项目采用 [MIT License](../../LICENSE)，版权归 `wkguoo` 所有。第三方代码许可声明见 [THIRD_PARTY_NOTICES.md](../legal/THIRD_PARTY_NOTICES.md)。

## 启动方式

在 Windows 文件管理器中双击：

```text
start_paper_scraper_ui.bat
```

首次启动时脚本会自动创建 `.venv` 并安装 `requirements.txt` 中的依赖；如果安装失败，窗口会保留错误信息，方便排查。

或在 PowerShell 中运行：

```powershell
cd "<仓库路径>"
.\start_paper_scraper_ui.bat
```

## UI 中的入口

| 页签 | 定位 |
| --- | --- |
| **统一批次（推荐）** | 默认页。`paper_batch.py` 的 `start` / `resume` / `zotero` |
| 运行日志 | 查看输出与报告 |

GUI 不显示邮箱或 Cookie JSON 输入框，也不会在启动统一批次时自动传递 `--email` / `--cookies`。这两个参数及 Cookie、浏览器会话、机构权限和 OA 底层逻辑仍保留在命令行中。

## 推荐操作流程：统一批次（paper_batch）

1. 启动后默认在「统一批次（推荐）」页，子命令选择 `start`。
2. 选择文献清单（TXT/MD/CSV/XLSX/XLSM），或直接粘贴 DOI/题名列表。
3. 选择输出根目录。GUI 使用统一批次的默认配置，不要求填写邮箱或 Cookie JSON。
4. 点击「开始运行」。失败项写入 `zotero_fallback`，不要求 Zotero 或自建桥接可用。
5. 需要复用库内已有 PDF 时，将批次目录交给 Codex，使用 `paper-download` 和官方 Zotero 插件处理。
6. 只有手动补下载或继续旧桥接时，才选择 `zotero` 并填写 `library-id` / 等待秒数；此时需保持 Zotero 与桥接插件可用。退出码 3 表示等待，就绪后继续同一命令。
7. `resume` 仅用于兼容旧批次或显式启用人工重试的场景，默认新任务无需使用。

批次目录结构示例：

```text
results\paper_batch_时间戳\
├── pdfs\
├── reports\
└── working\
    ├── batch_state.json
    ├── manual_retry.csv
    └── zotero_fallback.csv
```

也可用命令行完成同一流程：

```powershell
.\.venv\Scripts\python.exe paper_batch.py start --input "papers.xlsx" --out "results" --email "you@example.com"
# 可选：手动原生补下载，或继续旧桥接批次：
.\.venv\Scripts\python.exe paper_batch.py zotero --run-dir "results\paper_batch_时间戳"
```

## 兼容 / 高级命令行入口

GUI 不再提供 ScienceDirect DOI 专用页和 OA 专用页。如果确实需要旧流程，可继续使用底层命令行；相关脚本、参数和下载能力没有删除：

```powershell
# ScienceDirect DOI 批量兼容入口
.\.venv\Scripts\python.exe sd_scraper.py -m doi_batch --input "papers.csv" --doi-column "doi" --cookies "cookies.json" --download-pdfs

# OA 专用兼容入口
.\.venv\Scripts\python.exe paper_skill.py --help

# 统一批次中显式提供邮箱或 Cookie
.\.venv\Scripts\python.exe paper_batch.py start --input "papers.xlsx" --out "results" --email "you@example.com" --cookies "cookies.json"
```

Cookie JSON 属于凭据文件，不要提交到 Git，也不要放进打包目录。命令行兼容入口供了解参数含义的高级用户使用；新任务仍推荐统一批次。

## 输入表要求

最少需要 DOI 列。推荐列名：

```text
doi
```

也支持：

```text
DOI
Doi
DOI号
doi号
```

支持 `.xlsx`、`.xlsm`、`.csv`、`.tsv`、`.txt`、`.md`、`.markdown`。文本和 Markdown 文件会逐行扫描 DOI，不要求表头。如果是 CSV/文本文件，Excel/WPS 导出的 GBK/ANSI 编码也可以读取。

大批量导入时，预览和日志都采用分批刷新，避免一次性渲染全部数据导致界面卡死。

界面会记住最近的输出目录、批次操作参数和窗口尺寸，配置保存在 `results/_ui_settings.json`。旧设置中的邮箱或 Cookie 项会被忽略，但设置文件不会被删除。

## 输出文件

运行后会生成类似目录：

```text
results\doi_batch_时间戳\
├── doi_batch_resolved.xlsx
├── doi_batch_failed.csv
├── pdf_download_report.csv
├── run_summary.json
├── run_summary.txt
└── pdfs\
```

`doi_batch_failed.csv` 用于查看哪些 DOI 没有解析；`pdf_download_report.csv` 逐篇记录 PDF 下载成功、失败或跳过；`run_summary.txt` 汇总本次任务和下一步建议，`run_summary.json` 供界面或后续脚本读取。`supplement_download_report.csv` 和 `supplements\` 只在启用 PDF 下载并勾选“同时下载补充材料”时生成；补充材料状态 `not_found` 表示页面没有检测到 supplement 链接，不是正文 PDF 失败。

## 获取可分发源码

公开分享时使用 GitHub Releases 或仓库页面自动生成的 **Source code** 压缩包，也可以在目标电脑上直接克隆：

```powershell
git clone https://github.com/wkguoo/paper-scraper-doi.git
```

不要直接压缩自己的整个项目工作区发布，因为工作区可能包含 `cookie.json`、`results\`、下载的 PDF、`.venv\`、`dist\` 或浏览器缓存。
