const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");

function makeWindow() {
  const insertedFTL = [];
  const window = {
    MozXULElement: {
      insertFTLIfNeeded(name) {
        insertedFTL.push(name);
      },
    },
    document: {
      querySelector() {
        return null;
      },
    },
  };
  return { window, insertedFTL };
}

test("startup registers the official Tools menu before runtime I/O completes", () => {
  const source = fs.readFileSync(path.join(root, "bootstrap.js"), "utf8");
  const { window, insertedFTL } = makeWindow();
  const loadedScripts = [];
  const registeredMenus = [];
  let context;
  let runtimeStartupCalls = 0;
  const pendingRuntime = new Promise(() => {});
  const Services = {
    scriptloader: {
        loadSubScriptWithOptions(url, options) {
        loadedScripts.push(url);
        assert.equal(typeof options.target.Zotero, "object");
        assert.equal(typeof options.target.Services, "object");
        assert.equal(options.charset, "UTF-8");
        assert.equal(options.ignoreCache, true);
        if (url.endsWith("content/bridge-runtime.js")) {
          context.Zotero.PaperDownloadBridge = {
            startup() {
              runtimeStartupCalls += 1;
              return pendingRuntime;
            },
          };
        }
      },
    },
    prompt: { alert() {} },
  };

  context = vm.createContext({
    APP_SHUTDOWN: 2,
    Services,
    IOUtils: {},
    PathUtils: {},
    Zotero: {
      getMainWindows() {
        return [window];
      },
      logError(error) { throw error; },
      debug() {},
      MenuManager: {
        registerMenu(options) {
          registeredMenus.push(options);
          return "registered-tools-menu";
        },
        unregisterMenu() {},
      },
    },
  });
  vm.runInContext(source, context, { filename: "bootstrap.js" });

  context.startup({
    id: "paper-download-bridge@wkguoo.local",
    version: "0.1.5",
    rootURI: "resource://paper-download-bridge/",
  }, 5);

  assert.deepEqual(insertedFTL, ["bridge.ftl"]);
  assert.equal(registeredMenus.length, 1);
  assert.equal(registeredMenus[0].target, "main/menubar/tools");
  assert.equal(registeredMenus[0].pluginID, "paper-download-bridge@wkguoo.local");
  assert.equal(registeredMenus[0].menus[0].menuType, "submenu");
  assert.equal(registeredMenus[0].menus[0].l10nID, "bridge-menu-label");
  const topMenuAttributes = new Map();
  registeredMenus[0].menus[0].onShowing(null, {
    menuElem: {
      setAttribute(name, value) {
        topMenuAttributes.set(name, value);
      },
    },
  });
  assert.equal(topMenuAttributes.get("label"), "文献下载桥接");
  const childMenuAttributes = new Map();
  registeredMenus[0].menus[0].menus[0].onShowing(null, {
    menuElem: {
      setAttribute(name, value) {
        childMenuAttributes.set(name, value);
      },
    },
  });
  assert.equal(childMenuAttributes.get("label"), "立即检查任务");
  assert.equal(context.bridgeRuntimeState, "starting");
  assert.equal(runtimeStartupCalls, 1);
  assert.deepEqual(loadedScripts, [
    "resource://paper-download-bridge/content/bridge-core.js",
    "resource://paper-download-bridge/content/bridge-runtime.js",
  ]);
});
