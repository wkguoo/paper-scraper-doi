# ScienceDirect Paper Scraper Windows UI

这个界面使用 Python 标准库 `tkinter` 编写，不需要额外安装 GUI 框架。推荐环境是 Windows 10/11 + Python 3.10 或 3.11。当前版本提供 ScienceDirect 机构权限下载和 OA 资源辅助获取两个入口；Codex Skill 是可选增强，不影响图形界面单独使用。

## 来源声明

本项目基于开源项目 [GAO-pooh/paper-scraper](https://github.com/GAO-pooh/paper-scraper/tree/main) 修改并扩展。
授权和修改声明见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。

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

## UI 中的两个入口

- `DOI 批量下载` / `文献检索`：用于 ScienceDirect/Elsevier，依赖你的机构权限、Cookie JSON 或浏览器登录状态，PDF 下载仍使用原有 CDP/DevTools 流程。
- `OA 资源辅助获取`：用于非 ScienceDirect 或混合来源论文列表，仅尝试识别并下载公开开放获取的 PDF 候选资源，不读取 Cookie、不打开机构登录浏览器。

## 当前推荐操作流程：ScienceDirect DOI 批量下载 PDF

界面默认打开“DOI 批量下载”页，并按步骤分成“1 数据来源”“2 权限与输出”“3 预览检查”和底部运行按钮。

1. 在“1 数据来源”中选择 DOI 表格，例如 `lookup_preview.csv`、`papers.txt` 或 `papers.md`；也可以直接粘贴 DOI/表格内容。
2. 如需指定 Excel 工作表或 DOI 列名，填写“Excel 工作表名”和“DOI 列名”。
3. 在“2 权限与输出”中选择输出目录和 Cookie Editor 导出的 `cookies.json`。
4. 如果输入来自 AI 推荐、题名-only 列表或格式混乱的复制文本，先点击“生成新手预检报告”。它会调用 `sd_institutional_skill.py --beginner --preflight --auto-web-search`，不下载 PDF；确认 `doi_intake_preview.csv` 后，可点击“使用预检合并表”进入正式下载。
5. 保持“检索后下载 PDF”勾选；默认会同时下载 ScienceDirect 补充材料，如只要正文 PDF，可取消“同时下载补充材料”。只有 PDF 下载启用且该复选框保持勾选时，才会生成补充材料报告和目录。如果不用 Cookie JSON，再按需选择“从本机浏览器读取 Cookie”或“先弹出浏览器手动登录”（默认优先 Edge，Chrome 作为后备）。
6. 点击“预览解析”，在“3 预览检查”中确认识别到的 DOI 数量、列识别方式和前 200 条预览。
7. 点击底部固定操作栏中的“开始运行”；运行后界面会切到“运行日志”页。

不要勾选“从本机浏览器读取 Cookie”，也不要勾选“先弹出浏览器手动登录”。使用 Cookie Editor 导出的 `cookies.json` 时，程序会通过 `--cookies` 参数读取该文件。

也可以不选择文件，直接把 DOI 列表或从 Excel 复制出的表格粘贴到“直接粘贴 DOI 或表格内容”。点击“预览解析”后，界面只显示前 200 条，但会统计全部 DOI 数量；点击“开始运行”时会自动生成临时 CSV。

“生成新手预检报告”和“运行前体检（本地）”都不会下载 PDF，也不会生成 `supplement_download_report.csv` 或 `supplements\`。预检完成后结果区会出现“打开研究生查看入口”和“使用预检合并表”。

## OA 资源辅助获取流程

1. 打开“OA 资源辅助获取”页。
2. 选择 `.txt/.md/.markdown/.csv` 文件，或直接粘贴 DOI、标题、推荐文献列表。
3. 选择输出目录；邮箱可选，用于 Unpaywall/Crossref 礼貌访问。
4. 如需先检查识别结果，勾选 `Dry-run：只解析，不下载 PDF`。
5. 点击“开始运行”，日志页会显示 `manifest.csv`、`manifest.json` 和重复项报告位置。

该模式不会使用 Cookie JSON，也不会使用 Sci-Hub、LibGen 或其它绕过权限的来源；用户仍需自行确认使用方式符合出版商条款、机构访问政策和适用法规。

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

界面会记住最近的输出目录、Cookie 文件、窗口尺寸和常用登录选项，配置保存在 `results/_ui_settings.json`。

## 输出文件

运行后会生成类似目录：

```text
results\doi_batch_时间戳\
├── 00_给研究生查看\
│   ├── README_先看我.txt
│   ├── paper_index.csv
│   ├── paper_index.xlsx
│   └── 失败项_下一步处理.csv
├── doi_batch_resolved.xlsx
├── doi_batch_failed.csv
├── pdf_download_report.csv
├── library_index.csv
├── run_summary.txt
└── pdfs\
```

`00_给研究生查看` 是课题组交付入口：`paper_index.csv/xlsx` 汇总正文 PDF、补充材料、状态和失败原因，`失败项_下一步处理.csv` 按可操作类别给出下一步。`library_index.csv` 是同内容的根目录索引。`doi_batch_failed.csv` 用于查看哪些 DOI 没有解析；`pdf_download_report.csv` 逐篇记录 PDF 下载成功、失败或跳过；`run_summary.txt` 汇总本次任务和下一步建议。`supplement_download_report.csv` 和 `supplements\` 只在启用 PDF 下载并勾选“同时下载补充材料”时生成；补充材料状态 `not_found` 表示页面没有检测到 supplement 链接，不是正文 PDF 失败。

## 生成 Windows UI 源码包

运行：

```powershell
.\make_windows_ui_package.bat
```

生成目录：

```text
dist\paper-scraper-ui-windows
```

不要直接压缩自己的整个项目工作区发布，因为工作区可能包含 `cookie.json`、`results\`、下载的 PDF、`.venv\`、`dist\` 或浏览器缓存。公开分享时优先使用 GitHub 源码包，或使用上面的打包脚本生成干净目录。
