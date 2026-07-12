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

function undoState() {
  return {
    schema_version: 1,
    runs: {
      "run-undo": {
        job_ids: [JOB_IDS[0]],
        payload_sha256: ["a".repeat(64)],
        confirmed_at: "2026-07-11T09:00:00.000Z",
        completed: true,
      },
    },
    last_undo: {
      run_id: "run-undo",
      library_id: 1,
      collection_id: 77,
      collection_name: "Codex下载回退_undo",
      job_ids: [JOB_IDS[0]],
      payload_sha256: ["a".repeat(64)],
      created_item_ids: [901],
      created_attachment_ids: [902],
      added_memberships: [[304, 77]],
      preexisting_item_ids: [304],
      preexisting_attachment_ids: [305],
      total_count: 2,
      success_count: 2,
      failure_count: 0,
      completed_at: "2026-07-11T09:30:00.000Z",
      undo_started_at: null,
      undo_progress: null,
      undone: false,
      undo_result: null,
    },
  };
}

function undoItems() {
  return [{
    id: 304,
    libraryID: 1,
    doi: "10.1000/preexisting",
    title: "Preexisting Item",
    firstCreator: "Smith",
    year: "2025",
    collections: [77],
    attachments: [{
      id: 305,
      libraryID: 1,
      parentItemID: 304,
      contentType: "application/pdf",
      path: "C:\\Zotero\\storage\\PREEXISTING\\paper.pdf",
    }, {
      id: 902,
      libraryID: 1,
      parentItemID: 304,
      contentType: "application/pdf",
      path: "C:\\Zotero\\storage\\CREATED\\paper.pdf",
    }],
  }, {
    id: 901,
    libraryID: 1,
    doi: "10.1000/created",
    title: "Created Item",
    firstCreator: "Jones",
    year: "2025",
    collections: [77],
    attachments: [],
  }];
}

function normalizePath(value) {
  return String(value).replaceAll("\\", "/").replace(/\/+$/u, "");
}

function createMemoryIO(sharedFiles = null) {
  const files = sharedFiles || new Map();
  const directories = new Set();
  const operations = [];
  const audit = { lists: [], reads: [] };

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
    audit,
    join,
    basename,
    async makeDir(path) {
      directories.add(normalizePath(path));
    },
    async list(path) {
      const directory = normalizePath(path);
      audit.lists.push(directory);
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
      audit.reads.push(normalized);
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

async function makeHarness({
  requests = [],
  confirm = true,
  undoConfirm = true,
  zoteroOptions = {},
  sharedFiles = null,
  sharedZotero = null,
  crashAfter = null,
  crashAfterCancellationMarker = false,
  crashAfterUndoStart = false,
  crashAfterLedgerWrite = null,
  crashAfterCollectionMarker = false,
  crashAfterArchivedRequest = false,
  runConfirmationBarrier = null,
  initialState = null,
} = {}) {
  const io = createMemoryIO(sharedFiles);
  let crashTriggered = false;
  if (Number.isInteger(crashAfter) && crashAfter >= 0) {
    const replaceUTF8 = io.replaceUTF8.bind(io);
    io.replaceUTF8 = async (path, text, temporaryPath) => {
      await replaceUTF8(path, text, temporaryPath);
      if (
        !crashTriggered
        && path.endsWith(".progress.json")
        && JSON.parse(text).rows.length === crashAfter
      ) {
        crashTriggered = true;
        throw new Error("fixture_crash");
      }
    };
  }
  if (crashAfterCancellationMarker) {
    const move = io.move.bind(io);
    let cancellationCrashTriggered = false;
    io.move = async (source, target, options) => {
      await move(source, target, options);
      if (!cancellationCrashTriggered && target.endsWith(".cancelled.json")) {
        cancellationCrashTriggered = true;
        throw new Error("fixture_cancel_crash");
      }
    };
  }
  if (crashAfterUndoStart) {
    const replaceUTF8 = io.replaceUTF8.bind(io);
    let undoCrashTriggered = false;
    io.replaceUTF8 = async (path, text, temporaryPath) => {
      await replaceUTF8(path, text, temporaryPath);
      const value = JSON.parse(text);
      if (
        !undoCrashTriggered
        && path.endsWith("plugin-state.json")
        && value.last_undo?.undo_started_at
        && value.last_undo.undone === false
      ) {
        undoCrashTriggered = true;
        throw new Error("fixture_undo_crash");
      }
    };
  }
  if (crashAfterLedgerWrite) {
    const replaceUTF8 = io.replaceUTF8.bind(io);
    let ledgerCrashTriggered = false;
    io.replaceUTF8 = async (path, text, temporaryPath) => {
      await replaceUTF8(path, text, temporaryPath);
      if (ledgerCrashTriggered || !path.endsWith(".progress.json")) return;
      const value = JSON.parse(text);
      const shouldCrash = (
        crashAfterLedgerWrite === "item"
          ? value.created_item_ids.length > 0
          : crashAfterLedgerWrite === "membership"
            ? value.created_item_ids.length === 0 && value.added_memberships.length > 0
            : crashAfterLedgerWrite === "attachment"
              ? value.created_attachment_ids.length > 0
              : false
      );
      if (shouldCrash) {
        ledgerCrashTriggered = true;
        throw new Error("fixture_ledger_crash");
      }
    };
  }
  if (crashAfterCollectionMarker) {
    const replaceUTF8 = io.replaceUTF8.bind(io);
    let collectionCrashTriggered = false;
    io.replaceUTF8 = async (path, text, temporaryPath) => {
      await replaceUTF8(path, text, temporaryPath);
      if (
        !collectionCrashTriggered
        && path.endsWith(".collection.json")
        && JSON.parse(text).phase === "complete"
      ) {
        collectionCrashTriggered = true;
        throw new Error("fixture_collection_crash");
      }
    };
  }
  if (crashAfterArchivedRequest) {
    const move = io.move.bind(io);
    let archiveCrashTriggered = false;
    io.move = async (source, target, options) => {
      await move(source, target, options);
      const name = String(target).replaceAll("\\", "/").split("/").at(-1);
      if (
        !archiveCrashTriggered
        && target.includes("/archive/")
        && /^[0-9a-f-]{36}\.json$/.test(name)
      ) {
        archiveCrashTriggered = true;
        throw new Error("fixture_archive_crash");
      }
    };
  }
  const prompt = {
    calls: [],
    alerts: [],
    async confirm(details) {
      this.calls.push(details);
      if (details.kind !== "undo" && runConfirmationBarrier) {
        await runConfirmationBarrier;
      }
      return details.kind === "undo" ? undoConfirm : confirm;
    },
    alert(title, message) {
      this.alerts.push({ title, message });
    },
  };
  const errors = [];
  let undoWriteCrashTriggered = false;
  let zoteroWriteCrashTriggered = false;
  let zoteroPreWriteCrashTriggered = false;
  function maybeCrashBeforeZoteroWrite(kind) {
    if (
      zoteroOptions.crashBeforeZoteroWrite === kind
      && !zoteroPreWriteCrashTriggered
    ) {
      zoteroPreWriteCrashTriggered = true;
      const error = new Error(`fixture_${kind}_pre_write_crash`);
      error.bridgeFatal = true;
      throw error;
    }
  }
  function maybeCrashAfterZoteroWrite(kind) {
    if (
      zoteroOptions.crashAfterZoteroWrite === kind
      && !zoteroWriteCrashTriggered
    ) {
      zoteroWriteCrashTriggered = true;
      const error = new Error(`fixture_${kind}_write_crash`);
      error.bridgeFatal = true;
      throw error;
    }
  }
  const items = (zoteroOptions.items || []).map(value => ({
    ...value,
    attachments: (value.attachments || []).map(attachment => ({ ...attachment })),
    collections: [...(value.collections || [])],
  }));
  const collections = (zoteroOptions.collections || []).map(value => ({ ...value }));
  let nextItemID = Math.max(1000, ...items.map(item => Number(item.id) || 0)) + 1;
  let nextCollectionID = Math.max(700, ...collections.map(value => Number(value.id) || 0)) + 1;
  const createdZotero = {
    pluginVersion: "0.1.0-test",
    version: "9.0.6-test",
    writeCalls: [],
    searchCalls: [],
    importCalls: [],
    collectionCalls: [],
    collectionLookupCalls: [],
    membershipCalls: [],
    availablePDFCalls: [],
    processingAPICalls: [],
    deletedIDs: [],
    removedMemberships: [],
    items,
    collections,
    getInstanceIdentity() {
      if (zoteroOptions.instanceIdentity) {
        return { ...zoteroOptions.instanceIdentity };
      }
      return {
        instance_id: "test-data-dir-fixture",
        data_dir: "D:\\Zotero-Fixture-Data",
        profile_dir: "C:\\Profiles\\fixture.default",
        profile_name: "fixture.default",
        zotero_version: "9.0.6-test",
        plugin_version: "0.1.0-test",
      };
    },
    async getLibraryName(libraryID) {
      return libraryID === 1 ? "我的文库" : `文库 ${libraryID}`;
    },
    reportError(error) {
      errors.push(error);
    },
    async assertProcessingAPI() {
      this.processingAPICalls.push(1);
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
    async findCollectionByName(libraryID, name) {
      this.collectionCalls.push({ libraryID, name });
      const matches = this.collections.filter(collection => (
        collection.libraryID === libraryID
        && collection.name === name
        && collection.deleted !== true
      ));
      if (matches.length > 1) throw new Error("metadata_uncertain");
      return matches.length === 1 ? matches[0] : null;
    },
    async createCollection(libraryID, name) {
      const collection = { id: nextCollectionID++, libraryID, name, deleted: false };
      this.collections.push(collection);
      this.writeCalls.push({ type: "create_collection", id: collection.id });
      maybeCrashAfterZoteroWrite("collection");
      return collection;
    },
    async getCollectionByID(libraryID, collectionID) {
      this.collectionLookupCalls.push({ libraryID, collectionID });
      return this.collections.find(collection => (
        collection.id === collectionID
        && collection.libraryID === libraryID
        && collection.deleted !== true
      )) || null;
    },
    async translateByDOI(doi, libraryID, collectionID, beforeWrite = null) {
      this.importCalls.push({ doi, libraryID, collectionID, saveAttachments: false });
      const configuredError = zoteroOptions.importErrors?.[doi];
      if (configuredError) throw new Error(configuredError);
      const configured = zoteroOptions.translationsByDOI?.[doi];
      if (!configured) return [];
      if (typeof beforeWrite === "function") await beforeWrite();
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
      maybeCrashAfterZoteroWrite("item");
      return translated;
    },
    async hasCollectionMembership(item, collectionID) {
      return (item.collections || []).includes(collectionID);
    },
    async addToCollection(item, collectionID, beforeWrite = null) {
      this.membershipCalls.push({ itemID: item.id, collectionID });
      item.collections ||= [];
      if (item.collections.includes(collectionID)) return false;
      if (typeof beforeWrite === "function") await beforeWrite();
      maybeCrashBeforeZoteroWrite("membership");
      item.collections.push(collectionID);
      this.writeCalls.push({ type: "add_membership", itemID: item.id, collectionID });
      maybeCrashAfterZoteroWrite("membership");
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
      maybeCrashAfterZoteroWrite("attachment");
      return attachment;
    },
    async assertUndoAPI() {},
    async removeMembershipIfOwned(itemID, collectionID, libraryID) {
      const item = this.items.find(value => value.id === itemID);
      if (
        !item
        || item.libraryID !== libraryID
        || item.regular === false
        || item.feed === true
        || item.deleted === true
        || !(item.collections || []).includes(collectionID)
      ) {
        return false;
      }
      item.collections = item.collections.filter(id => id !== collectionID);
      this.removedMemberships.push([itemID, collectionID]);
      this.writeCalls.push({ type: "remove_membership", itemID, collectionID });
      if (
        zoteroOptions.crashAfterUndoWrite === "membership"
        && !undoWriteCrashTriggered
      ) {
        undoWriteCrashTriggered = true;
        const error = new Error("fixture_undo_write_crash");
        error.bridgeFatal = true;
        throw error;
      }
      return true;
    },
    async eraseCreatedObject(id, kind, libraryID, identity) {
      if (kind === "attachment") {
        for (const parent of this.items) {
          const attachmentIndex = (parent.attachments || []).findIndex(value => value.id === id);
          if (attachmentIndex === -1) continue;
          const attachment = parent.attachments[attachmentIndex];
          if (
            attachment.libraryID !== libraryID
            || attachment.parentItemID !== parent.id
            || !identity.batchItemIDs.includes(parent.id)
          ) {
            return false;
          }
          parent.attachments.splice(attachmentIndex, 1);
          this.deletedIDs.push(id);
          this.writeCalls.push({ type: "erase_attachment", id });
          return true;
        }
        return false;
      }
      const itemIndex = this.items.findIndex(value => value.id === id);
      if (itemIndex === -1) return false;
      const item = this.items[itemIndex];
      if (
        item.libraryID !== libraryID
        || item.regular === false
        || item.feed === true
        || item.deleted === true
        || !Number.isInteger(identity.collectionID)
        || !(item.collections || []).includes(identity.collectionID)
      ) {
        return false;
      }
      this.items.splice(itemIndex, 1);
      this.deletedIDs.push(id);
      this.writeCalls.push({ type: "erase_item", id });
      return true;
    },
  };
  const zotero = sharedZotero || createdZotero;
  zotero.reportError = error => errors.push(error);
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

  if (initialState) {
    io.files.set(paths.state, `${JSON.stringify(initialState)}\n`);
  }

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
    files: io.files,
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
  assert.match(harness.prompt.calls[0].message, /当前打开的这个 Zotero/);
  assert.match(harness.prompt.calls[0].message, /数据目录=/);
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
    activeInstance: "C:/LocalAppData/PaperScraperDOI/zotero-bridge/v1/active-instance.json",
    consumerLease: "C:/LocalAppData/PaperScraperDOI/zotero-bridge/v1/consumer-lease.json",
  });
});

test("publishes active-instance for the open Zotero and blocks a second instance", async () => {
  const sharedFiles = new Map();
  const first = await makeHarness({
    sharedFiles,
    zoteroOptions: {
      instanceIdentity: {
        instance_id: "main-zeterofiles",
        data_dir: "D:\\zeterofiles",
        profile_dir: "C:\\Profiles\\g39b695l.default",
        profile_name: "g39b695l.default",
        zotero_version: "9.0.6",
        plugin_version: "0.1.9",
      },
    },
  });
  const firstScan = await first.runtime.scanNow();
  assert.equal(firstScan.status, "scanned");
  assert.ok(sharedFiles.has(first.paths.activeInstance));
  const active = JSON.parse(sharedFiles.get(first.paths.activeInstance));
  assert.equal(active.data_dir, "D:\\zeterofiles");
  assert.equal(active.profile_name, "g39b695l.default");
  assert.ok(sharedFiles.has(first.paths.consumerLease));

  const second = await makeHarness({
    sharedFiles,
    zoteroOptions: {
      instanceIdentity: {
        instance_id: "test-zotero-test-data",
        data_dir: "D:\\Zotero-Test-Data",
        profile_dir: "C:\\Profiles\\elpj7iql.Zotero test",
        profile_name: "elpj7iql.Zotero test",
        zotero_version: "9.0.6",
        plugin_version: "0.1.9",
      },
    },
  });
  const secondScan = await second.runtime.scanNow();
  assert.equal(secondScan.status, "another_instance_active");
  // Lease holder (main) remains the published active target.
  const stillActive = JSON.parse(sharedFiles.get(first.paths.activeInstance));
  assert.equal(stillActive.instance_id, "main-zeterofiles");
  assert.equal(stillActive.data_dir, "D:\\zeterofiles");
});

test("idle polling never enumerates or rereads the historical archive", async () => {
  const harness = await makeHarness();
  const markerPath = harness.io.join(
    harness.paths.archive,
    `${JOB_IDS[0]}.cancelled.json`,
  );
  harness.files.set(markerPath, JSON.stringify({
    schema_version: 1,
    run_id: "historical-cancelled-run",
    job_ids: [JOB_IDS[0]],
    payload_sha256: ["a".repeat(64)],
    cancelled_at: "2026-07-11T09:00:00.000Z",
  }));
  harness.io.audit.lists.length = 0;
  harness.io.audit.reads.length = 0;

  await harness.runtime.scanNow();
  await harness.runtime.scanNow();
  await harness.runtime.scanNow();

  assert.equal(
    harness.io.audit.lists.filter(path => path === harness.paths.archive).length,
    0,
  );
  assert.equal(harness.io.audit.reads.includes(markerPath), false);
});

test("does not prompt for an incomplete declared run", async () => {
  const first = await job({ number: 1, chunkIndex: 1, chunkCount: 2 });
  const second = await job({ number: 2, chunkIndex: 2, chunkCount: 2 });
  const harness = await makeHarness({ requests: [first] });

  await harness.runtime.scanNow();
  assert.equal(harness.prompt.calls.length, 0);
  assert.equal((await harness.io.list(harness.paths.inbox)).length, 1);
  assert.equal((await harness.io.list(harness.paths.processing)).length, 0);
  assert.match(harness.runtime.showStatus(), /状态：等待分块/);
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
  const archived = await harness.io.list(harness.paths.archive);
  assert.equal(archived.some(path => path.endsWith(`${request.job_id}.json`)), true);
  assert.equal(archived.some(path => path.endsWith(".cancelled.json")), true);
});

test("restart completes a durably marked cancellation without prompting or writing", async () => {
  const request = await job();
  const first = await makeHarness({
    requests: [request],
    confirm: false,
    crashAfterCancellationMarker: true,
  });

  await first.runtime.scanNow();

  assert.equal(first.prompt.calls.length, 1);
  assert.equal(first.results().length, 0);
  assert.equal(first.zotero.writeCalls.length, 0);
  assert.equal(first.errors.some(error => error.code === "fixture_cancel_crash"), true);
  assert.equal(Array.from(first.files.keys()).some(path => path.endsWith(".cancelled.json")), true);

  const second = await makeHarness({
    sharedFiles: first.files,
    sharedZotero: first.zotero,
    confirm: true,
  });
  await second.runtime.scanNow();

  assert.equal(first.prompt.calls.length + second.prompt.calls.length, 1);
  assert.equal(second.zotero.writeCalls.length, 0);
  assert.equal(second.results()[0].rows[0].status, "user_cancelled");
  assert.equal((await second.io.list(second.paths.archive)).some(path => (
    path.endsWith(".cancelled.json")
  )), true);
});

test("restart completes a multi-chunk cancellation interrupted during request archiving", async () => {
  const firstRequest = await job({
    number: 1,
    runID: "run-cancel-archive-recovery",
    chunkIndex: 1,
    chunkCount: 2,
  });
  const secondRequest = await job({
    number: 2,
    runID: "run-cancel-archive-recovery",
    chunkIndex: 2,
    chunkCount: 2,
  });
  const first = await makeHarness({
    requests: [firstRequest, secondRequest],
    confirm: false,
    crashAfterArchivedRequest: true,
  });

  await first.runtime.scanNow();

  assert.equal(first.prompt.calls.length, 1);
  assert.equal(first.zotero.writeCalls.length, 0);
  assert.equal(first.errors.some(error => error.code === "fixture_archive_crash"), true);
  const processingAfterCrash = (await first.io.list(first.paths.processing)).filter(path => (
    /^[0-9a-f-]{36}\.json$/.test(first.io.basename(path))
  ));
  const archivedAfterCrash = (await first.io.list(first.paths.archive)).filter(path => (
    /^[0-9a-f-]{36}\.json$/.test(first.io.basename(path))
  ));
  assert.equal(processingAfterCrash.length, 1);
  assert.equal(archivedAfterCrash.length, 1);

  const second = await makeHarness({
    sharedFiles: first.files,
    sharedZotero: first.zotero,
    confirm: true,
  });
  const outcome = await second.runtime.scanNow();

  const processingAfterRestart = (await second.io.list(second.paths.processing)).filter(path => (
    /^[0-9a-f-]{36}\.json$/.test(second.io.basename(path))
  ));
  const archivedAfterRestart = (await second.io.list(second.paths.archive)).filter(path => (
    /^[0-9a-f-]{36}\.json$/.test(second.io.basename(path))
  ));
  assert.equal(outcome.completeRuns, 1);
  assert.equal(outcome.incompleteRuns, 0);
  assert.equal(processingAfterRestart.length, 0);
  assert.equal(archivedAfterRestart.length, 2);
  assert.equal(first.prompt.calls.length + second.prompt.calls.length, 1);
  assert.equal(second.zotero.writeCalls.length, 0);
  assert.deepEqual(
    second.results().flatMap(result => result.rows.map(row => row.status)),
    ["user_cancelled", "user_cancelled"],
  );
});

test("old state with the same run id cannot block cancellation archive recovery", async () => {
  const runID = "run-cancel-reused-id";
  const firstRequest = await job({
    number: 1,
    runID,
    chunkIndex: 1,
    chunkCount: 2,
  });
  const secondRequest = await job({
    number: 2,
    runID,
    chunkIndex: 2,
    chunkCount: 2,
  });
  const first = await makeHarness({
    requests: [firstRequest, secondRequest],
    confirm: false,
    crashAfterArchivedRequest: true,
    initialState: {
      schema_version: 1,
      runs: {
        [runID]: {
          job_ids: [JOB_IDS[3]],
          payload_sha256: ["b".repeat(64)],
          confirmed_at: "2026-07-11T08:00:00.000Z",
          completed: true,
        },
      },
      last_undo: null,
    },
  });

  await first.runtime.scanNow();
  assert.equal(first.errors.some(error => error.code === "fixture_archive_crash"), true);

  const second = await makeHarness({
    sharedFiles: first.files,
    sharedZotero: first.zotero,
  });
  const outcome = await second.runtime.scanNow();

  assert.equal(outcome.completeRuns, 1);
  assert.equal(outcome.incompleteRuns, 0);
  assert.equal(first.prompt.calls.length + second.prompt.calls.length, 1);
  assert.equal((await second.io.list(second.paths.processing)).filter(path => (
    /^[0-9a-f-]{36}\.json$/.test(second.io.basename(path))
  )).length, 0);
  assert.equal((await second.io.list(second.paths.archive)).filter(path => (
    /^[0-9a-f-]{36}\.json$/.test(second.io.basename(path))
  )).length, 2);
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

test("persists exact completion state and reuses confirmation only for identical jobs", async () => {
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
        completed: true,
      },
    },
    last_undo: {
      run_id: original.run_id,
      library_id: original.library_id,
      collection_id: 701,
      collection_name: original.collection_name,
      job_ids: [original.job_id],
      payload_sha256: [original.payload_sha256],
      created_item_ids: [],
      created_attachment_ids: [],
      added_memberships: [],
      preexisting_item_ids: [],
      preexisting_attachment_ids: [],
      total_count: 1,
      success_count: 0,
      failure_count: 1,
      completed_at: "2026-07-11T10:00:00.000Z",
      undo_started_at: null,
      undo_progress: null,
      undone: false,
      undo_result: null,
    },
  });

  harness.removeQueuedRequests();
  const changed = await job({ number: 2 });
  harness.addRequest(changed);
  await harness.runtime.scanNow();
  assert.equal(harness.prompt.calls.length, 2);
  const changedState = JSON.parse(await harness.io.readUTF8(harness.paths.state));
  assert.equal(changedState.runs[changed.run_id].completed, true);
  assert.deepEqual(changedState.last_undo.job_ids, [changed.job_id]);
  assert.deepEqual(changedState.last_undo.payload_sha256, [changed.payload_sha256]);
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

test("one scan preserves completion state for two independent runs", async () => {
  const first = await job({ number: 1, runID: "run-a" });
  const second = await job({ number: 2, runID: "run-b" });
  const harness = await makeHarness({
    requests: [first, second],
    zoteroOptions: { availablePDFAPI: false },
  });

  await harness.runtime.scanNow();

  const state = JSON.parse(await harness.io.readUTF8(harness.paths.state));
  assert.equal(state.runs["run-a"].completed, true);
  assert.equal(state.runs["run-b"].completed, true);
  assert.equal(harness.prompt.calls.length, 2);
});

test("restart completes a multi-chunk run interrupted during request archiving", async () => {
  const firstRequest = await job({
    number: 1,
    runID: "run-archive-recovery",
    chunkIndex: 1,
    chunkCount: 2,
  });
  const secondRequest = await job({
    number: 2,
    runID: "run-archive-recovery",
    chunkIndex: 2,
    chunkCount: 2,
  });
  const first = await makeHarness({
    requests: [firstRequest, secondRequest],
    crashAfterArchivedRequest: true,
    zoteroOptions: { availablePDFAPI: false },
  });

  await first.runtime.scanNow();

  assert.equal(first.errors.some(error => error.code === "fixture_archive_crash"), true);
  const processingAfterCrash = (await first.io.list(first.paths.processing)).filter(path => (
    /^[0-9a-f-]{36}\.json$/.test(first.io.basename(path))
  ));
  const archivedAfterCrash = (await first.io.list(first.paths.archive)).filter(path => (
    /^[0-9a-f-]{36}\.json$/.test(first.io.basename(path))
  ));
  assert.equal(processingAfterCrash.length, 1);
  assert.equal(archivedAfterCrash.length, 1);

  const second = await makeHarness({
    sharedFiles: first.files,
    sharedZotero: first.zotero,
  });
  await second.runtime.scanNow();

  const processingAfterRestart = (await second.io.list(second.paths.processing)).filter(path => (
    /^[0-9a-f-]{36}\.json$/.test(second.io.basename(path))
  ));
  const archivedAfterRestart = (await second.io.list(second.paths.archive)).filter(path => (
    /^[0-9a-f-]{36}\.json$/.test(second.io.basename(path))
  ));
  assert.equal(processingAfterRestart.length, 0);
  assert.equal(archivedAfterRestart.length, 2);
  assert.equal(first.prompt.calls.length + second.prompt.calls.length, 1);
  const state = JSON.parse(await second.io.readUTF8(second.paths.state));
  assert.equal(state.runs["run-archive-recovery"].completed, true);
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
  const state = JSON.parse(await harness.io.readUTF8(harness.paths.state));
  assert.deepEqual(state.last_undo.created_item_ids, []);
  assert.deepEqual(state.last_undo.created_attachment_ids, []);
  assert.deepEqual(state.last_undo.added_memberships, [[101, collectionID]]);
  assert.deepEqual(state.last_undo.preexisting_item_ids, [101]);
  assert.deepEqual(state.last_undo.preexisting_attachment_ids, [201]);
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
  const state = JSON.parse(await harness.io.readUTF8(harness.paths.state));
  assert.deepEqual(state.last_undo.created_attachment_ids, [202]);
  assert.deepEqual(state.last_undo.added_memberships, [[102, collectionID]]);
  assert.deepEqual(state.last_undo.preexisting_item_ids, [102]);
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
  const state = JSON.parse(await harness.io.readUTF8(harness.paths.state));
  assert.deepEqual(state.last_undo.created_item_ids, [103]);
  assert.deepEqual(state.last_undo.created_attachment_ids, [203]);
  assert.deepEqual(state.last_undo.added_memberships, [[103, collectionID]]);
  assert.deepEqual(state.last_undo.preexisting_item_ids, []);
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

test("restart resumes after the last completed task without a second prompt", async () => {
  const request = await job({
    items: [1, 2, 3].map(number => ({
      task_id: `paper-${String(number).padStart(4, "0")}`,
      doi: `10.1000/restart-${number}`,
      title: `Restart Paper ${number}`,
      authors: "Smith, J.",
      year: "2025",
    })),
  });
  const collectionID = 701;
  const first = await makeHarness({
    requests: [request],
    crashAfter: 1,
    zoteroOptions: {
      collections: [{ id: collectionID, libraryID: 1, name: request.collection_name }],
      items: [1, 2, 3].map(number => ({
        id: 500 + number,
        libraryID: 1,
        doi: `10.1000/restart-${number}`,
        title: `Restart Paper ${number}`,
        firstCreator: "Smith",
        year: "2025",
        collections: [collectionID],
        attachments: [],
      })),
      availablePDFByItemID: Object.fromEntries([1, 2, 3].map(number => [
        500 + number,
        {
          id: 600 + number,
          contentType: "application/pdf",
          path: `C:\\Zotero\\storage\\RESTART${number}\\paper.pdf`,
        },
      ])),
    },
  });

  await first.runtime.scanNow();

  assert.equal(first.results().length, 0);
  assert.equal(first.errors.some(error => error.code === "fixture_crash"), true);
  assert.deepEqual(first.zotero.availablePDFCalls, [501]);
  const progressName = `${request.job_id}.progress.json`;
  const processingProgress = first.io.join(first.paths.processing, progressName);
  const firstProgress = JSON.parse(await first.io.readUTF8(processingProgress));
  assert.deepEqual(Object.keys(firstProgress), [
    "schema_version",
    "job_id",
    "payload_sha256",
    "confirmed",
    "rows",
    "created_item_ids",
    "created_attachment_ids",
    "added_memberships",
    "pending_write",
  ]);
  assert.equal(firstProgress.rows.length, 1);

  const second = await makeHarness({
    sharedFiles: first.files,
    sharedZotero: first.zotero,
  });
  await second.runtime.scanNow();

  assert.equal(first.prompt.calls.length + second.prompt.calls.length, 1);
  assert.deepEqual(second.zotero.availablePDFCalls, [501, 502, 503]);
  assert.equal(second.zotero.availablePDFCalls.filter(id => id === 501).length, 1);
  assert.equal(second.results()[0].rows.length, 3);
  assert.deepEqual(second.results()[0].rows.map(row => row.status), [
    "downloaded",
    "downloaded",
    "downloaded",
  ]);
  assert.equal(await second.io.exists(processingProgress), false);
  assert.equal(
    await second.io.exists(second.io.join(second.paths.archive, progressName)),
    true,
  );
  const completedState = JSON.parse(await second.io.readUTF8(second.paths.state));
  assert.equal(completedState.runs[request.run_id].completed, true);
});

test("collection creation is durably ledgered and reused after restart", async () => {
  const request = await job();
  const first = await makeHarness({
    requests: [request],
    crashAfterCollectionMarker: true,
    zoteroOptions: {
      items: [{
        id: 601,
        libraryID: 1,
        doi: request.items[0].doi,
        title: request.items[0].title,
        firstCreator: "Smith",
        year: "2025",
        collections: [],
        attachments: [],
      }],
    },
  });

  await first.runtime.scanNow();

  assert.equal(first.results().length, 0);
  assert.equal(first.errors.some(error => error.code === "fixture_collection_crash"), true);
  assert.equal(first.zotero.writeCalls.filter(call => call.type === "create_collection").length, 1);
  const markerName = `${request.job_id}.collection.json`;
  const markerPath = first.io.join(first.paths.processing, markerName);
  const marker = JSON.parse(await first.io.readUTF8(markerPath));
  assert.deepEqual(Object.keys(marker), [
    "schema_version",
    "run_id",
    "job_ids",
    "payload_sha256",
    "library_id",
    "collection_id",
    "collection_name",
    "created",
    "phase",
    "recorded_at",
  ]);
  assert.equal(marker.created, true);
  assert.equal(marker.collection_id, 701);

  const second = await makeHarness({
    sharedFiles: first.files,
    sharedZotero: first.zotero,
  });
  await second.runtime.scanNow();

  assert.equal(second.zotero.writeCalls.filter(call => call.type === "create_collection").length, 1);
  assert.deepEqual(second.zotero.collectionLookupCalls, [{ libraryID: 1, collectionID: 701 }]);
  assert.equal(second.results()[0].rows[0].status, "no_pdf");
  assert.equal(await second.io.exists(markerPath), false);
  assert.equal(await second.io.exists(second.io.join(second.paths.archive, markerName)), true);
});

test("restart after an imported-item checkpoint does not import the item twice", async () => {
  const request = await job();
  const doi = core.normalizeDOI(request.items[0].doi);
  const first = await makeHarness({
    requests: [request],
    crashAfterLedgerWrite: "item",
    zoteroOptions: {
      collections: [{ id: 701, libraryID: 1, name: request.collection_name }],
      translationsByDOI: {
        [doi]: {
          id: 610,
          doi,
          title: request.items[0].title,
          firstCreator: "Smith",
          year: "2025",
        },
      },
    },
  });

  await first.runtime.scanNow();

  assert.equal(first.results().length, 0);
  assert.equal(first.errors.some(error => error.code === "fixture_ledger_crash"), true);
  assert.equal(first.zotero.importCalls.length, 1);
  const progressPath = first.io.join(
    first.paths.processing,
    `${request.job_id}.progress.json`,
  );
  const checkpoint = JSON.parse(await first.io.readUTF8(progressPath));
  assert.deepEqual(checkpoint.created_item_ids, [610]);
  assert.deepEqual(checkpoint.added_memberships, [[610, 701]]);
  assert.deepEqual(checkpoint.rows, []);

  const second = await makeHarness({
    sharedFiles: first.files,
    sharedZotero: first.zotero,
  });
  await second.runtime.scanNow();

  assert.equal(second.zotero.importCalls.length, 1);
  assert.deepEqual(second.zotero.availablePDFCalls, [610]);
  assert.equal(second.results()[0].rows[0].status, "no_pdf");
});

test("restart after a membership checkpoint does not add the membership twice", async () => {
  const request = await job();
  const first = await makeHarness({
    requests: [request],
    crashAfterLedgerWrite: "membership",
    zoteroOptions: {
      collections: [{ id: 702, libraryID: 1, name: request.collection_name }],
      items: [{
        id: 620,
        libraryID: 1,
        doi: request.items[0].doi,
        title: request.items[0].title,
        firstCreator: "Smith",
        year: "2025",
        collections: [],
        attachments: [],
      }],
    },
  });

  await first.runtime.scanNow();

  assert.equal(first.results().length, 0);
  assert.equal(first.errors.some(error => error.code === "fixture_ledger_crash"), true);
  assert.equal(first.zotero.writeCalls.filter(call => call.type === "add_membership").length, 1);

  const second = await makeHarness({
    sharedFiles: first.files,
    sharedZotero: first.zotero,
  });
  await second.runtime.scanNow();

  assert.equal(second.zotero.writeCalls.filter(call => call.type === "add_membership").length, 1);
  assert.deepEqual(second.zotero.availablePDFCalls, [620]);
  assert.equal(second.results()[0].rows[0].status, "no_pdf");
});

test("restart after an attachment checkpoint does not request the PDF twice", async () => {
  const request = await job();
  const first = await makeHarness({
    requests: [request],
    crashAfterLedgerWrite: "attachment",
    zoteroOptions: {
      collections: [{ id: 703, libraryID: 1, name: request.collection_name }],
      items: [{
        id: 630,
        libraryID: 1,
        doi: request.items[0].doi,
        title: request.items[0].title,
        firstCreator: "Smith",
        year: "2025",
        collections: [],
        attachments: [],
      }],
      availablePDFByItemID: {
        630: {
          id: 631,
          contentType: "application/pdf",
          path: "C:\\Zotero\\storage\\CHECKPOINT\\paper.pdf",
        },
      },
    },
  });

  await first.runtime.scanNow();

  assert.equal(first.results().length, 0);
  assert.equal(first.errors.some(error => error.code === "fixture_ledger_crash"), true);
  assert.deepEqual(first.zotero.availablePDFCalls, [630]);
  const progressPath = first.io.join(
    first.paths.processing,
    `${request.job_id}.progress.json`,
  );
  const checkpoint = JSON.parse(await first.io.readUTF8(progressPath));
  assert.deepEqual(checkpoint.created_attachment_ids, [631]);
  assert.deepEqual(checkpoint.rows, []);

  const second = await makeHarness({
    sharedFiles: first.files,
    sharedZotero: first.zotero,
  });
  await second.runtime.scanNow();

  assert.deepEqual(second.zotero.availablePDFCalls, [630]);
  assert.equal(second.results()[0].rows[0].status, "existing_pdf");
  const state = JSON.parse(await second.io.readUTF8(second.paths.state));
  assert.deepEqual(state.last_undo.created_attachment_ids, [631]);
  assert.deepEqual(state.last_undo.preexisting_attachment_ids, []);

  const undo = await second.runtime.undoLastBatch();
  assert.equal(undo.status, "undone");
  assert.equal(second.zotero.deletedIDs.includes(631), true);
});

test("an uncertain collection write is not recreated or claimed after restart", async () => {
  const request = await job();
  const first = await makeHarness({
    requests: [request],
    zoteroOptions: {
      crashAfterZoteroWrite: "collection",
      items: [{
        id: 640,
        libraryID: 1,
        doi: request.items[0].doi,
        title: request.items[0].title,
        firstCreator: "Smith",
        year: "2025",
        collections: [],
        attachments: [],
      }],
    },
  });

  await first.runtime.scanNow();

  assert.equal(first.results().length, 0);
  assert.equal(first.zotero.writeCalls.filter(call => call.type === "create_collection").length, 1);

  const second = await makeHarness({
    sharedFiles: first.files,
    sharedZotero: first.zotero,
  });
  await second.runtime.scanNow();

  assert.equal(first.prompt.calls.length + second.prompt.calls.length, 1);
  assert.equal(second.zotero.writeCalls.filter(call => call.type === "create_collection").length, 1);
  assert.equal(second.results()[0].rows[0].status, "plugin_error");
  assert.equal(second.results()[0].rows[0].reason, "write_outcome_uncertain");
  const markerPath = (await second.io.list(second.paths.archive)).find(path => (
    path.endsWith(".collection.json")
  ));
  const marker = JSON.parse(await second.io.readUTF8(markerPath));
  assert.equal(marker.phase, "pending");
  assert.equal(marker.created, null);
  assert.equal(marker.collection_id, null);
});

test("an uncertain import is not retried after its created item is externally removed", async () => {
  const request = await job();
  const doi = core.normalizeDOI(request.items[0].doi);
  const first = await makeHarness({
    requests: [request],
    zoteroOptions: {
      crashAfterZoteroWrite: "item",
      collections: [{ id: 704, libraryID: 1, name: request.collection_name }],
      translationsByDOI: {
        [doi]: {
          id: 650,
          doi,
          title: request.items[0].title,
          firstCreator: "Smith",
          year: "2025",
        },
      },
    },
  });

  await first.runtime.scanNow();
  assert.equal(first.results().length, 0);
  assert.equal(first.zotero.importCalls.length, 1);
  const preflightCallsAfterCrash = first.zotero.processingAPICalls.length;
  first.zotero.items = first.zotero.items.filter(item => item.id !== 650);

  const second = await makeHarness({
    sharedFiles: first.files,
    sharedZotero: first.zotero,
  });
  await second.runtime.scanNow();

  assert.equal(second.zotero.importCalls.length, 1);
  assert.equal(second.zotero.processingAPICalls.length, preflightCallsAfterCrash);
  assert.equal(second.results()[0].rows[0].status, "plugin_error");
  assert.equal(second.results()[0].rows[0].reason, "write_outcome_uncertain");
  const state = JSON.parse(await second.io.readUTF8(second.paths.state));
  assert.deepEqual(state.last_undo.created_item_ids, []);
  assert.deepEqual(state.last_undo.added_memberships, []);
  assert.deepEqual(state.last_undo.preexisting_item_ids, []);
});

test("an uncertain membership is not claimed when an external actor adds it", async () => {
  const request = await job();
  const first = await makeHarness({
    requests: [request],
    zoteroOptions: {
      crashBeforeZoteroWrite: "membership",
      collections: [{ id: 705, libraryID: 1, name: request.collection_name }],
      items: [{
        id: 660,
        libraryID: 1,
        doi: request.items[0].doi,
        title: request.items[0].title,
        firstCreator: "Smith",
        year: "2025",
        collections: [],
        attachments: [],
      }],
    },
  });

  await first.runtime.scanNow();
  assert.equal(first.results().length, 0);
  assert.equal(first.zotero.writeCalls.filter(call => call.type === "add_membership").length, 0);
  first.zotero.items.find(item => item.id === 660).collections.push(705);

  const second = await makeHarness({
    sharedFiles: first.files,
    sharedZotero: first.zotero,
  });
  await second.runtime.scanNow();

  assert.equal(second.zotero.writeCalls.filter(call => call.type === "add_membership").length, 0);
  assert.equal(second.results()[0].rows[0].status, "plugin_error");
  assert.equal(second.results()[0].rows[0].reason, "write_outcome_uncertain");
  const state = JSON.parse(await second.io.readUTF8(second.paths.state));
  assert.deepEqual(state.last_undo.added_memberships, []);
  assert.deepEqual(state.last_undo.preexisting_item_ids, []);
});

test("an uncertain attachment is not requested again after external removal", async () => {
  const request = await job();
  const first = await makeHarness({
    requests: [request],
    zoteroOptions: {
      crashAfterZoteroWrite: "attachment",
      collections: [{ id: 706, libraryID: 1, name: request.collection_name }],
      items: [{
        id: 670,
        libraryID: 1,
        doi: request.items[0].doi,
        title: request.items[0].title,
        firstCreator: "Smith",
        year: "2025",
        collections: [706],
        attachments: [],
      }],
      availablePDFByItemID: {
        670: {
          id: 671,
          contentType: "application/pdf",
          path: "C:\\Zotero\\storage\\WRITEAHEAD\\paper.pdf",
        },
      },
    },
  });

  await first.runtime.scanNow();
  assert.equal(first.results().length, 0);
  assert.deepEqual(first.zotero.availablePDFCalls, [670]);
  first.zotero.items.find(item => item.id === 670).attachments = [];

  const second = await makeHarness({
    sharedFiles: first.files,
    sharedZotero: first.zotero,
  });
  await second.runtime.scanNow();

  assert.deepEqual(second.zotero.availablePDFCalls, [670]);
  assert.equal(second.results()[0].rows[0].status, "plugin_error");
  assert.equal(second.results()[0].rows[0].reason, "write_outcome_uncertain");
  const state = JSON.parse(await second.io.readUTF8(second.paths.state));
  assert.deepEqual(state.last_undo.created_attachment_ids, []);
  assert.deepEqual(state.last_undo.preexisting_attachment_ids, []);
});

test("tampered progress is rejected without reprocessing or publishing a result", async () => {
  const request = await job();
  const collectionID = 701;
  const first = await makeHarness({
    requests: [request],
    crashAfter: 1,
    zoteroOptions: {
      collections: [{ id: collectionID, libraryID: 1, name: request.collection_name }],
      items: [{
        id: 801,
        libraryID: 1,
        doi: request.items[0].doi,
        title: request.items[0].title,
        firstCreator: "Smith",
        year: "2025",
        collections: [collectionID],
        attachments: [],
      }],
      availablePDFByItemID: {
        801: {
          id: 802,
          contentType: "application/pdf",
          path: "C:\\Zotero\\storage\\TAMPER\\paper.pdf",
        },
      },
    },
  });
  await first.runtime.scanNow();
  const progressPath = first.io.join(
    first.paths.processing,
    `${request.job_id}.progress.json`,
  );
  const progress = JSON.parse(await first.io.readUTF8(progressPath));
  progress.rows[0].task_id = "paper-tampered";
  first.files.set(progressPath, `${JSON.stringify(progress)}\n`);

  const second = await makeHarness({
    sharedFiles: first.files,
    sharedZotero: first.zotero,
  });
  await second.runtime.scanNow();

  assert.equal(second.errors.some(error => error.code === "bridge_progress_invalid"), true);
  assert.deepEqual(second.zotero.availablePDFCalls, [801]);
  assert.equal(second.results().length, 0);
  assert.equal((await second.io.list(second.paths.processing)).some(path => (
    path.endsWith(`${request.job_id}.json`)
  )), true);
});

test("completed replay validates and preserves the only published result", async () => {
  const request = await job();
  const collectionID = 701;
  const first = await makeHarness({
    requests: [request],
    zoteroOptions: {
      collections: [{ id: collectionID, libraryID: 1, name: request.collection_name }],
      items: [{
        id: 820,
        libraryID: 1,
        doi: request.items[0].doi,
        title: request.items[0].title,
        firstCreator: "Smith",
        year: "2025",
        collections: [collectionID],
        attachments: [],
      }],
      availablePDFByItemID: {
        820: {
          id: 821,
          contentType: "application/pdf",
          path: "C:\\Zotero\\storage\\REPLAY\\paper.pdf",
        },
      },
    },
  });
  await first.runtime.scanNow();
  const resultPath = first.io.join(first.paths.outbox, `${request.job_id}.result.json`);
  const resultBytes = first.files.get(resultPath);
  const requestName = `${request.job_id}.json`;
  const progressName = `${request.job_id}.progress.json`;
  await first.io.move(
    first.io.join(first.paths.archive, requestName),
    first.io.join(first.paths.processing, requestName),
    { noOverwrite: true },
  );
  await first.io.move(
    first.io.join(first.paths.archive, progressName),
    first.io.join(first.paths.processing, progressName),
    { noOverwrite: true },
  );
  const writesBeforeReplay = first.zotero.writeCalls.length;

  const second = await makeHarness({
    sharedFiles: first.files,
    sharedZotero: first.zotero,
  });
  await second.runtime.scanNow();

  assert.equal(second.prompt.calls.length, 0);
  assert.equal(second.zotero.writeCalls.length, writesBeforeReplay);
  assert.deepEqual(second.zotero.availablePDFCalls, [820]);
  assert.equal(second.files.get(resultPath), resultBytes);
  assert.equal(await second.io.exists(resultPath), true);
  assert.equal(await second.io.exists(second.io.join(second.paths.archive, requestName)), true);
  assert.equal(await second.io.exists(second.io.join(second.paths.archive, progressName)), true);
});

test("undo touches only IDs created or memberships added by the last batch", async () => {
  const harness = await makeHarness({
    initialState: undoState(),
    zoteroOptions: { items: undoItems() },
  });

  const outcome = await harness.runtime.undoLastBatch();

  assert.equal(outcome.status, "undone");
  assert.deepEqual(harness.zotero.removedMemberships, [[304, 77]]);
  assert.deepEqual(harness.zotero.deletedIDs, [902, 901]);
  assert.equal(harness.zotero.deletedIDs.includes(304), false);
  assert.equal(harness.zotero.deletedIDs.includes(305), false);
  assert.match(harness.prompt.calls[0].message, /新增条目：1/);
  assert.match(harness.prompt.calls[0].message, /新增附件：1/);
  assert.match(harness.prompt.calls[0].message, /集合成员关系：1/);

  const writesAfterFirstUndo = harness.zotero.writeCalls.length;
  const repeated = await harness.runtime.undoLastBatch();
  assert.equal(repeated.status, "already_undone");
  assert.equal(harness.zotero.writeCalls.length, writesAfterFirstUndo);
  const state = JSON.parse(await harness.io.readUTF8(harness.paths.state));
  assert.equal(state.last_undo.undone, true);
  assert.deepEqual(state.last_undo.undo_result, {
    finished_at: "2026-07-11T10:00:00.000Z",
    removed_memberships: [[304, 77]],
    deleted_attachment_ids: [902],
    deleted_item_ids: [901],
    skipped_ids: [],
  });
});

test("undo persists an in-progress marker before writes and resumes without another prompt", async () => {
  const first = await makeHarness({
    initialState: undoState(),
    crashAfterUndoStart: true,
    zoteroOptions: { items: undoItems() },
  });

  await assert.rejects(first.runtime.undoLastBatch(), /fixture_undo_crash/);

  assert.equal(first.prompt.calls.length, 1);
  assert.equal(first.zotero.writeCalls.length, 0);
  const interrupted = JSON.parse(await first.io.readUTF8(first.paths.state));
  assert.equal(interrupted.last_undo.undo_started_at, "2026-07-11T10:00:00.000Z");
  assert.equal(interrupted.last_undo.undone, false);
  assert.equal(interrupted.last_undo.undo_result, null);

  const second = await makeHarness({
    sharedFiles: first.files,
    sharedZotero: first.zotero,
  });
  const outcome = await second.runtime.undoLastBatch();

  assert.equal(second.prompt.calls.length, 0);
  assert.equal(outcome.status, "undone");
  assert.deepEqual(second.zotero.removedMemberships, [[304, 77]]);
  assert.deepEqual(second.zotero.deletedIDs, [902, 901]);
  const completed = JSON.parse(await second.io.readUTF8(second.paths.state));
  assert.equal(completed.last_undo.undo_started_at, "2026-07-11T10:00:00.000Z");
  assert.equal(completed.last_undo.undone, true);
});

test("undo restart never replays a membership removal whose outcome was not checkpointed", async () => {
  const first = await makeHarness({
    initialState: undoState(),
    zoteroOptions: {
      items: undoItems(),
      crashAfterUndoWrite: "membership",
    },
  });

  await assert.rejects(first.runtime.undoLastBatch(), /fixture_undo_write_crash/);

  assert.equal(first.prompt.calls.length, 1);
  assert.deepEqual(first.zotero.removedMemberships, [[304, 77]]);
  const interrupted = JSON.parse(await first.io.readUTF8(first.paths.state));
  assert.equal(interrupted.last_undo.undo_progress.pending_action.kind, "membership");
  const existingItem = first.zotero.items.find(item => item.id === 304);
  existingItem.collections.push(77);

  const second = await makeHarness({
    sharedFiles: first.files,
    sharedZotero: first.zotero,
  });
  const outcome = await second.runtime.undoLastBatch();

  assert.equal(second.prompt.calls.length, 0);
  assert.equal(outcome.status, "undone");
  assert.deepEqual(existingItem.collections, [77]);
  assert.deepEqual(second.zotero.removedMemberships, [[304, 77]]);
  const completed = JSON.parse(await second.io.readUTF8(second.paths.state));
  assert.equal(completed.last_undo.undone, true);
  assert.deepEqual(completed.last_undo.undo_result.removed_memberships, []);
  assert.deepEqual(completed.last_undo.undo_result.skipped_ids, [304]);
});

test("concurrent undo calls share one promise and one mutation sequence", async () => {
  const harness = await makeHarness({
    initialState: undoState(),
    zoteroOptions: { items: undoItems() },
  });

  const first = harness.runtime.undoLastBatch();
  const second = harness.runtime.undoLastBatch();

  assert.equal(first, second);
  const [firstOutcome, secondOutcome] = await Promise.all([first, second]);
  assert.deepEqual(firstOutcome, secondOutcome);
  assert.equal(firstOutcome.status, "undone");
  assert.equal(harness.prompt.calls.length, 1);
  assert.deepEqual(harness.zotero.removedMemberships, [[304, 77]]);
  assert.deepEqual(harness.zotero.deletedIDs, [902, 901]);
});

test("scan and undo are serialized so their state and Zotero writes cannot overlap", async () => {
  let releaseConfirmation;
  const runConfirmationBarrier = new Promise(resolve => {
    releaseConfirmation = resolve;
  });
  const request = await job({ number: 2, runID: "run-after-undo-ledger" });
  const harness = await makeHarness({
    requests: [request],
    initialState: undoState(),
    runConfirmationBarrier,
    zoteroOptions: { items: undoItems() },
  });

  const scan = harness.runtime.scanNow();
  for (let attempt = 0; attempt < 20 && harness.prompt.calls.length === 0; attempt += 1) {
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.equal(harness.prompt.calls.length, 1);
  assert.notEqual(harness.prompt.calls[0].kind, "undo");

  const undo = harness.runtime.undoLastBatch();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(harness.prompt.calls.length, 1);

  releaseConfirmation();
  await scan;
  const outcome = await undo;

  assert.equal(outcome.status, "undone");
  assert.equal(harness.prompt.calls.filter(call => call.kind === "undo").length, 1);
  assert.equal(outcome.runID, request.run_id);
});

test("generated ledger undo preserves an existing item and removes imported artifacts", async () => {
  const request = await job({
    items: [{
      task_id: "paper-0001",
      doi: "10.1000/ledger-existing",
      title: "Ledger Existing",
      authors: "Smith, J.",
      year: "2025",
    }, {
      task_id: "paper-0002",
      doi: "10.1000/ledger-imported",
      title: "Ledger Imported",
      authors: "Jones, J.",
      year: "2024",
    }],
  });
  const collectionID = 701;
  const harness = await makeHarness({
    requests: [request],
    zoteroOptions: {
      collections: [{ id: collectionID, libraryID: 1, name: request.collection_name }],
      items: [{
        id: 910,
        libraryID: 1,
        doi: "10.1000/ledger-existing",
        title: "Ledger Existing",
        firstCreator: "Smith",
        year: "2025",
        collections: [],
        attachments: [],
      }],
      translationsByDOI: {
        "10.1000/ledger-imported": {
          id: 911,
          doi: "10.1000/ledger-imported",
          title: "Ledger Imported",
          firstCreator: "Jones",
          year: "2024",
        },
      },
      availablePDFByItemID: {
        910: {
          id: 912,
          contentType: "application/pdf",
          path: "C:\\Zotero\\storage\\LEDGER1\\paper.pdf",
        },
        911: {
          id: 913,
          contentType: "application/pdf",
          path: "C:\\Zotero\\storage\\LEDGER2\\paper.pdf",
        },
      },
    },
  });

  await harness.runtime.scanNow();
  const stateBeforeUndo = JSON.parse(await harness.io.readUTF8(harness.paths.state));
  assert.deepEqual(stateBeforeUndo.last_undo.created_item_ids, [911]);
  assert.deepEqual(stateBeforeUndo.last_undo.created_attachment_ids, [912, 913]);
  assert.deepEqual(stateBeforeUndo.last_undo.added_memberships, [
    [910, collectionID],
    [911, collectionID],
  ]);

  const outcome = await harness.runtime.undoLastBatch();

  assert.equal(outcome.status, "undone");
  assert.deepEqual(harness.zotero.removedMemberships, [[910, collectionID]]);
  assert.deepEqual(harness.zotero.deletedIDs, [913, 912, 911]);
  assert.equal(harness.zotero.items.some(item => item.id === 910), true);
  assert.equal(harness.zotero.items.some(item => item.id === 911), false);
});

test("cancelling undo performs zero Zotero writes and keeps the ledger active", async () => {
  const harness = await makeHarness({
    initialState: undoState(),
    undoConfirm: false,
    zoteroOptions: { items: undoItems() },
  });

  const outcome = await harness.runtime.undoLastBatch();

  assert.equal(outcome.status, "cancelled");
  assert.equal(harness.zotero.writeCalls.length, 0);
  const state = JSON.parse(await harness.io.readUTF8(harness.paths.state));
  assert.equal(state.last_undo.undone, false);
  assert.equal(state.last_undo.undo_result, null);
});

test("undo skips and reports an object whose library or batch identity changed", async () => {
  const state = undoState();
  state.last_undo.created_attachment_ids = [];
  state.last_undo.added_memberships = [];
  const harness = await makeHarness({
    initialState: state,
    zoteroOptions: {
      items: [{
        id: 901,
        libraryID: 2,
        doi: "10.1000/moved",
        title: "Moved Item",
        firstCreator: "Jones",
        year: "2025",
        collections: [77],
        attachments: [],
      }],
    },
  });

  const outcome = await harness.runtime.undoLastBatch();

  assert.equal(outcome.status, "undone");
  assert.deepEqual(harness.zotero.deletedIDs, []);
  assert.deepEqual(outcome.result.skipped_ids, [901]);
  assert.equal(harness.errors.some(error => error.code === "undo_identity_mismatch"), true);
});

test("undo is blocked while another confirmed run is still active", async () => {
  const state = undoState();
  state.runs["run-active"] = {
    job_ids: [JOB_IDS[1]],
    payload_sha256: ["b".repeat(64)],
    confirmed_at: "2026-07-11T09:45:00.000Z",
    completed: false,
  };
  const harness = await makeHarness({
    initialState: state,
    zoteroOptions: { items: undoItems() },
  });

  const outcome = await harness.runtime.undoLastBatch();

  assert.equal(outcome.status, "run_active");
  assert.equal(harness.prompt.calls.length, 0);
  assert.equal(harness.zotero.writeCalls.length, 0);
});

test("showStatus reports run id, phase, total, successes, and failures", async () => {
  const request = await job({
    items: [{
      task_id: "paper-0001",
      doi: "10.1000/status-success",
      title: "Status Success",
      authors: "Smith, J.",
      year: "2025",
    }, {
      task_id: "paper-0002",
      doi: "10.1000/status-failure",
      title: "Status Failure",
      authors: "Jones, J.",
      year: "2024",
    }],
  });
  const collectionID = 701;
  const harness = await makeHarness({
    requests: [request],
    zoteroOptions: {
      collections: [{ id: collectionID, libraryID: 1, name: request.collection_name }],
      items: [{
        id: 950,
        libraryID: 1,
        doi: "10.1000/status-success",
        title: "Status Success",
        firstCreator: "Smith",
        year: "2025",
        collections: [collectionID],
        attachments: [{
          id: 951,
          contentType: "application/pdf",
          path: "C:\\Zotero\\storage\\STATUS\\paper.pdf",
        }],
      }, {
        id: 952,
        libraryID: 1,
        doi: "10.1000/status-failure",
        title: "Status Failure",
        firstCreator: "Jones",
        year: "2024",
        collections: [collectionID],
        attachments: [],
      }],
    },
  });

  await harness.runtime.scanNow();
  const message = harness.runtime.showStatus();

  assert.match(message, new RegExp(request.run_id));
  assert.match(message, /状态：已完成/);
  assert.match(message, /总数：2/);
  assert.match(message, /成功：1/);
  assert.match(message, /失败：1/);
  assert.equal(harness.prompt.alerts.at(-1).message, message);

  const restarted = await makeHarness({
    sharedFiles: harness.files,
    sharedZotero: harness.zotero,
  });
  await restarted.runtime.scanNow();
  const restored = restarted.runtime.showStatus();
  assert.match(restored, new RegExp(request.run_id));
  assert.match(restored, /状态：已完成/);
  assert.match(restored, /总数：2/);
  assert.match(restored, /成功：1/);
  assert.match(restored, /失败：1/);
});
