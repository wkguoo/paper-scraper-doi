# Zotero 9 Bridge Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Zotero 9.0.6 bootstrapped plugin that consumes strict local queue jobs, asks for one confirmation per user batch, safely resolves/imports items, invokes Zotero's available-PDF action, and publishes resumable results.

**Architecture:** Pure contract and matching logic lives in `content/bridge-core.js` and runs unchanged under Zotero and Node's built-in test runner. `content/bridge-runtime.js` owns local file I/O, one-confirmation grouping, checkpoints, Zotero API adapters, and result publication. `bootstrap.js` only loads/unloads the runtime and registers a small Tools menu; it contains no domain logic.

**Tech Stack:** Zotero 9 bootstrapped WebExtension, JavaScript, Zotero JavaScript API, Mozilla `IOUtils`/`PathUtils`/`Services`, Node.js built-in `node:test` for pure tests; no npm runtime dependencies.

## Global Constraints

- Target only Zotero `9.0` through `9.0.*`; manifest version 2.
- Read/write only `%LOCALAPPDATA%\PaperScraperDOI\zotero-bridge\v1` queue directories.
- Never open a network listener or accept arbitrary output paths, code, commands, or URLs.
- Validate exact schema and SHA-256 identity before showing a confirmation or writing the library.
- Show one native confirmation per `run_id`, including library ID/name, total item count, and collection name, only after every declared one-based chunk from `1` through `chunk_count` is present.
- Cancellation performs zero Zotero writes and produces `user_cancelled` rows.
- DOI matching is exact after normalization; title matching requires normalized title plus year or first author and rejects ambiguity.
- Use Zotero data objects/transactions; never read or write `zotero.sqlite` directly.
- Existing items and attachments are never deleted, renamed, moved, or overwritten.
- Existing valid local PDF attachments are returned without a network lookup.
- Call `Zotero.Attachments.addAvailablePDF` at most once per unresolved item per job.
- Never bypass login/CAPTCHA or use shadow sources.
- Checkpoint each item and resume by `job_id` without duplicate import, collection assignment, or PDF lookup.
- Do not build or install an XPI until the explicit integration-plan approval gate.
- Append every project modification to `CHANGELOG.md`.

---

## File Structure

- Create `zotero_bridge_plugin/manifest.json`: Zotero compatibility and plugin identity.
- Create `zotero_bridge_plugin/bootstrap.js`: lifecycle and menu registration.
- Create `zotero_bridge_plugin/content/bridge-core.js`: strict schema, normalization, matching, result-row helpers.
- Create `zotero_bridge_plugin/content/bridge-runtime.js`: queue, confirmation, Zotero adapters, processing, checkpoints, undo ledger.
- Create `zotero_bridge_plugin/locale/zh-CN/bridge.ftl`: Chinese labels.
- Create `zotero_bridge_plugin/tests/bridge-core.test.cjs`: pure Node tests.
- Create `zotero_bridge_plugin/tests/bridge-runtime.test.cjs`: fake Zotero/filesystem behavior tests.
- Create `zotero_bridge_plugin/package.json`: test scripts only, no dependencies.
- Create `zotero_bridge_plugin/README.md`: source test and installation boundaries.
- Create `build_zotero_bridge_xpi.ps1`: deterministic source allowlist and XPI validation; creation is manual.
- Modify `CHANGELOG.md`: append task evidence.

### Task 1: Create Zotero 9 plugin skeleton and lifecycle

**Files:**
- Create: `zotero_bridge_plugin/manifest.json`
- Create: `zotero_bridge_plugin/bootstrap.js`
- Create: `zotero_bridge_plugin/content/bridge-runtime.js`
- Create: `zotero_bridge_plugin/locale/zh-CN/bridge.ftl`
- Create: `zotero_bridge_plugin/tests/plugin-structure.test.cjs`
- Create: `zotero_bridge_plugin/package.json`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces global `Zotero.PaperDownloadBridge` with `startup()`, `shutdown()`, `scanNow()`, `showStatus()`, and `undoLastBatch()`.
- Later tasks replace the initial runtime methods without changing lifecycle names.

- [ ] **Step 1: Write failing structure tests**

Create `zotero_bridge_plugin/tests/plugin-structure.test.cjs`:

```javascript
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");

test("manifest targets only Zotero 9.0.x", () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(root, "manifest.json"), "utf8"));
  assert.equal(manifest.manifest_version, 2);
  assert.equal(manifest.applications.zotero.id, "paper-download-bridge@wkguoo.local");
  assert.equal(manifest.applications.zotero.strict_min_version, "9.0");
  assert.equal(manifest.applications.zotero.strict_max_version, "9.0.*");
});

test("bootstrap exports all Zotero lifecycle hooks and no network primitive", () => {
  const source = fs.readFileSync(path.join(root, "bootstrap.js"), "utf8");
  for (const hook of ["install", "startup", "shutdown", "uninstall", "onMainWindowLoad", "onMainWindowUnload"]) {
    assert.match(source, new RegExp(`function ${hook}\\b`));
  }
  for (const forbidden of ["fetch(", "XMLHttpRequest", "ServerSocket", "WebSocket"]) {
    assert.equal(source.includes(forbidden), false);
  }
});
```

Create `zotero_bridge_plugin/package.json`:

```json
{
  "name": "zotero-paper-download-bridge",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "test": "node --test tests/*.test.cjs"
  }
}
```

- [ ] **Step 2: Run structure tests and verify RED**

```powershell
node --test zotero_bridge_plugin/tests/plugin-structure.test.cjs
```

Expected: failure because manifest/bootstrap do not exist.

- [ ] **Step 3: Add manifest, bootstrap, locale, and minimal runtime**

Create `manifest.json`:

```json
{
  "manifest_version": 2,
  "name": "Paper Download Bridge",
  "version": "0.1.0",
  "description": "One-confirmation local bridge between paper-scraper-doi and Zotero 9.",
  "author": "wkguoo",
  "applications": {
    "zotero": {
      "id": "paper-download-bridge@wkguoo.local",
      "strict_min_version": "9.0",
      "strict_max_version": "9.0.*"
    }
  }
}
```

Create `bootstrap.js` with lifecycle-safe loading and a Tools menu:

```javascript
var { Services } = ChromeUtils.importESModule("resource://gre/modules/Services.sys.mjs");
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

function onMainWindowLoad({ window }) { addMenu(window); }
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
```

Create `content/bridge-runtime.js`:

```javascript
Zotero.PaperDownloadBridge = {
  timer: null,
  async startup() {
    if (this.timer) return;
    this.timer = setInterval(() => this.scanNow().catch(error => Zotero.logError(error)), 1000);
  },
  async shutdown() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  },
  async scanNow() {},
  showStatus() {
    Services.prompt.alert(null, "文献下载桥接", "插件已启动，尚无已处理批次。");
  },
  async undoLastBatch() {
    Services.prompt.alert(null, "文献下载桥接", "当前没有可撤销的批次。");
  },
};
```

Create `locale/zh-CN/bridge.ftl` with the three menu labels and confirmation text, even though bootstrap initially uses fixed Chinese strings; Task 5 switches runtime dialogs to the locale bundle.

- [ ] **Step 4: Run structure tests**

```powershell
node --test zotero_bridge_plugin/tests/plugin-structure.test.cjs
```

Expected: all tests pass.

- [ ] **Step 5: Append CHANGELOG and commit**

```powershell
git add zotero_bridge_plugin CHANGELOG.md
git commit -m "Scaffold Zotero 9 bridge plugin"
```

### Task 2: Implement pure schema, normalization, matching, and result logic

**Files:**
- Create: `zotero_bridge_plugin/content/bridge-core.js`
- Create: `zotero_bridge_plugin/tests/bridge-core.test.cjs`
- Modify: `zotero_bridge_plugin/bootstrap.js`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces `ZoteroPaperBridgeCore.validateRequest()`, `normalizeDOI()`, `normalizeTitle()`, `firstCreatorKey()`, `chooseCandidate()`, `successRow()`, and `failureRow()`.
- Consumed by runtime Tasks 3-5.

- [ ] **Step 1: Write failing pure tests**

Create `tests/bridge-core.test.cjs` with Node tests for:

```javascript
const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../content/bridge-core.js");

function request() {
  return {
    schema_version: 1,
    job_id: "11111111-1111-4111-8111-111111111111",
    payload_sha256: "a".repeat(64),
    created_at: "2026-07-11T09:00:00Z",
    expires_at: "2026-07-12T09:00:00Z",
    run_id: "paper_batch_20260711_090000",
    library_id: 1,
    chunk_index: 1,
    chunk_count: 1,
    collection_name: "Codex下载回退_20260711_090000",
    items: [{ task_id: "paper-0001", doi: "https://doi.org/10.1000/ABC", title: "A—B", authors: "Smith, J.", year: "2025" }],
  };
}

test("normalizes DOI and Unicode title deterministically", () => {
  assert.equal(core.normalizeDOI(" DOI: https://doi.org/10.1000/ABC "), "10.1000/abc");
  assert.equal(core.normalizeTitle("Ａ—B: Test"), "abtest");
});

test("rejects unknown fields, duplicates, invalid ids, and expired jobs", async () => {
  const cases = [];
  const unknown = request(); unknown.extra = true; cases.push(unknown);
  const duplicate = request(); duplicate.items.push({ ...duplicate.items[0] }); cases.push(duplicate);
  const invalidId = request(); invalidId.job_id = "../bad"; cases.push(invalidId);
  for (const value of cases) assert.throws(() => core.validateRequest(value, new Date("2026-07-11T10:00:00Z")));
  assert.throws(() => core.validateRequest(request(), new Date("2026-07-13T10:00:00Z")), /job_expired/);
});

test("title match requires year or first author and rejects ambiguity", () => {
  const wanted = { title: "Example Paper", authors: "Smith, J.", year: "2025" };
  assert.equal(core.chooseCandidate(wanted, [{ id: 1, title: "Example Paper", firstCreator: "Smith", year: "2025" }]).id, 1);
  assert.equal(core.chooseCandidate(wanted, [{ id: 2, title: "Example Paper", firstCreator: "Jones", year: "2024" }]), null);
  assert.throws(() => core.chooseCandidate(wanted, [
    { id: 1, title: "Example Paper", firstCreator: "Smith", year: "2025" },
    { id: 2, title: "Example Paper", firstCreator: "Smith", year: "2025" },
  ]), /metadata_uncertain/);
});

test("result helpers emit exactly five strings", () => {
  assert.deepEqual(Object.keys(core.successRow("paper-0001", 304, "C:\\a.pdf", "existing_pdf")), [
    "task_id", "zotero_item_id", "attachment_path", "status", "reason",
  ]);
  assert.deepEqual(core.failureRow("paper-0001", "no_pdf", "no_available_pdf"), {
    task_id: "paper-0001", zotero_item_id: "", attachment_path: "", status: "no_pdf", reason: "no_available_pdf",
  });
});
```

- [ ] **Step 2: Run core tests and verify RED**

```powershell
node --test zotero_bridge_plugin/tests/bridge-core.test.cjs
```

Expected: module-not-found failure.

- [ ] **Step 3: Implement `bridge-core.js` as a UMD-style pure module**

Implement a single IIFE that returns the named functions and ends with:

```javascript
const api = factory();
if (typeof module !== "undefined" && module.exports) module.exports = api;
else globalThis.ZoteroPaperBridgeCore = api;
```

Inside the factory:

- exact top-level fields: `schema_version,job_id,payload_sha256,created_at,expires_at,run_id,library_id,collection_name,chunk_index,chunk_count,items`;
- exact item fields: `task_id,doi,title,authors,year`;
- UUID-v4 regex identical to the Python contract;
- 100-item maximum and 4096-character string maximum;
- `chunk_index` and `chunk_count` are positive integers with `chunk_index <= chunk_count`; all jobs in a confirmable `run_id` must agree on `chunk_count`, library, collection name, creation/expiry instants, and contain exactly one of every chunk index;
- Unicode NFKC plus case folding through `toLocaleLowerCase("und")`;
- title normalization removes every Unicode whitespace, punctuation, and symbol with `/[\p{White_Space}\p{P}\p{S}]/gu`;
- DOI normalization removes `doi:` and `https://doi.org/` prefixes;
- `chooseCandidate()` returns one exact candidate, `null`, or throws `metadata_uncertain`;
- result helpers stringify numeric IDs and emit no extra keys.

Load `bridge-core.js` before runtime from `bootstrap.js` using `Services.scriptloader.loadSubScriptWithOptions()`.

- [ ] **Step 4: Run tests and a forbidden-primitives scan**

```powershell
node --test zotero_bridge_plugin/tests/bridge-core.test.cjs
rg -n "eval\(|Function\(|fetch\(|XMLHttpRequest|WebSocket|child_process|sqlite" zotero_bridge_plugin/content/bridge-core.js
```

Expected: tests pass; scan has no matches.

- [ ] **Step 5: Append CHANGELOG and commit**

```powershell
git add zotero_bridge_plugin/content/bridge-core.js zotero_bridge_plugin/tests/bridge-core.test.cjs zotero_bridge_plugin/bootstrap.js CHANGELOG.md
git commit -m "Add Zotero bridge contract core"
```

### Task 3: Implement file queue, grouping, and one confirmation

**Files:**
- Modify: `zotero_bridge_plugin/content/bridge-runtime.js`
- Create: `zotero_bridge_plugin/tests/bridge-runtime.test.cjs`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `ZoteroPaperBridgeCore.validateRequest()`.
- Produces runtime methods `queuePaths()`, `readRequest()`, `publishJSON()`, `scanNow()`, `confirmRun()`, and `processRun()`.

- [ ] **Step 1: Add fake-I/O runtime tests**

Refactor runtime into a factory exported as `module.exports` under Node and assigned to Zotero under the client. Inject dependencies `{ io, env, prompt, clock, zotero }`. Tests must prove:

```javascript
test("groups every queued subjob with one run_id into one confirmation", async () => {
  const first = job("a", "run-1"); Object.assign(first, { chunk_index: 1, chunk_count: 2 });
  const second = job("b", "run-1"); Object.assign(second, { chunk_index: 2, chunk_count: 2 });
  const harness = makeHarness({ requests: [first, second] });
  await harness.runtime.scanNow();
  assert.equal(harness.prompt.calls.length, 1);
  assert.equal(harness.prompt.calls[0].itemCount, 2);
});

test("does not prompt for an incomplete declared run", async () => {
  const first = job("a", "run-1"); Object.assign(first, { chunk_index: 1, chunk_count: 2 });
  const second = job("b", "run-1"); Object.assign(second, { chunk_index: 2, chunk_count: 2 });
  const harness = makeHarness({ requests: [first] });
  await harness.runtime.scanNow();
  assert.equal(harness.prompt.calls.length, 0);
  harness.addRequest(second);
  await harness.runtime.scanNow();
  assert.equal(harness.prompt.calls.length, 1);
});

test("inconsistent or duplicate chunk positions are rejected without prompting", async () => {
  const first = job("a", "run-1"); Object.assign(first, { chunk_index: 1, chunk_count: 2 });
  const duplicate = job("b", "run-1"); Object.assign(duplicate, { chunk_index: 1, chunk_count: 2 });
  const harness = makeHarness({ requests: [first, duplicate] });
  await harness.runtime.scanNow();
  assert.equal(harness.prompt.calls.length, 0);
  assert.equal(harness.zotero.writeCalls.length, 0);
  assert.equal(harness.errors[0].code, "bridge_run_chunks_invalid");
});

test("cancel emits one row per task and performs zero Zotero writes", async () => {
  const harness = makeHarness({ confirm: false, requests: [job("a", "run-1")] });
  await harness.runtime.scanNow();
  assert.equal(harness.zotero.writeCalls.length, 0);
  assert.equal(harness.results[0].rows[0].status, "user_cancelled");
});

test("unknown field and hash mismatch are archived without prompting", async () => {
  const bad = job("a", "run-1"); bad.extra = true;
  const harness = makeHarness({ requests: [bad] });
  await harness.runtime.scanNow();
  assert.equal(harness.prompt.calls.length, 0);
  assert.equal(harness.zotero.writeCalls.length, 0);
  assert.equal(harness.errors[0].code, "bridge_request_fields_invalid");
});
```

- [ ] **Step 2: Run runtime tests and verify RED**

```powershell
node --test zotero_bridge_plugin/tests/bridge-runtime.test.cjs
```

Expected: runtime factory/harness interfaces are missing.

- [ ] **Step 3: Implement fixed queue paths and atomic file operations**

The Zotero dependency adapter must use:

```javascript
const localAppData = Services.env.get("LOCALAPPDATA");
if (!localAppData) throw new Error("bridge_localappdata_missing");
const root = PathUtils.join(localAppData, "PaperScraperDOI", "zotero-bridge", "v1");
```

Implement JSON reads with `IOUtils.readUTF8()` plus `JSON.parse()`. Implement publication by writing `<name>.<random>.tmp`, flushing through the supported `IOUtils.writeUTF8`, and moving to the final path with `noOverwrite: true`. If the current Zotero 9 `IOUtils.move` option differs, feature-detect the option and fail `zotero_api_unavailable`; never silently replace an existing file.

`scanNow()` must serialize scans with an in-memory promise, validate every file name against the UUID pattern, read/validate all requests, and group by `run_id`. Before `confirmRun()` it must require one shared library/collection/creation/expiry/chunk-count tuple and exactly one job for every index `1..chunk_count`. An incomplete group is retained without a prompt or library write; a duplicate, inconsistent, or invalid group is archived/reported as `bridge_run_chunks_invalid` without a prompt or library write. Only a complete group calls `confirmRun()` once. The prompt text includes target library ID/name, total item count across all chunks, collection name, and a statement that existing attachments will not be modified.

- [ ] **Step 4: Implement cancellation and confirmed-run ledger**

Persist `plugin-state.json` atomically with this exact shape:

```json
{
  "schema_version": 1,
  "runs": {
    "paper_batch_20260711_090000": {
      "job_ids": ["uuid"],
      "payload_sha256": ["hex"],
      "confirmed_at": "ISO-8601",
      "completed": false
    }
  },
  "last_undo": null
}
```

On restart, a run is considered confirmed only if the queued job IDs and payload hashes exactly match the ledger. New or changed jobs require a new prompt and do not inherit confirmation.

- [ ] **Step 5: Run runtime tests and timing stress**

```powershell
node --test zotero_bridge_plugin/tests/bridge-runtime.test.cjs
1..50 | ForEach-Object { node --test zotero_bridge_plugin/tests/bridge-runtime.test.cjs }
```

Expected: all runs pass; every test records at most one confirmation per run ID.

- [ ] **Step 6: Append CHANGELOG and commit**

```powershell
git add zotero_bridge_plugin/content/bridge-runtime.js zotero_bridge_plugin/tests/bridge-runtime.test.cjs CHANGELOG.md
git commit -m "Process Zotero bridge queue safely"
```

### Task 4: Add Zotero item resolution, import, and available-PDF handling

**Files:**
- Modify: `zotero_bridge_plugin/content/bridge-runtime.js`
- Modify: `zotero_bridge_plugin/tests/bridge-runtime.test.cjs`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces `resolveItem()`, `findPDFAttachment()`, `importByDOI()`, `ensureCollection()`, `addAvailablePDFOnce()`, and `processItem()`.

- [ ] **Step 1: Add fake-Zotero behavior tests**

Add explicit tests for:

- exact DOI hit with existing PDF returns `existing_pdf`, performs zero imports and zero available-PDF calls;
- existing item without PDF is added to the batch collection once and calls available-PDF once;
- missing DOI imports one item, verifies its normalized DOI, adds it to the collection, and calls available-PDF once;
- title-only ambiguity returns `metadata_uncertain` with zero library writes;
- one item throwing does not stop the next item;
- replay from checkpoint performs zero duplicate calls;
- missing `Zotero.Attachments.addAvailablePDF` returns `zotero_api_unavailable` before any item write.

Use assertions such as:

```javascript
assert.deepEqual(result.rows.map(row => row.status), ["existing_pdf", "downloaded", "no_pdf"]);
assert.equal(fake.importCalls.length, 1);
assert.equal(fake.availablePDFCalls.length, 2);
assert.equal(new Set(fake.availablePDFCalls).size, 2);
```

- [ ] **Step 2: Run behavior tests and verify RED**

```powershell
node --test zotero_bridge_plugin/tests/bridge-runtime.test.cjs
```

Expected: missing Zotero adapter methods and result differences.

- [ ] **Step 3: Implement exact DOI and strict title matching adapters**

Use `new Zotero.Search()`, assign `libraryID`, add `DOI is <normalized>` for DOI searches, and fetch IDs through `await search.search()`. For title-only searches, use `title contains <bounded title fragment>`, map each candidate to `{id,title,firstCreator,year}`, and delegate final selection to `chooseCandidate()`.

Reject feed items, attachments, notes, annotations, deleted items, and items from a different library. Multiple exact normalized DOI matches return `metadata_uncertain`; do not choose the first result.

- [ ] **Step 4: Implement collection, import, and PDF adapters with feature checks**

Use these exact operations behind feature-checked adapters:

```javascript
async function ensureCollection(libraryID, name) {
  const search = new Zotero.Search();
  search.libraryID = libraryID;
  search.addCondition("collection", "is", name);
  const ids = await search.search();
  const existing = (await Zotero.Collections.getAsync(ids)).find(c => c.name === name);
  if (existing) return existing;
  const collection = new Zotero.Collection();
  collection.libraryID = libraryID;
  collection.name = name;
  await collection.saveTx();
  return collection;
}

async function importByDOI(doi, libraryID, collectionID) {
  const translate = new Zotero.Translate.Search();
  translate.setIdentifier({ DOI: doi });
  const translators = await translate.getTranslators();
  if (!translators.length) throw new Error("not_found");
  translate.setTranslator(translators);
  const items = await translate.translate({
    libraryID,
    collections: [collectionID],
    saveAttachments: false,
  });
  const exact = items.filter(item => normalizeDOI(item.getField("DOI")) === doi);
  if (exact.length !== 1) throw new Error(exact.length ? "metadata_uncertain" : "not_found");
  return exact[0];
}
```

At runtime startup, verify constructors and methods used above exist. In the Zotero test profile, compare the actual `translate()` option contract with Zotero 9.0.6. If it differs, adapt only this wrapper and add a fake contract test for the observed signature; do not spread version branches through processing logic.

For attachments, call `item.getAttachments()`, load children, require a PDF attachment, and use `await attachment.getFilePathAsync()` when available or `attachment.getFilePath()` otherwise. Require a non-empty absolute Windows path before returning it; project-side finalization performs the authoritative file/reparse/PDF validation.

Call `Zotero.Attachments.addAvailablePDF(item)` once. If it returns no attachment, re-read child attachments once; return `no_pdf` when none exists.

- [ ] **Step 5: Run behavior and full plugin tests**

```powershell
node --test zotero_bridge_plugin/tests/*.test.cjs
```

Expected: all plugin tests pass.

- [ ] **Step 6: Append CHANGELOG and commit**

```powershell
git add zotero_bridge_plugin/content/bridge-runtime.js zotero_bridge_plugin/tests/bridge-runtime.test.cjs CHANGELOG.md
git commit -m "Resolve Zotero items and PDFs"
```

### Task 5: Add checkpoints, crash recovery, status, and safe undo

**Files:**
- Modify: `zotero_bridge_plugin/content/bridge-runtime.js`
- Modify: `zotero_bridge_plugin/tests/bridge-runtime.test.cjs`
- Modify: `zotero_bridge_plugin/locale/zh-CN/bridge.ftl`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces per-job progress files, final result publication, `showStatus()`, and `undoLastBatch()` with an explicit ledger.

- [ ] **Step 1: Add crash/restart and undo safety tests**

Test these exact scenarios:

```javascript
test("restart resumes after last completed task without a second prompt", async () => {
  const first = makeHarness({ crashAfter: 1, requests: [jobWithThreeItems()] });
  await assert.rejects(first.runtime.scanNow(), /fixture_crash/);
  const second = makeHarness({ sharedFiles: first.files, sharedZotero: first.zotero });
  await second.runtime.scanNow();
  assert.equal(first.prompt.calls.length + second.prompt.calls.length, 1);
  assert.equal(second.zotero.callsFor("paper-0001"), 0);
  assert.equal(second.results[0].rows.length, 3);
});

test("undo touches only IDs created by this batch", async () => {
  const harness = makeHarness({ ledger: {
    created_item_ids: [901], created_attachment_ids: [902], added_memberships: [[304, 77]],
    preexisting_item_ids: [304], preexisting_attachment_ids: [305],
  }});
  await harness.runtime.undoLastBatch();
  assert.deepEqual(harness.zotero.deletedIDs, [902, 901]);
  assert.deepEqual(harness.zotero.removedMemberships, [[304, 77]]);
  assert.equal(harness.zotero.deletedIDs.includes(304), false);
  assert.equal(harness.zotero.deletedIDs.includes(305), false);
});
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
node --test zotero_bridge_plugin/tests/bridge-runtime.test.cjs
```

Expected: restart reprocesses rows or undo methods are missing.

- [ ] **Step 3: Implement per-item progress and final publication**

Use `processing/<job_id>.progress.json` with exact fields:

```json
{
  "schema_version": 1,
  "job_id": "uuid",
  "payload_sha256": "hex",
  "confirmed": true,
  "rows": [],
  "created_item_ids": [],
  "created_attachment_ids": [],
  "added_memberships": []
}
```

After every item, atomically replace progress. On restart, validate job/hash and completed task IDs before reuse. Publish a full result only when every requested task has exactly one row. After publishing, mark the run completed and archive request/progress; never delete the only copy of a result.

- [ ] **Step 4: Implement status and undo with a second confirmation**

`showStatus()` displays the most recent run ID, total/success/failure counts, and whether it is waiting/running/completed.

`undoLastBatch()` first shows the exact number of created items, created attachments, and added collection memberships. On cancel it performs zero writes. On confirm, remove only ledger-recorded memberships, then erase only ledger-recorded newly created attachments/items that still belong to the expected library and batch. If identity differs, skip and report it. Store an undo result and never allow the same ledger to run twice.

- [ ] **Step 5: Run full plugin tests twice and safety scans**

```powershell
node --test zotero_bridge_plugin/tests/*.test.cjs
node --test zotero_bridge_plugin/tests/*.test.cjs
rg -n "zotero\.sqlite|executeTransaction|queryAsync|eval\(|Function\(|fetch\(|XMLHttpRequest|WebSocket|ServerSocket" zotero_bridge_plugin
```

Expected: tests pass twice; scan has no direct database, code execution, or network-listener implementation.

- [ ] **Step 6: Append CHANGELOG and commit**

```powershell
git add zotero_bridge_plugin/content/bridge-runtime.js zotero_bridge_plugin/tests/bridge-runtime.test.cjs zotero_bridge_plugin/locale/zh-CN/bridge.ftl CHANGELOG.md
git commit -m "Make Zotero bridge resumable and undoable"
```

### Task 6: Add source documentation and manual XPI builder

**Files:**
- Create: `zotero_bridge_plugin/README.md`
- Create: `build_zotero_bridge_xpi.ps1`
- Create: `tests/test_zotero_bridge_packaging.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces a validated builder that creates `dist/zotero-paper-download-bridge-<version>.xpi` only when the user explicitly runs it.

- [ ] **Step 1: Write failing builder source-contract tests**

Create `tests/test_zotero_bridge_packaging.py` asserting the script:

- has `[CmdletBinding()]` and `-OutputDirectory`;
- refuses an output path inside plugin source;
- uses an explicit allowlist for manifest/bootstrap/content/locale;
- excludes `tests`, `package.json`, `.git`, logs, queue files, and secrets;
- validates the archive contains root-level `manifest.json` and `bootstrap.js`;
- never calls the existing `make_windows_ui_package.bat`;
- does not run automatically from any start/install script.

- [ ] **Step 2: Run test and verify RED**

```powershell
..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge_packaging -v
```

Expected: builder file missing.

- [ ] **Step 3: Implement builder and beginner README**

The builder accepts an output directory, parses version from `manifest.json`, copies only the explicit source allowlist to a temporary staging directory, runs `Compress-Archive`, renames `.zip` to `.xpi`, lists it with `tar -tf`, validates required root entries, then atomically moves it to the requested output path. It refuses overwrite unless an explicit `-Force` is supplied and never installs the XPI.

README documents:

```powershell
node --test .\zotero_bridge_plugin\tests\*.test.cjs
powershell -ExecutionPolicy Bypass -File .\build_zotero_bridge_xpi.ps1 -OutputDirectory .\dist
```

Clearly mark the second command as approval-gated and state that this plan does not execute it.

- [ ] **Step 4: Run tests without building**

```powershell
..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge_packaging -v
node --test zotero_bridge_plugin/tests/*.test.cjs
git diff --check
```

Expected: all tests pass and no `.xpi` exists under the repository.

- [ ] **Step 5: Append CHANGELOG and commit**

```powershell
git add zotero_bridge_plugin/README.md build_zotero_bridge_xpi.ps1 tests/test_zotero_bridge_packaging.py CHANGELOG.md
git commit -m "Document Zotero bridge packaging"
```

### Task 7: Plugin review gate

**Files:**
- Modify only files required by review findings.
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces reviewed plugin source ready for integration tests, but no XPI and no Zotero installation.

- [ ] **Step 1: Review every plugin write path**

Trace request validation to complete-chunk grouping to confirmation to collection/item/attachment operations and result publication. Prove an incomplete or inconsistent chunk group has zero prompts and zero writes, cancellation has zero writes, every write is ledgered, replay does not duplicate writes, and undo cannot touch preexisting IDs.

- [ ] **Step 2: Run plugin and Python packaging tests**

```powershell
node --test zotero_bridge_plugin/tests/*.test.cjs
..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge_packaging -v
```

Expected: all pass.

- [ ] **Step 3: Verify no package or profile mutation**

```powershell
Get-ChildItem -Recurse -File -Filter *.xpi | Select-Object FullName
git status --short
```

Expected: no newly generated XPI; only intentional review changes before commit.

- [ ] **Step 4: Append review evidence and commit**

```powershell
git add zotero_bridge_plugin build_zotero_bridge_xpi.ps1 tests/test_zotero_bridge_packaging.py CHANGELOG.md
git commit -m "Harden Zotero 9 bridge plugin"
```
