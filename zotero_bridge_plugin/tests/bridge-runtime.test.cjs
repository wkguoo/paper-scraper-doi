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

async function makeHarness({ requests = [], confirm = true } = {}) {
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
  const zotero = {
    pluginVersion: "0.1.0-test",
    version: "9.0.6-test",
    writeCalls: [],
    async getLibraryName(libraryID) {
      return libraryID === 1 ? "我的文库" : `文库 ${libraryID}`;
    },
    reportError(error) {
      errors.push(error);
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
