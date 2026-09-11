# Paper Scraper DOI

中文首页 | [English guide](docs/user-guide/en.md) | [完整中文指南](docs/user-guide/zh.md)

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![License](https://img.shields.io/github/license/wkguoo/paper-scraper-doi)
![Tests](https://github.com/wkguoo/paper-scraper-doi/actions/workflows/tests.yml/badge.svg)
![Release](https://img.shields.io/github/v/release/wkguoo/paper-scraper-doi?display_name=tag)

面向 Windows 科研用户的论文批量下载助手：把 DOI、Excel、Markdown 或复制的文献列表整理成可复核任务，统一衔接公开 OA、授权机构访问和 Zotero 回退。

> **默认入口只有一个：**新任务使用 `paper_batch.py`，或双击 `start_paper_scraper_ui.bat` 后进入 **统一批次（推荐）**。

[下载最新版本](https://github.com/wkguoo/paper-scraper-doi/releases/latest) · [Windows UI 说明](docs/user-guide/windows-ui.md) · [Zotero 桥接指南](docs/zotero_bridge_beginner_guide.md)

## 它能做什么

- 读取 TXT、Markdown、CSV、Excel 或直接粘贴的 DOI/题名列表。
- 预检 DOI、去重并补全文献元数据，把不确定记录留给人工复核。
- 在用户已有权限范围内尝试 OA、出版社/机构访问和有限 OA 恢复。
- 将仍失败的 DOI 汇总到回退清单；Codex 优先用官方 Zotero 插件复用已有本地 PDF，自建桥接仅在手动补下载或旧批次续作时使用。
- 按 `年份-第一作者姓-题名.pdf` 发布 PDF，并生成下载清单和审计报告。

本项目**不提供**数据库、学校或出版社访问权限，不代替用户输入账号密码，也不绕过 CAPTCHA 或访问控制。

## 推荐入口

| 场景 | 使用方式 |
| --- | --- |
| 图形界面 | 双击 `start_paper_scraper_ui.bat` |
| 命令行批量任务 | `paper_batch.py start` |
| 自然语言 / Codex | `$paper-download` |

兼容脚本 `sd_scraper.py`、`sd_institutional_skill.py`、`paper_skill.py` 和 `institutional_paper_skill.py` 仅用于旧流程或内部适配，不是新任务的默认入口。

## 快速开始

在 PowerShell 中进入仓库目录：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

启动图形界面：

```powershell
.\start_paper_scraper_ui.bat
```

或运行统一批次命令：

```powershell
.\.venv\Scripts\python.exe paper_batch.py start `
  --input "papers.xlsx" `
  --out "results" `
  --email "you@example.com"
```

输入优先使用“每行一个 DOI”的 TXT，或包含 `doi` 列的 CSV/XLSX。
如果输入来自 AI 推荐或混杂参考文献文本，先让 `$paper-download` 使用 `--beginner --preflight` 生成复核清单，再开始正式下载。

## 默认流程

```text
输入清单
  → DOI 预检与去重
  → OA / 授权机构访问
  → 有限 OA 恢复
  → 剩余失败清单（Codex 官方 Zotero 插件查库；自建桥接可选）
  → 结果/下载清单.csv + 结果/pdf/
```

原始输入和实验/研究资料不会被覆盖。运行缓存、报告和交付文件保存在新建的批次目录中。

## 用户交付目录

```text
结果/
├── <原始输入文件>
├── 下载清单.csv
├── pdf/
├── md/
└── 补充材料/        # 仅实际下载到补充材料时创建
```

内部的 `pdfs/`、`reports/` 和 `working/` 用于缓存、续跑和审计；日常查看只需进入 `结果/`。

## 文档导航

- [完整中文指南](docs/user-guide/zh.md)
- [Complete English guide](docs/user-guide/en.md)
- [Windows UI 使用说明](docs/user-guide/windows-ui.md)
- [Zotero 9 本地桥接新手指南](docs/zotero_bridge_beginner_guide.md)
- [人工 QA 清单](docs/development/manual-qa.md)
- [安全策略](.github/SECURITY.md)

<details>
<summary>开发与测试</summary>

离线检查：

```powershell
.\.venv\Scripts\python.exe -m compileall paper_batch.py preflight_doi_metadata.py paper_scraper_ui.py sd_scraper.py windows_paths.py sd_institutional_skill.py institutional_paper_skill.py paper_skill.py paper_automation
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

真实机构登录、CAPTCHA、PDF 与补充材料下载只在[人工 QA 清单](docs/development/manual-qa.md)中验证，不进入默认离线测试。

</details>

## 安全与许可

不要提交 Cookie、密码、下载的 PDF、结果表、浏览器缓存、`.venv/` 或 `dist/`。发现安全问题时请先阅读[安全策略](.github/SECURITY.md)。

项目采用 [MIT License](LICENSE)，版权归 `wkguoo` 所有；第三方代码许可见 [THIRD_PARTY_NOTICES.md](docs/legal/THIRD_PARTY_NOTICES.md)。
