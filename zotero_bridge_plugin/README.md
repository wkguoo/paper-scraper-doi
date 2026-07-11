# Zotero 9 文献下载桥接插件

这个插件是 `paper-scraper-doi` 的本地回退端：项目先处理合法开放获取或用户已有机构权限可访问的 PDF，只有失败项才进入 Zotero。插件会在完整批次到齐后弹出一次确认，随后查重、按 DOI 导入缺失条目、建立批次集合，并调用 Zotero 自带的“可用 PDF”能力。项目最后复核附件并汇总最终 PDF。

## 兼容范围

- 仅支持 Zotero 9.0.x；当前源码按本机 Zotero 9.0.6 API 静态核对。
- 只使用本地 `%LOCALAPPDATA%\PaperScraperDOI\zotero-bridge\v1` 队列。
- 不直接读取 `zotero.sqlite`，不启动 Edge，不自行实现网络下载或 CAPTCHA 绕过。
- 真实 PDF 是否可得取决于 Zotero 当前登录、机构授权、出版商限制和合法可访问来源。

## 先运行离线测试

输入：插件源码和内存假 Zotero；输出：测试结果，不生成 XPI，不修改真实 Zotero。

```powershell
node --test .\zotero_bridge_plugin\tests\*.test.cjs
```

成功标准：所有测试显示 `pass`，`fail` 为 0。

## 手工构建（需明确批准）

下面的命令会创建 XPI，属于需明确批准的打包步骤。本次不会执行该命令，也不会自动安装插件：

```powershell
powershell -ExecutionPolicy Bypass -File .\build_zotero_bridge_xpi.ps1 -OutputDirectory .\dist
```

输入：`manifest.json`、`bootstrap.js`、`content/`、`locale/` 四项白名单源码。

输出：`dist\zotero-paper-download-bridge-0.1.0.xpi`。脚本不会包含 `tests/`、`package.json`、日志、桥接队列、Cookie 或环境文件；不会调用现有 Windows UI 打包脚本；不会自动安装到 Zotero。目标已存在时默认停止，只有显式添加 `-Force` 才允许替换。

成功标准：命令显示 `Validated Zotero XPI created`，且压缩包根目录含 `manifest.json` 和 `bootstrap.js`。建议先安装到独立 Zotero 测试配置，不要直接使用主文库。

## 最终批处理流程

1. 项目侧先运行 `paper_batch.py start`，必要时只运行一次 `resume`。
2. 对剩余失败项运行 `paper_batch.py zotero --run-dir "<批次目录>"`，项目把严格 JSON 作业放入本地队列。
3. Zotero 只在全部分块到齐后确认一次。取消时不写 Zotero；确认后逐项保存检查点。
4. 插件完成后，再运行同一条 `paper_batch.py zotero` 命令。项目复核 PDF 文件并更新最终清单与 `pdfs\`。

插件不会修改已有附件。菜单“查看最近状态”显示等待、运行、完成或撤销状态；“撤销最近批次新增”需要第二次确认，并且只处理账本记录且身份仍匹配的新条目、新附件和集合成员关系。

## 注意事项

- 不要把 Cookie、密码、机构令牌、下载 PDF 或真实桥接队列放入源码或 XPI。
- 不要手工编辑 `plugin-state.json`、作业 JSON、进度 JSON 或结果 JSON；身份或摘要不一致会安全停止。
- 遇到 CAPTCHA、登录失效或出版商拒绝时应保留失败状态，由用户在授权环境中处理，不得绕过访问控制。
- 当前源码完成的是离线实现与测试。只有在独立 Zotero 测试配置通过人工验收后，才应考虑安装到主配置。
