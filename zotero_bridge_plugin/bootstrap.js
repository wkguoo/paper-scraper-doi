var { Services } = ChromeUtils.importESModule(
  "resource://gre/modules/Services.sys.mjs",
);
var bridgeRootURI = "";
var bridgeMenus = new Map();

function install() {}

async function startup(data) {
  bridgeRootURI = data.rootURI || data.resourceURI.spec;
  Services.scriptloader.loadSubScriptWithOptions(
    bridgeRootURI + "content/bridge-runtime.js",
    { target: globalThis, charset: "UTF-8", ignoreCache: true },
  );
  await Zotero.PaperDownloadBridge.startup({ rootURI: bridgeRootURI });
}

function addMenu(window) {
  if (!window || bridgeMenus.has(window)) return;
  const document = window.document;
  const popup = document.getElementById("menu_ToolsPopup");
  if (!popup) return;

  const menu = document.createXULElement("menu");
  menu.setAttribute("label", "文献下载桥接");
  const items = document.createXULElement("menupopup");
  for (const [label, command] of [
    ["立即检查任务", "scanNow"],
    ["查看最近状态", "showStatus"],
    ["撤销最近批次新增", "undoLastBatch"],
  ]) {
    const item = document.createXULElement("menuitem");
    item.setAttribute("label", label);
    item.addEventListener("command", () => Zotero.PaperDownloadBridge[command]());
    items.appendChild(item);
  }
  menu.appendChild(items);
  popup.appendChild(menu);
  bridgeMenus.set(window, menu);
}

function onMainWindowLoad({ window }) {
  addMenu(window);
}

function onMainWindowUnload({ window }) {
  const menu = bridgeMenus.get(window);
  if (menu && menu.parentNode) menu.parentNode.removeChild(menu);
  bridgeMenus.delete(window);
}

async function shutdown(_data, reason) {
  if (reason !== APP_SHUTDOWN) await Zotero.PaperDownloadBridge?.shutdown();
  for (const window of Array.from(bridgeMenus.keys())) onMainWindowUnload({ window });
  delete Zotero.PaperDownloadBridge;
}

function uninstall() {}
