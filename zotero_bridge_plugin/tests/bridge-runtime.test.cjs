const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../content/bridge-core.js");
const createRuntime = require("../content/bridge-runtime.js");

const JOB_IDS = [
  "11111111-1111-4111-8111-111111111111",
  "22222222-2222-4222-8222-222222222222",
  "33333333-3333-4333-8333-333333333333",
  "44444444-4444-4444-8444-444444444444",
];

async function job({
  number = 1,
  runID = "paper_batch_20260711_090000",
  chunkIndex = 1,
  chunkCount = 1,
  libraryID = 1,
  collectionName = "Codex下载回退_20260711_090000",
  items = null,
} = {}) {
  const request = {
    schema_version: 1,
    job_id: JOB_IDS[number - 1],
    payload_sha256: "",
    created_at: "2026-07-11T09:00:00Z",
    expires_at: "2026-07-12T09:00:00Z",
    run_id: runID,
    library_id: libraryID,
    collection_name: collectionName,
    chunk_index: chunkIndex,
    chunk_count: chunkCount,
    items: items || [{
      task_id: `paper-${String(number).padStart(4, "0")}`,
      doi: `10.1000/example-${number}`,
      title: `Example Paper ${number}`,
      authors: "Smith, J.",
      year: "2025",
    }],
  };
  request.payload_sha256 = await core.payloadHash(request);
  return request;
}

function normalizePath(value) {
  return String(value).replaceAll("\\", "/").replace(/\/+$/u, "");
}

function createMemoryIO() {
  const files = new Map();
  const directories = new Set();
  const operations = [];

  function join(...parts) {
    return parts
      .map((part, index) => {
        const normalized = normalizePath(part);
        return index === 0 ? normalized : normalized.replace(/^\/+/, "");
      })
      .filter(Boolean)
      .join("/");
  }

  function basename(path) {
    return normalizePath(path).split("/").at(-1);
  }

  return {
    files,
    operations,
    join,
    basename,
    async makeDir(path) {
      directories.add(normalizePath(path));
    },
    async list(path) {
      const directory = normalizePath(path);
      return Array.from(files.keys()).filter(candidate => {
        const normalized = normalizePath(candidate);
        return normalized.slice(0, normalized.lastIndexOf("/")) === directory;
      });
    },
    async exists(path) {
      return files.has(normalizePath(path));
    },
    async readUTF8(path) {
      const normalized = normalizePath(path);
      if (!files.has(normalized)) throw new Error("bridge_file_missing");
      return files.get(normalized);
    },
    async writeUTF8(path, text, { exclusive = false } = {}) {
      const normalized = normalizePath(path);
      if (exclusive && files.has(normalized)) throw new Error("bridge_file_exists");
      operations.push({ type: "write", path: normalized });
      files.set(normalized, text);
    },
    async replaceUTF8(path, text, temporaryPath) {
      operations.push({
        type: "replace",
        path: normalizePath(path),
        temporaryPath: normalizePath(temporaryPath),
      });
      files.set(normalizePath(path), text);
    },
    async move(source, target, { noOverwrite = false } = {}) {
      const from = normalizePath(source);
      const to = normalizePath(target);
      if (!files.has(from)) throw new Error("bridge_file_missing");
      if (noOverwrite && files.has(to)) throw new Error("bridge_file_exists");
      operations.push({ type: "move", source: from, target: to, noOverwrite });
      files.set(to, files.get(from));
      files.delete(from);
    },
    async remove(path) {
      files.delete(normalizePath(path));
    },
  };
}

async function makeHarness({ requests = [], confirm = true, zoteroOptions = {} } = {}) {
  const io = createMemoryIO();
  const prompt = {
    calls: [],
    alerts: [],
    async confirm(details) {
      this.calls.push(details);
      return confirm;
    },
    alert(title, message) {
      this.alerts.push({ title, message });
    },
  };
  const errors = [];
  const items = (zoteroOptions.items || []).map(value => ({
    ...value,
    attachments: (value.attachments || []).map(attachment => ({ ...attachment })),
    collections: [...(value.collections || [])],
  }));
  const collections = (zoteroOptions.collections || []).map(value => ({ ...value }));
  let nextItemID = Math.max(1000, ...items.map(item => Number(item.id) || 0)) + 1;
  let nextCollectionID = Math.max(700, ...collections.map(value => Number(value.id) || 0)) + 1;
  const zotero = {
    pluginVersion: "0.1.0-test",
    version: "9.0.6-test",
    writeCalls: [],
    searchCalls: [],
    importCalls: [],
    collectionCalls: [],
    membershipCalls: [],
    availablePDFCalls: [],
    items,
    collections,
    async getLibraryName(libraryID) {
      return libraryID === 1 ? "我的文库" : `文库 ${libraryID}`;
    },
    reportError(error) {
      errors.push(error);
    },
    async assertProcessingAPI() {
      if (zoteroOptions.availablePDFAPI === false) {
        throw new Error("zotero_api_unavailable");
      }
    },
    async searchByDOI(libraryID, doi) {
      this.searchCalls.push({ type: "doi", libraryID, value: doi });
      const configuredError = zoteroOptions.searchErrors?.[doi];
      if (configuredError) throw new Error(configuredError);
      const configuredIDs = zoteroOptions.searchDOIResultIDs?.[doi];
      if (configuredIDs) {
        return configuredIDs.map(id => this.items.find(item => item.id === id)).filter(Boolean);
      }
      return this.items.filter(item => (
        item.libraryID === libraryID && core.normalizeDOI(item.doi) === doi
      ));
    },
    async searchByTitle(libraryID, fragment) {
      this.searchCalls.push({ type: "title", libraryID, value: fragment });
      const wanted = String(fragment).toLocaleLowerCase("und");
      return this.items.filter(item => (
        item.libraryID === libraryID
        && String(item.title || "").toLocaleLowerCase("und").includes(wanted)
      ));
    },
    async describeItem(item, libraryID) {
      return {
        item,
        id: item.id,
        libraryID: item.libraryID,
        eligible: item.libraryID === libraryID
          && item.regular !== false
          && item.feed !== true
          && item.deleted !== true,
        doi: String(item.doi || ""),
        title: String(item.title || ""),
        firstCreator: String(item.firstCreator || ""),
        year: String(item.year || ""),
      };
    },
    async listAttachments(item) {
      return item.attachments || [];
    },
    async describeAttachment(attachment, item) {
      return {
        attachment,
        id: attachment.id,
        eligible: attachment.deleted !== true
          && attachment.isAttachment !== false
          && (attachment.libraryID ?? item.libraryID) === item.libraryID
          && (attachment.parentItemID ?? item.id) === item.id,
        contentType: String(attachment.contentType || ""),
        path: attachment.path || "",
      };
    },
    async ensureCollection(libraryID, name) {
      this.collectionCalls.push({ libraryID, name });
      const matches = this.collections.filter(collection => (
        collection.libraryID === libraryID
        && collection.name === name
        && collection.deleted !== true
      ));
      if (matches.length > 1) throw new Error("metadata_uncertain");
      if (matches.length === 1) return matches[0];
      const collection = { id: nextCollectionID++, libraryID, name, deleted: false };
      this.collections.push(collection);
      this.writeCalls.push({ type: "create_collection", id: collection.id });
      return collection;
    },
    async translateByDOI(doi, libraryID, collectionID) {
      this.importCalls.push({ doi, libraryID, collectionID, saveAttachments: false });
      const configuredError = zoteroOptions.importErrors?.[doi];
      if (configuredError) throw new Error(configuredError);
      const configured = zoteroOptions.translationsByDOI?.[doi];
      if (!configured) return [];
      const translated = (Array.isArray(configured) ? configured : [configured]).map(value => {
        const item = {
          ...value,
          id: value.id || nextItemID++,
          libraryID,
          attachments: (value.attachments || []).map(attachment => ({ ...attachment })),
          collections: Array.from(new Set([...(value.collections || []), collectionID])),
        };
        this.items.push(item);
        this.writeCalls.push({ type: "import_item", id: item.id });
        return item;
      });
      return translated;
    },
    async addToCollection(item, collectionID) {
      this.membershipCalls.push({ itemID: item.id, collectionID });
      item.collections ||= [];
      if (item.collections.includes(collectionID)) return false;
      item.collections.push(collectionID);
      this.writeCalls.push({ type: "add_membership", itemID: item.id, collectionID });
      return true;
    },
    async addAvailablePDF(item) {
      this.availablePDFCalls.push(item.id);
      const configuredError = zoteroOptions.availablePDFErrors?.[item.id];
      if (configuredError) throw new Error(configuredError);
      const configured = zoteroOptions.availablePDFByItemID?.[item.id];
      if (!configured) return false;
      const attachment = {
        ...configured,
        id: configured.id || nextItemID++,
        libraryID: item.libraryID,
        parentItemID: item.id,
      };
      item.attachments ||= [];
      item.attachments.push(attachment);
      this.writeCalls.push({ type: "add_available_pdf", itemID: item.id, attachmentID: attachment.id });
      return attachment;
    },
  };
  const clock = {
    now: () => new Date("2026-07-11T10:00:00Z"),
    setInterval: () => 1,
    clearInterval: () => {},
  };
  const runtime = createRuntime({
    core,
    io,
    env: { get: name => (name === "LOCALAPPDATA" ? "C:/LocalAppData" : "") },
    prompt,
    clock,
    zotero,
  });
  const paths = runtime.queuePaths();

  function addRequest(request, directory = paths.inbox) {
    io.files.set(io.join(directory, `${request.job_id}.json`), `${JSON.stringify(request)}\n`);
  }

  function removeQueuedRequests() {
    for (const path of Array.from(io.files.keys())) {
      if (path.startsWith(`${paths.inbox}/`) || path.startsWith(`${paths.processing}/`)) {
        io.files.delete(path);
      }
    }
  }

  function results() {
    return Array.from(io.files.entries())
      .filter(([path]) => path.startsWith(`${paths.outbox}/`) && path.endsWith(".result.json"))
      .map(([, text]) => JSON.parse(text))
      .sort((left, right) => left.job_id.localeCompare(right.job_id));
  }

  for (const request of requests) addRequest(request);
  return {
    runtime,
    io,
    prompt,
    zotero,
    errors,
    paths,
    addRequest,
    removeQueuedRequests,
    results,
  };
}

test("groups every queued subjob with one run_id into one confirmation", async () => {
  const first = await job({ number: 1, chunkIndex: 1, chunkCount: 2 });
  const second = await job({ number: 2, chunkIndex: 2, chunkCount: 2 });
  const harness = await makeHarness({ requests: [first, second] });

  await harness.runtime.scanNow();

  assert.equal(harness.prompt.calls.length, 1);
  assert.equal(harness.prompt.calls[0].itemCount, 2);
  assert.match(harness.prompt.calls[0].message, /我的文库.*ID: 1/s);
  assert.match(harness.prompt.calls[0].message, /现有附件不会被修改/);
});

test("uses only the fixed LocalAppData bridge directories", async () => {
  const harness = await makeHarness();
  assert.deepEqual(harness.paths, {
    root: "C:/LocalAppData/PaperScraperDOI/zotero-bridge/v1",
    inbox: "C:/LocalAppData/PaperScraperDOI/zotero-bridge/v1/inbox",
    processing: "C:/LocalAppData/PaperScraperDOI/zotero-bridge/v1/processing",
    outbox: "C:/LocalAppData/PaperScraperDOI/zotero-bridge/v1/outbox",
    archive: "C:/LocalAppData/PaperScraperDOI/zotero-bridge/v1/archive",
    state: "C:/LocalAppData/PaperScraperDOI/zotero-bridge/v1/plugin-state.json",
  });
});

test("does not prompt for an incomplete declared run", async () => {
  const first = await job({ number: 1, chunkIndex: 1, chunkCount: 2 });
  const second = await job({ number: 2, chunkIndex: 2, chunkCount: 2 });
  const harness = await makeHarness({ requests: [first] });

  await harness.runtime.scanNow();
  assert.equal(harness.prompt.calls.length, 0);
  assert.equal((await harness.io.list(harness.paths.inbox)).length, 1);
  assert.equal((await harness.io.list(harness.paths.processing)).length, 0);
  harness.addRequest(second);
  await harness.runtime.scanNow();
  assert.equal(harness.prompt.calls.length, 1);
});

test("inconsistent or duplicate chunk positions are rejected without prompting", async () => {
  const first = await job({ number: 1, chunkIndex: 1, chunkCount: 2 });
  const duplicate = await job({ number: 2, chunkIndex: 1, chunkCount: 2 });
  const harness = await makeHarness({ requests: [first, duplicate] });

  await harness.runtime.scanNow();

  assert.equal(harness.prompt.calls.length, 0);
  assert.equal(harness.zotero.writeCalls.length, 0);
  assert.equal(harness.errors[0].code, "bridge_run_chunks_invalid");
  assert.deepEqual(
    harness.results().flatMap(result => result.rows.map(row => row.status)),
    ["plugin_error", "plugin_error"],
  );
});

test("rejects inconsistent shared run values and cross-chunk task duplicates", async () => {
  const first = await job({ number: 1, chunkIndex: 1, chunkCount: 2 });
  const inconsistent = await job({
    number: 2,
    chunkIndex: 2,
    chunkCount: 2,
    libraryID: 2,
  });
  const harness = await makeHarness({ requests: [first, inconsistent] });
  await harness.runtime.scanNow();
  assert.equal(harness.prompt.calls.length, 0);
  assert.equal(harness.errors[0].code, "bridge_run_chunks_invalid");

  const duplicateTaskFirst = await job({ number: 3, chunkIndex: 1, chunkCount: 2 });
  const duplicateTaskSecond = await job({
    number: 4,
    chunkIndex: 2,
    chunkCount: 2,
    items: [{
      task_id: duplicateTaskFirst.items[0].task_id,
      doi: "10.1000/duplicate",
      title: "Duplicate Task",
      authors: "Smith, J.",
      year: "2025",
    }],
  });
  const duplicateHarness = await makeHarness({
    requests: [duplicateTaskFirst, duplicateTaskSecond],
  });
  await duplicateHarness.runtime.scanNow();
  assert.equal(duplicateHarness.prompt.calls.length, 0);
  assert.equal(duplicateHarness.errors[0].code, "bridge_run_chunks_invalid");
});

test("cancel emits one row per task and performs zero Zotero writes", async () => {
  const request = await job({
    items: [
      { task_id: "paper-0001", doi: "10.1/a", title: "A", authors: "A", year: "2024" },
      { task_id: "paper-0002", doi: "10.1/b", title: "B", authors: "B", year: "2025" },
    ],
  });
  request.payload_sha256 = await core.payloadHash(request);
  const harness = await makeHarness({ confirm: false, requests: [request] });

  await harness.runtime.scanNow();

  assert.equal(harness.zotero.writeCalls.length, 0);
  const [result] = harness.results();
  assert.deepEqual(Object.keys(result), [
    "schema_version",
    "job_id",
    "payload_sha256",
    "plugin_version",
    "zotero_version",
    "started_at",
    "finished_at",
    "rows",
  ]);
  assert.equal(result.job_id, request.job_id);
  assert.equal(result.payload_sha256, request.payload_sha256);
  assert.equal(result.plugin_version, "0.1.0-test");
  assert.equal(result.zotero_version, "9.0.6-test");
  assert.deepEqual(result.rows.map(row => row.status), [
    "user_cancelled",
    "user_cancelled",
  ]);
  assert.equal((await harness.io.list(harness.paths.processing)).length, 0);
  assert.equal((await harness.io.list(harness.paths.archive)).length, 1);
});

test("unknown field and hash mismatch are archived without prompting", async () => {
  const unknown = await job({ number: 1 });
  unknown.extra = true;
  const tampered = await job({ number: 2, runID: "paper_batch_20260711_090001" });
  tampered.items[0].title = "Changed after hashing";
  const harness = await makeHarness({ requests: [unknown, tampered] });

  await harness.runtime.scanNow();

  assert.equal(harness.prompt.calls.length, 0);
  assert.equal(harness.zotero.writeCalls.length, 0);
  assert.deepEqual(harness.errors.map(error => error.code).sort(), [
    "bridge_payload_hash_invalid",
    "bridge_request_fields_invalid",
  ]);
  assert.equal((await harness.io.list(harness.paths.archive)).length, 2);
});

test("invalid filenames and filename identity conflicts are archived", async () => {
  const harness = await makeHarness();
  harness.io.files.set(
    harness.io.join(harness.paths.inbox, "not-a-job.json"),
    "{}\n",
  );
  const request = await job({ number: 1 });
  harness.io.files.set(
    harness.io.join(harness.paths.inbox, `${JOB_IDS[1]}.json`),
    `${JSON.stringify(request)}\n`,
  );

  await harness.runtime.scanNow();

  assert.equal(harness.prompt.calls.length, 0);
  assert.deepEqual(harness.errors.map(error => error.code).sort(), [
    "bridge_job_id_conflict",
    "bridge_request_filename_invalid",
  ]);
  assert.equal((await harness.io.list(harness.paths.archive)).length, 2);
});

test("corrupt plugin state blocks prompts and preserves queued requests", async () => {
  const request = await job();
  const harness = await makeHarness({ requests: [request] });
  harness.io.files.set(harness.paths.state, JSON.stringify({
    schema_version: 1,
    runs: {},
    last_undo: null,
    unexpected: true,
  }));

  const outcome = await harness.runtime.scanNow();

  assert.equal(outcome.status, "state_invalid");
  assert.equal(harness.prompt.calls.length, 0);
  assert.equal(harness.zotero.writeCalls.length, 0);
  assert.equal(harness.errors[0].code, "bridge_state_invalid");
  assert.equal((await harness.io.list(harness.paths.inbox)).length, 1);
});

test("persists exact confirmation state and reuses it only for identical jobs", async () => {
  const original = await job({ number: 1 });
  const harness = await makeHarness({ requests: [original] });
  await harness.runtime.scanNow();
  await harness.runtime.scanNow();

  assert.equal(harness.prompt.calls.length, 1);
  const state = JSON.parse(await harness.io.readUTF8(harness.paths.state));
  assert.deepEqual(state, {
    schema_version: 1,
    runs: {
      paper_batch_20260711_090000: {
        job_ids: [original.job_id],
        payload_sha256: [original.payload_sha256],
        confirmed_at: "2026-07-11T10:00:00.000Z",
        completed: false,
      },
    },
    last_undo: null,
  });

  harness.removeQueuedRequests();
  const changed = await job({ number: 2 });
  harness.addRequest(changed);
  await harness.runtime.scanNow();
  assert.equal(harness.prompt.calls.length, 2);
});

test("serializes overlapping scans so one run receives at most one prompt", async () => {
  const harness = await makeHarness({ requests: [await job()] });
  const scans = [
    harness.runtime.scanNow(),
    harness.runtime.scanNow(),
    harness.runtime.scanNow(),
  ];
  assert.equal(scans[0], scans[1]);
  assert.equal(scans[1], scans[2]);
  await Promise.all(scans);
  assert.equal(harness.prompt.calls.length, 1);
});

test("publishJSON never overwrites an existing result", async () => {
  const harness = await makeHarness();
  const target = harness.io.join(harness.paths.outbox, `${JOB_IDS[0]}.result.json`);
  harness.io.files.set(target, "original bytes");

  await assert.rejects(
    harness.runtime.publishJSON(target, { changed: true }),
    /bridge_file_exists/,
  );
  assert.equal(harness.io.files.get(target), "original bytes");
  assert.equal(Array.from(harness.io.files.keys()).some(path => path.endsWith(".tmp")), false);
});

test("publishJSON writes a random temporary file then uses a no-overwrite move", async () => {
  const harness = await makeHarness();
  const target = harness.io.join(harness.paths.outbox, `${JOB_IDS[0]}.result.json`);

  await harness.runtime.publishJSON(target, { ok: true });

  assert.equal(JSON.parse(harness.io.files.get(target)).ok, true);
  assert.equal(harness.io.operations.length, 2);
  assert.equal(harness.io.operations[0].type, "write");
  assert.match(harness.io.operations[0].path, /\.tmp$/);
  assert.deepEqual(harness.io.operations[1], {
    type: "move",
    source: harness.io.operations[0].path,
    target,
    noOverwrite: true,
  });
});

test("exact DOI hit with an existing PDF performs no import or available-PDF call", async () => {
  const request = await job();
  const collectionID = 701;
  const harness = await makeHarness({
    requests: [request],
    zoteroOptions: {
      collections: [{
        id: collectionID,
        libraryID: 1,
        name: request.collection_name,
      }],
      items: [{
        id: 101,
        libraryID: 1,
        doi: "https://doi.org/10.1000/EXAMPLE-1",
        title: "Example Paper 1",
        firstCreator: "Smith",
        year: "2025",
        collections: [],
        attachments: [{
          id: 201,
          contentType: "application/pdf",
          path: "C:\\Zotero\\storage\\EXISTING\\paper.pdf",
        }],
      }],
    },
  });

  for (const method of [
    "resolveItem",
    "findPDFAttachment",
    "importByDOI",
    "ensureCollection",
    "addAvailablePDFOnce",
    "processItem",
  ]) {
    assert.equal(typeof harness.runtime[method], "function");
  }
  await harness.runtime.scanNow();

  const [result] = harness.results();
  assert.equal(result.rows[0].status, "existing_pdf");
  assert.equal(result.rows[0].zotero_item_id, "101");
  assert.equal(result.rows[0].attachment_path, "C:\\Zotero\\storage\\EXISTING\\paper.pdf");
  assert.equal(harness.zotero.importCalls.length, 0);
  assert.equal(harness.zotero.availablePDFCalls.length, 0);
  assert.deepEqual(harness.zotero.membershipCalls, [{ itemID: 101, collectionID }]);
  assert.deepEqual(harness.zotero.writeCalls, [{
    type: "add_membership",
    itemID: 101,
    collectionID,
  }]);
});

test("DOI resolution rejects ineligible candidates and refuses multiple exact items", async () => {
  const request = await job();
  const doi = core.normalizeDOI(request.items[0].doi);
  const collectionID = 701;
  const common = {
    doi,
    title: request.items[0].title,
    firstCreator: "Smith",
    year: "2025",
    collections: [collectionID],
    attachments: [],
  };
  const harness = await makeHarness({
    requests: [request],
    zoteroOptions: {
      collections: [{ id: collectionID, libraryID: 1, name: request.collection_name }],
      items: [{ id: 301, libraryID: 2, ...common }, {
        id: 302, libraryID: 1, feed: true, ...common,
      }, {
        id: 303, libraryID: 1, regular: false, ...common,
      }, {
        id: 304, libraryID: 1, deleted: true, ...common,
      }, {
        id: 305,
        libraryID: 1,
        ...common,
        attachments: [{
          id: 405,
          contentType: "application/pdf",
          path: "C:\\Zotero\\storage\\ELIGIBLE\\paper.pdf",
        }],
      }],
      searchDOIResultIDs: { [doi]: [301, 302, 303, 304, 305] },
    },
  });

  await harness.runtime.scanNow();

  assert.equal(harness.results()[0].rows[0].status, "existing_pdf");
  assert.equal(harness.results()[0].rows[0].zotero_item_id, "305");
  assert.equal(harness.zotero.importCalls.length, 0);

  const duplicateRequest = await job({ number: 2 });
  const duplicateDOI = core.normalizeDOI(duplicateRequest.items[0].doi);
  const duplicateHarness = await makeHarness({
    requests: [duplicateRequest],
    zoteroOptions: {
      items: [401, 402].map(id => ({
        id,
        libraryID: 1,
        doi: duplicateDOI,
        title: duplicateRequest.items[0].title,
        firstCreator: "Smith",
        year: "2025",
        collections: [],
        attachments: [],
      })),
      searchDOIResultIDs: { [duplicateDOI]: [401, 402] },
    },
  });
  await duplicateHarness.runtime.scanNow();
  assert.equal(duplicateHarness.results()[0].rows[0].status, "metadata_uncertain");
  assert.equal(duplicateHarness.zotero.writeCalls.length, 0);
  assert.equal(duplicateHarness.zotero.collectionCalls.length, 0);
});

test("existing item without PDF is collected once and requests available PDF once", async () => {
  const request = await job();
  const collectionID = 701;
  const harness = await makeHarness({
    requests: [request],
    zoteroOptions: {
      collections: [{ id: collectionID, libraryID: 1, name: request.collection_name }],
      items: [{
        id: 102,
        libraryID: 1,
        doi: request.items[0].doi,
        title: request.items[0].title,
        firstCreator: "Smith",
        year: "2025",
        collections: [],
        attachments: [],
      }],
      availablePDFByItemID: {
        102: {
          id: 202,
          contentType: "application/pdf",
          path: "D:\\Zotero\\storage\\NEWPDF\\paper.pdf",
        },
      },
    },
  });

  await harness.runtime.scanNow();

  assert.equal(harness.results()[0].rows[0].status, "downloaded");
  assert.deepEqual(harness.zotero.availablePDFCalls, [102]);
  assert.deepEqual(harness.zotero.membershipCalls, [{ itemID: 102, collectionID }]);
  assert.equal(harness.zotero.importCalls.length, 0);
  const callsAfterCompletion = {
    memberships: harness.zotero.membershipCalls.length,
    available: harness.zotero.availablePDFCalls.length,
  };
  await harness.runtime.scanNow();
  assert.deepEqual({
    memberships: harness.zotero.membershipCalls.length,
    available: harness.zotero.availablePDFCalls.length,
  }, callsAfterCompletion);
});

test("missing DOI imports exactly one matching item without translator attachments", async () => {
  const request = await job();
  const doi = core.normalizeDOI(request.items[0].doi);
  const collectionID = 701;
  const harness = await makeHarness({
    requests: [request],
    zoteroOptions: {
      collections: [{ id: collectionID, libraryID: 1, name: request.collection_name }],
      translationsByDOI: {
        [doi]: {
          id: 103,
          doi: "https://doi.org/10.1000/EXAMPLE-1",
          title: request.items[0].title,
          firstCreator: "Smith",
          year: "2025",
        },
      },
      availablePDFByItemID: {
        103: {
          id: 203,
          contentType: "application/pdf",
          path: "C:\\Zotero\\storage\\IMPORTED\\paper.pdf",
        },
      },
    },
  });

  await harness.runtime.scanNow();

  assert.equal(harness.results()[0].rows[0].status, "downloaded");
  assert.deepEqual(harness.zotero.importCalls, [{
    doi,
    libraryID: 1,
    collectionID,
    saveAttachments: false,
  }]);
  assert.equal(
    core.normalizeDOI(harness.zotero.items.find(item => item.id === 103).doi),
    doi,
  );
  assert.deepEqual(harness.zotero.availablePDFCalls, [103]);
});

test("identifier import rejects a translated item whose DOI is not exact", async () => {
  const request = await job();
  const doi = core.normalizeDOI(request.items[0].doi);
  const collectionID = 701;
  const harness = await makeHarness({
    requests: [request],
    zoteroOptions: {
      collections: [{ id: collectionID, libraryID: 1, name: request.collection_name }],
      translationsByDOI: {
        [doi]: {
          id: 104,
          doi: "10.1000/a-different-paper",
          title: "Wrong Translation",
          firstCreator: "Other",
          year: "2020",
        },
      },
    },
  });

  await harness.runtime.scanNow();

  assert.equal(harness.results()[0].rows[0].status, "not_found");
  assert.equal(harness.zotero.importCalls.length, 1);
  assert.equal(harness.zotero.availablePDFCalls.length, 0);
});

test("title-only ambiguity returns metadata_uncertain with zero library writes", async () => {
  const request = await job({
    items: [{
      task_id: "paper-0001",
      doi: "",
      title: "Ambiguous Titanium Paper",
      authors: "Smith, J.",
      year: "2025",
    }],
  });
  const harness = await makeHarness({
    requests: [request],
    zoteroOptions: {
      items: [1, 2].map(id => ({
        id: 110 + id,
        libraryID: 1,
        doi: "",
        title: "Ambiguous Titanium Paper",
        firstCreator: "Smith",
        year: "2025",
        attachments: [],
        collections: [],
      })),
    },
  });

  await harness.runtime.scanNow();

  assert.equal(harness.results()[0].rows[0].status, "metadata_uncertain");
  assert.equal(harness.zotero.writeCalls.length, 0);
  assert.equal(harness.zotero.collectionCalls.length, 0);
  assert.equal(harness.zotero.importCalls.length, 0);
  assert.equal(harness.zotero.availablePDFCalls.length, 0);
});

test("one item failure does not stop the next item", async () => {
  const request = await job({
    items: [{
      task_id: "paper-0001",
      doi: "10.1000/error",
      title: "Broken Search",
      authors: "Smith, J.",
      year: "2025",
    }, {
      task_id: "paper-0002",
      doi: "10.1000/good",
      title: "Good Paper",
      authors: "Jones, J.",
      year: "2024",
    }],
  });
  const collectionID = 701;
  const harness = await makeHarness({
    requests: [request],
    zoteroOptions: {
      collections: [{ id: collectionID, libraryID: 1, name: request.collection_name }],
      searchErrors: { "10.1000/error": "download_failed" },
      items: [{
        id: 120,
        libraryID: 1,
        doi: "10.1000/good",
        title: "Good Paper",
        firstCreator: "Jones",
        year: "2024",
        collections: [collectionID],
        attachments: [{
          id: 220,
          contentType: "application/pdf",
          path: "C:\\Zotero\\storage\\GOOD\\paper.pdf",
        }],
      }],
    },
  });

  await harness.runtime.scanNow();

  assert.deepEqual(harness.results()[0].rows.map(row => row.status), [
    "download_failed",
    "existing_pdf",
  ]);
});

test("no available PDF returns no_pdf after exactly one attempt", async () => {
  const request = await job();
  const collectionID = 701;
  const harness = await makeHarness({
    requests: [request],
    zoteroOptions: {
      collections: [{ id: collectionID, libraryID: 1, name: request.collection_name }],
      items: [{
        id: 130,
        libraryID: 1,
        doi: request.items[0].doi,
        title: request.items[0].title,
        firstCreator: "Smith",
        year: "2025",
        collections: [collectionID],
        attachments: [],
      }],
    },
  });

  await harness.runtime.scanNow();

  assert.equal(harness.results()[0].rows[0].status, "no_pdf");
  assert.equal(harness.results()[0].rows[0].reason, "no_available_pdf");
  assert.deepEqual(harness.zotero.availablePDFCalls, [130]);
});

test("URL, relative, and non-PDF attachments are never reported as existing PDFs", async () => {
  const request = await job();
  const collectionID = 701;
  const harness = await makeHarness({
    requests: [request],
    zoteroOptions: {
      collections: [{ id: collectionID, libraryID: 1, name: request.collection_name }],
      items: [{
        id: 131,
        libraryID: 1,
        doi: request.items[0].doi,
        title: request.items[0].title,
        firstCreator: "Smith",
        year: "2025",
        collections: [collectionID],
        attachments: [{
          id: 231,
          contentType: "application/pdf",
          path: "https://example.invalid/paper.pdf",
        }, {
          id: 232,
          contentType: "application/pdf",
          path: "relative\\paper.pdf",
        }, {
          id: 233,
          contentType: "text/html",
          path: "C:\\Zotero\\storage\\HTML\\paper.pdf",
        }],
      }],
      availablePDFByItemID: {
        131: {
          id: 234,
          contentType: "application/pdf",
          path: "C:\\Zotero\\storage\\VALID\\paper.pdf",
        },
      },
    },
  });

  await harness.runtime.scanNow();

  const row = harness.results()[0].rows[0];
  assert.equal(row.status, "downloaded");
  assert.equal(row.attachment_path, "C:\\Zotero\\storage\\VALID\\paper.pdf");
  assert.deepEqual(harness.zotero.availablePDFCalls, [131]);
});

test("missing available-PDF API fails before every Zotero item write", async () => {
  const request = await job();
  const harness = await makeHarness({
    requests: [request],
    zoteroOptions: { availablePDFAPI: false },
  });

  await harness.runtime.scanNow();

  assert.equal(harness.results()[0].rows[0].status, "zotero_api_unavailable");
  assert.equal(harness.zotero.writeCalls.length, 0);
  assert.equal(harness.zotero.searchCalls.length, 0);
  assert.equal(harness.zotero.importCalls.length, 0);
  assert.equal(harness.zotero.availablePDFCalls.length, 0);
});
