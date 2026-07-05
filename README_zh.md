# 中文说明入口

本项目的 GitHub 首页说明已经改为中文主版，请优先阅读 [README.md](README.md)。

`README_zh.md` 保留为兼容入口，避免旧链接失效。为避免两份中文说明长期维护后出现命令、流程或安全提醒不一致，完整的新手安装和使用说明统一放在 `README.md`。

## 推荐阅读顺序

1. [README.md](README.md)：新手主说明，包含安装依赖、安装 Codex Skills、复制即用示例、研究生交付入口、输出文件说明和常见问题。
2. [如何导出机构Cookie.md](如何导出机构Cookie.md)：ScienceDirect 机构权限下载前，如何导出并安全使用 `cookies.json`。
3. [WINDOWS_UI_README.md](WINDOWS_UI_README.md)：只想使用 Windows 图形界面时阅读。
4. [docs/sciencedirect_skill_beginner_guide.md](docs/sciencedirect_skill_beginner_guide.md)：需要给学生或课题组成员看的 ScienceDirect Skill 详细教程。
5. [MANUAL_QA.md](MANUAL_QA.md)：需要真实机构登录、PDF 下载、CAPTCHA 或补充材料下载检查时阅读。

## 最短开始方式

在 PowerShell 中进入仓库目录：

```powershell
cd "<仓库路径>"
```

安装 Python 依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

预检查 Codex Skills 安装位置：

```powershell
powershell -ExecutionPolicy Bypass -File .\install_codex_skills.ps1 -DryRun
```

正式安装或刷新 Codex Skills：

```powershell
powershell -ExecutionPolicy Bypass -File .\install_codex_skills.ps1
```

重启 Codex 后，优先使用统一入口：

```text
Use $paper-download to preflight these paper recommendations with --beginner --preflight.

<在这里粘贴 DOI、题名或论文推荐列表>
```

ScienceDirect 机构权限下载、合法 OA 下载、图形界面和命令行示例都以 [README.md](README.md) 为准。
