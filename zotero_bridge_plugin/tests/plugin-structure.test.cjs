const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");

test("manifest targets only Zotero 9.0.x", () => {
  const manifest = JSON.parse(
    fs.readFileSync(path.join(root, "manifest.json"), "utf8"),
  );
  assert.equal(manifest.manifest_version, 2);
  assert.equal(manifest.applications.zotero.id, "paper-download-bridge@wkguoo.local");
  assert.equal(
    manifest.applications.zotero.update_url,
    "https://example.invalid/zotero-paper-download-bridge/updates.json",
  );
  assert.equal(manifest.applications.zotero.strict_min_version, "9.0");
  assert.equal(manifest.applications.zotero.strict_max_version, "9.0.*");
});

test("bootstrap exports lifecycle hooks and has no network primitive", () => {
  const source = fs.readFileSync(path.join(root, "bootstrap.js"), "utf8");
  for (const hook of [
    "install",
    "startup",
    "shutdown",
    "uninstall",
    "onMainWindowLoad",
    "onMainWindowUnload",
  ]) {
    assert.match(source, new RegExp(`function ${hook}\\b`));
  }
  for (const forbidden of ["fetch(", "XMLHttpRequest", "ServerSocket", "WebSocket"]) {
    assert.equal(source.includes(forbidden), false);
  }
  assert.match(source, /content\/bridge-runtime\.js/);
  assert.match(
    source,
    /async function startup\(\{ id, version, rootURI \}, reason\)/,
  );
  assert.doesNotMatch(source, /Services\.sys\.mjs/);
  assert.doesNotMatch(source, /ChromeUtils\.importESModule/);
  assert.doesNotMatch(source, /Services\.wm\.getEnumerator/);
  assert.match(source, /Zotero\.MenuManager\.registerMenu/);
  assert.match(source, /target: "main\/menubar\/tools"/);
  assert.match(source, /Services\.scriptloader\.loadSubScriptWithOptions/);
  assert.match(source, /target: globalThis/);
  assert.match(source, /menuType: "submenu"/);
  assert.match(source, /l10nID: "bridge-menu-label"/);
  assert.match(source, /Zotero\.getMainWindows\(\)/);
  assert.match(source, /function onMainWindowLoad\(\{ window \}\)/);
  assert.match(
    source,
    /window\.MozXULElement\.insertFTLIfNeeded\("bridge\.ftl"\)/,
  );
  assert.match(source, /bridge_runtime_starting/);
  assert.match(source, /bridge_runtime_startup_failed/);
  assert.ok(
    source.indexOf("registerToolsMenu(id)")
      < source.indexOf('bridgeRootURI + "content/bridge-runtime.js"'),
  );
});

test("menu localization uses the label attributes required by MenuManager", () => {
  const source = fs.readFileSync(
    path.join(root, "locale", "zh-CN", "bridge.ftl"),
    "utf8",
  );
  for (const id of [
    "bridge-menu-label",
    "bridge-menu-scan",
    "bridge-menu-status",
    "bridge-menu-undo",
  ]) {
    assert.match(source, new RegExp(`${id}\\s*=\\s*\\r?\\n\\s+\\.label\\s*=`));
  }
});
