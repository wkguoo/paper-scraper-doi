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
});
