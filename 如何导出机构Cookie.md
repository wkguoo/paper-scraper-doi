# 如何导出机构 Cookie 以使用学校账号下载 ScienceDirect

这份说明写给第一次使用本项目的用户。`cookies.json` 的作用是让脚本复用你已经登录 ScienceDirect 的机构访问状态，从而访问你所在学校或机构已经订阅的内容。

## 先确认你是否需要 Cookie

| 场景 | 是否需要 `cookies.json` |
| --- | --- |
| 使用 ScienceDirect/Elsevier 机构权限下载 PDF | 推荐使用 |
| 使用 Windows UI 的 `DOI 批量下载` | 推荐使用 |
| 使用 `sd_scraper.py -m doi_batch --download-pdfs` | 推荐使用 |
| 使用 Codex Skill 并让脚本弹出浏览器登录 | 不一定需要，脚本也可以通过浏览器登录缓存凭据 |
| 使用 `legal-oa-paper-download` 或 `paper_skill.py` OA 流程 | 不需要，也不应该使用 |

Cookie 不是账号密码，但它属于登录凭据。请按账号密码的安全级别处理。

## 步骤一：在浏览器中通过机构登录

1. 打开 Chrome、Edge 或 Firefox。
2. 进入 [ScienceDirect](https://www.sciencedirect.com)。
3. 点击右上角 `Sign in`。
4. 选择 `Access through your institution`。
5. 搜索你的学校或机构名称，按页面提示跳转。
6. 在学校统一身份认证、CARSI、VPN 或图书馆入口中完成登录。
7. 回到 ScienceDirect 后，确认页面显示机构名称或可以打开一篇你有权限的全文页面。

不要把学校账号、密码、验证码发给 Codex、脚本或任何人。

## 步骤二：安装 Cookie Editor 插件

推荐使用浏览器插件 `Cookie Editor`：

- Chrome / Edge：在浏览器扩展商店搜索 `Cookie Editor`。
- Firefox：在 Firefox Add-ons 里搜索 `Cookie Editor`。

安装后，浏览器工具栏通常会出现 Cookie Editor 图标。

## 步骤三：导出 `cookies.json`

1. 保持浏览器停留在 `https://www.sciencedirect.com` 页面。
2. 点击浏览器工具栏里的 Cookie Editor 图标。
3. 点击 `Export`。
4. 选择 `Export as JSON`。
5. 新建一个文本文件，把导出的 JSON 内容粘贴进去。
6. 文件名保存为 `cookies.json`。

推荐保存位置：

```text
<仓库路径>\cookies.json
```

也可以保存到其他本机目录，例如：

```text
D:\Private\ScienceDirect\cookies.json
```

无论放在哪里，都不要上传到 GitHub、网盘共享目录、群文件或论文附件中。

## 在 Windows UI 中使用 Cookie

1. 双击 `start_paper_scraper_ui.bat`。
2. 打开默认的 `DOI 批量下载` 页面。
3. 在 `2 权限与输出` 区域找到 `Cookie JSON 文件`。
4. 点击 `选择`，选中刚导出的 `cookies.json`。
5. 保持 `检索后下载 PDF` 勾选。
6. 如果只需要正文 PDF，可以取消 `同时下载补充材料`。
7. 使用 `cookies.json` 时，不需要再勾选 `从本机 Chrome 读取 Cookie`，也不需要勾选 `先弹出 Chrome 手动登录`。

如果下载失败，先查看输出目录中的 `pdf_download_report.csv` 和 `run_summary.txt`，不要反复大批量重试。

## 在命令行中使用 Cookie

先进入仓库目录：

```powershell
cd "<仓库路径>"
```

ScienceDirect DOI 批量下载示例：

```powershell
.\.venv\Scripts\python.exe sd_scraper.py -m doi_batch --input "papers.csv" --doi-column "doi" --cookies "cookies.json" --download-pdfs
```

如果 `cookies.json` 不在仓库目录，请写完整路径：

```powershell
.\.venv\Scripts\python.exe sd_scraper.py -m doi_batch --input "papers.csv" --doi-column "doi" --cookies "D:\Private\ScienceDirect\cookies.json" --download-pdfs
```

如果只下载正文 PDF，不下载补充材料：

```powershell
.\.venv\Scripts\python.exe sd_scraper.py -m doi_batch --input "papers.csv" --doi-column "doi" --cookies "cookies.json" --download-pdfs --no-download-supplements
```

## 在 Codex Skill 中怎么说明

如果已经安装了本项目的 Codex Skills，通常可以直接让 `paper-download` 或 `sciencedirect-doi-download` 处理 ScienceDirect 下载。你不需要把 Cookie 内容粘贴给 Codex，只需要说明本机有 `cookies.json` 文件或让脚本使用浏览器登录。

推荐写法：

```text
Use $paper-download to download these ScienceDirect papers.
Use the local cookies.json file if needed.
Save results to D:\Literature\ScienceDirect.

DOI: 10.1016/j.actamat.2016.08.081
```

不要在聊天里粘贴 `cookies.json` 的内容。

## 常见问题

| 问题 | 处理方法 |
| --- | --- |
| 报 403、无权限或下载失败 | Cookie 可能过期，或学校没有订阅该论文。重新登录 ScienceDirect 后再导出 Cookie，并先用 1 篇论文测试。 |
| Cookie Editor 导出的不是 JSON | 导出时确认选择 `Export as JSON`，不要选择 Netscape 或纯文本格式。 |
| UI 中已经选了 `cookies.json`，还要不要读 Chrome Cookie | 不需要。优先使用导出的 `cookies.json`，减少浏览器读取失败的情况。 |
| 换电脑后还能用原来的 Cookie 吗 | 不建议。请在当前电脑和当前浏览器重新登录并导出。 |
| OA 下载要不要 Cookie | 不需要。`paper_skill.py` 和 `legal-oa-paper-download` 不使用机构 Cookie。 |

## 安全清单

请务必遵守：

- 不要提交 `cookies.json`。
- 不要提交 `results\_auth\sciencedirect_cookies.json`。
- 不要提交下载的 PDF、补充材料、结果表或日志。
- 不要把 Cookie 内容粘贴到 Codex、聊天软件、邮件或 issue 中。
- 不要分享 `%TEMP%\chrome_dbg_profile`。

如果在公共电脑或临时测试机器上使用过机构登录，可以清理本机凭据状态：

```powershell
Remove-Item -Recurse -Force (Join-Path $env:TEMP "chrome_dbg_profile")
Remove-Item -Force ".\results\_auth\sciencedirect_cookies.json"
```
