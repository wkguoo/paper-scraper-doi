var bridgeRootURI = "";
var bridgeMenuRegistrationID = null;
var bridgeRuntimeState = "stopped";
var bridgeRuntimeError = "";

function log(message) {
  Zotero.debug(`Paper Download Bridge: ${message}`);
}

function install({ version }) {
  log(`Installed ${version}`);
}

async function startup({ id, version, rootURI }, reason) {
  bridgeRootURI = rootURI;
  bridgeRuntimeState = "starting";
  bridgeRuntimeError = "";
  log(`Starting ${version}`);

  // Zotero 9 injects Services, IOUtils, and PathUtils into this plugin scope.
  // Load our Fluent resource into every current window and use the official
  // MenuManager API instead of injecting legacy XUL menu nodes directly.
  for (const window of Zotero.getMainWindows()) {
    onMainWindowLoad({ window });
  }
  try {
    registerToolsMenu(id);
    Services.scriptloader.loadSubScriptWithOptions(
      bridgeRootURI + "content/bridge-core.js",
      { target: globalThis, charset: "UTF-8", ignoreCache: true },
    );
    Services.scriptloader.loadSubScriptWithOptions(
      bridgeRootURI + "content/bridge-runtime.js",
      { target: globalThis, charset: "UTF-8", ignoreCache: true },
    );
    await Zotero.PaperDownloadBridge.startup({ rootURI: bridgeRootURI });
    bridgeRuntimeState = "ready";
    bridgeRuntimeError = "";
    log(`Ready ${version}`);
  } catch (error) {
    bridgeRuntimeState = "failed";
    bridgeRuntimeError = errorCode(error);
    log(`Startup failed: ${bridgeRuntimeError}`);
    Zotero.logError(error);
  }
}

function errorCode(error) {
  const value = String(error?.message || error?.name || error || "unknown");
  return value.replace(/[^A-Za-z0-9_.-]+/g, "_").slice(0, 120) || "unknown";
}

function setMenuLabel(label) {
  return (_event, context) => {
    const menuElem = context?.menuElem;
    if (menuElem && typeof menuElem.setAttribute === "function") {
      menuElem.setAttribute("label", label);
    }
  };
}

function registerToolsMenu(pluginID) {
  if (bridgeMenuRegistrationID) return;

  bridgeMenuRegistrationID = Zotero.MenuManager.registerMenu({
    menuID: "paper-download-bridge-tools-menu",
    pluginID,
    target: "main/menubar/tools",
    menus: [
      {
        menuType: "submenu",
        l10nID: "bridge-menu-label",
        onShowing: setMenuLabel("文献下载桥接"),
        menus: [
          {
            menuType: "menuitem",
            l10nID: "bridge-menu-scan",
            onShowing: setMenuLabel("立即检查任务"),
            onCommand: event => runMenuCommand("scanNow", event),
          },
          {
            menuType: "menuitem",
            l10nID: "bridge-menu-status",
            onShowing: setMenuLabel("查看最近状态"),
            onCommand: event => runMenuCommand("showStatus", event),
          },
          {
            menuType: "menuitem",
            l10nID: "bridge-menu-undo",
            onShowing: setMenuLabel("撤销最近批次新增"),
            onCommand: event => runMenuCommand("undoLastBatch", event),
          },
        ],
      },
    ],
  });

  if (!bridgeMenuRegistrationID) {
    bridgeRuntimeState = "failed";
    throw new Error("bridge_menu_registration_failed");
  }
}

function runMenuCommand(command, event) {
  const window = event?.target?.ownerGlobal || Zotero.getMainWindow();
  if (bridgeRuntimeState === "starting") {
    Services.prompt.alert(
      window,
      "文献下载桥接",
      "插件运行时仍在启动：bridge_runtime_starting",
    );
    return;
  }

  const handler = Zotero.PaperDownloadBridge?.[command];
  if (bridgeRuntimeState !== "ready" || typeof handler !== "function") {
    Services.prompt.alert(
      window,
      "文献下载桥接",
      `插件运行时启动失败：bridge_runtime_startup_failed${bridgeRuntimeError ? `:${bridgeRuntimeError}` : ""}`,
    );
    return;
  }
  Promise.resolve(handler()).catch(error => Zotero.logError(error));
}

function onMainWindowLoad({ window }) {
  try {
    window.MozXULElement.insertFTLIfNeeded("bridge.ftl");
  } catch (error) {
    log(`Localization failed: ${errorCode(error)}`);
    Zotero.logError(error);
  }
}

function onMainWindowUnload({ window }) {
  // The document and its inserted localization link are destroyed with the
  // window. Do not retain any window reference here.
}

function removeLocalizationFromWindow(window) {
  window.document.querySelector('[href="bridge.ftl"]')?.remove();
}

async function shutdown(_data, reason) {
  log("Shutting down");

  if (bridgeMenuRegistrationID) {
    Zotero.MenuManager.unregisterMenu(bridgeMenuRegistrationID);
    bridgeMenuRegistrationID = null;
  }
  for (const window of Zotero.getMainWindows()) {
    removeLocalizationFromWindow(window);
  }

  if (
    reason !== APP_SHUTDOWN &&
    typeof Zotero.PaperDownloadBridge?.shutdown === "function"
  ) {
    await Zotero.PaperDownloadBridge.shutdown();
  }
  delete Zotero.PaperDownloadBridge;
  bridgeRuntimeState = "stopped";
  bridgeRuntimeError = "";
  bridgeRootURI = "";
}

function uninstall({ version }) {
  log(`Uninstalled ${version}`);
}
