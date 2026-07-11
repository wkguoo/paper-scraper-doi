(function (createRuntime) {
  if (typeof module !== "undefined" && module.exports) {
    module.exports = createRuntime;
    return;
  }

  function apiUnavailable() {
    throw new Error("zotero_api_unavailable");
  }

  if (
    !globalThis.ZoteroPaperBridgeCore
    || !globalThis.IOUtils
    || !globalThis.PathUtils
    || !globalThis.Services
    || !globalThis.Zotero
  ) {
    apiUnavailable();
  }

  const io = {
    join: (...parts) => PathUtils.join(...parts),
    basename: path => (
      typeof PathUtils.filename === "function"
        ? PathUtils.filename(path)
        : String(path).replaceAll("\\", "/").split("/").at(-1)
    ),
    makeDir: path => IOUtils.makeDirectory(path, { ignoreExisting: true }),
    list: path => IOUtils.getChildren(path),
    exists: path => IOUtils.exists(path),
    readUTF8: path => IOUtils.readUTF8(path),
    async writeUTF8(path, text, { exclusive = false, flush = false } = {}) {
      try {
        return await IOUtils.writeUTF8(path, text, {
          mode: exclusive ? "create" : "overwrite",
          flush,
        });
      } catch (error) {
        if (exclusive && await IOUtils.exists(path)) throw new Error("bridge_file_exists");
        throw error;
      }
    },
    replaceUTF8(path, text, temporaryPath) {
      return IOUtils.writeUTF8(path, text, { tmpPath: temporaryPath, flush: true });
    },
    async move(source, target, { noOverwrite = false } = {}) {
      try {
        return await IOUtils.move(source, target, { noOverwrite });
      } catch (error) {
        if (noOverwrite && await IOUtils.exists(target)) throw new Error("bridge_file_exists");
        throw error;
      }
    },
    remove: path => IOUtils.remove(path, { ignoreAbsent: true }),
  };

  const prompt = {
    confirm: details => Services.prompt.confirm(
      null,
      "文献下载桥接",
      details.message,
    ),
    alert: (title, message) => Services.prompt.alert(null, title, message),
  };

  const clock = {
    now: () => new Date(),
    randomUUID: () => (
      globalThis.crypto?.randomUUID?.()
      || `${Date.now()}-${Math.random().toString(16).slice(2)}`
    ),
    setInterval: (callback, milliseconds) => setInterval(callback, milliseconds),
    clearInterval: timer => clearInterval(timer),
  };

  const zotero = {
    pluginVersion: "0.1.0",
    version: String(Zotero.version || "9.0"),
    async getLibraryName(libraryID) {
      const library = Zotero.Libraries.get(libraryID);
      return library?.name || `文库 ${libraryID}`;
    },
    reportError(report) {
      const error = new Error(report.code || "plugin_error");
      error.name = "PaperDownloadBridgeError";
      Zotero.logError(error);
    },
  };

  Zotero.PaperDownloadBridge = createRuntime({
    core: globalThis.ZoteroPaperBridgeCore,
    io,
    env: { get: name => Services.env.get(name) },
    prompt,
    clock,
    zotero,
  });
})(function createRuntime({ core, io, env, prompt, clock, zotero }) {
  const JOB_FILE_RE = /^([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\.json$/;
  const JOB_ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
  const SHA256_RE = /^[0-9a-f]{64}$/;
  const UTC_TIMESTAMP_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/;
  const ERROR_CODE_RE = /^[a-z][a-z0-9_]{1,127}$/;
  const STATE_FIELDS = new Set(["schema_version", "runs", "last_undo"]);
  const RUN_STATE_FIELDS = new Set([
    "job_ids",
    "payload_sha256",
    "confirmed_at",
    "completed",
  ]);
  const POLL_INTERVAL_MS = 1000;

  if (
    !core
    || typeof core.validateRequest !== "function"
    || typeof core.failureRow !== "function"
    || !io
    || typeof io.join !== "function"
    || typeof io.basename !== "function"
    || typeof io.makeDir !== "function"
    || typeof io.list !== "function"
    || typeof io.exists !== "function"
    || typeof io.readUTF8 !== "function"
    || typeof io.writeUTF8 !== "function"
    || typeof io.replaceUTF8 !== "function"
    || typeof io.move !== "function"
    || typeof io.remove !== "function"
    || typeof env?.get !== "function"
    || typeof prompt?.confirm !== "function"
    || typeof clock?.now !== "function"
  ) {
    throw new Error("zotero_api_unavailable");
  }

  let timer = null;
  let scanInFlight = null;
  let temporaryCounter = 0;
  let lastStatus = "插件已启动，尚无已处理批次。";

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function hasExactFields(value, expected) {
    if (!isPlainObject(value)) return false;
    const keys = Object.keys(value);
    return keys.length === expected.size && keys.every(key => expected.has(key));
  }

  function errorCode(error, fallback = "plugin_error") {
    const message = typeof error?.message === "string" ? error.message : "";
    return ERROR_CODE_RE.test(message) ? message : fallback;
  }

  function now() {
    const value = clock.now();
    if (!(value instanceof Date) || Number.isNaN(value.getTime())) {
      throw new Error("bridge_clock_invalid");
    }
    return value;
  }

  function nowISO() {
    return now().toISOString();
  }

  function temporaryToken() {
    temporaryCounter += 1;
    const generated = typeof clock.randomUUID === "function"
      ? clock.randomUUID()
      : (
        globalThis.crypto?.randomUUID?.()
        || `${now().getTime()}-${Math.random().toString(16).slice(2)}-${temporaryCounter}`
      );
    return String(generated).replace(/[^a-zA-Z0-9-]/g, "");
  }

  function queuePaths() {
    const localAppData = String(env.get("LOCALAPPDATA") || "").trim();
    if (!localAppData) throw new Error("bridge_localappdata_missing");
    const root = io.join(localAppData, "PaperScraperDOI", "zotero-bridge", "v1");
    return Object.freeze({
      root,
      inbox: io.join(root, "inbox"),
      processing: io.join(root, "processing"),
      outbox: io.join(root, "outbox"),
      archive: io.join(root, "archive"),
      state: io.join(root, "plugin-state.json"),
    });
  }

  async function ensureQueue() {
    const paths = queuePaths();
    for (const directory of [paths.inbox, paths.processing, paths.outbox, paths.archive]) {
      await io.makeDir(directory);
    }
    return paths;
  }

  function serializeJSON(value) {
    return `${JSON.stringify(value, null, 2)}\n`;
  }

  async function publishJSON(path, value) {
    const temporaryPath = `${path}.${temporaryToken()}.tmp`;
    try {
      await io.writeUTF8(temporaryPath, serializeJSON(value), {
        exclusive: true,
        flush: true,
      });
      await io.move(temporaryPath, path, { noOverwrite: true });
    } catch (error) {
      try {
        await io.remove(temporaryPath);
      } catch (_cleanupError) {
        // Keep the original publication error; stale .tmp files are never consumed.
      }
      throw error;
    }
    return path;
  }

  async function replaceJSON(path, value) {
    const temporaryPath = `${path}.${temporaryToken()}.tmp`;
    try {
      await io.replaceUTF8(path, serializeJSON(value), temporaryPath);
    } catch (error) {
      try {
        await io.remove(temporaryPath);
      } catch (_cleanupError) {
        // Keep the original state-write error.
      }
      throw error;
    }
    return path;
  }

  async function readRequest(path) {
    const name = io.basename(path);
    const filenameMatch = JOB_FILE_RE.exec(name);
    if (!filenameMatch) throw new Error("bridge_request_filename_invalid");
    let request;
    try {
      request = JSON.parse(await io.readUTF8(path));
    } catch (error) {
      if (errorCode(error) === "bridge_file_missing") throw error;
      throw new Error("bridge_request_json_invalid");
    }
    await core.validateRequest(request, now());
    if (request.job_id !== filenameMatch[1]) throw new Error("bridge_job_id_conflict");
    return request;
  }

  function emptyState() {
    return { schema_version: 1, runs: {}, last_undo: null };
  }

  function validateState(value) {
    if (!hasExactFields(value, STATE_FIELDS)) throw new Error("bridge_state_invalid");
    if (value.schema_version !== 1 || !isPlainObject(value.runs) || value.last_undo !== null) {
      throw new Error("bridge_state_invalid");
    }
    for (const [runID, run] of Object.entries(value.runs)) {
      if (!runID || runID.length > 4096 || !hasExactFields(run, RUN_STATE_FIELDS)) {
        throw new Error("bridge_state_invalid");
      }
      if (
        !Array.isArray(run.job_ids)
        || !run.job_ids.length
        || !run.job_ids.every(value => typeof value === "string" && JOB_ID_RE.test(value))
        || new Set(run.job_ids).size !== run.job_ids.length
        || !Array.isArray(run.payload_sha256)
        || run.payload_sha256.length !== run.job_ids.length
        || !run.payload_sha256.every(value => typeof value === "string" && SHA256_RE.test(value))
        || typeof run.confirmed_at !== "string"
        || !UTC_TIMESTAMP_RE.test(run.confirmed_at)
        || Number.isNaN(Date.parse(run.confirmed_at))
        || typeof run.completed !== "boolean"
      ) {
        throw new Error("bridge_state_invalid");
      }
    }
    return value;
  }

  async function loadState(paths) {
    if (!await io.exists(paths.state)) return emptyState();
    let value;
    try {
      value = JSON.parse(await io.readUTF8(paths.state));
    } catch (_error) {
      throw new Error("bridge_state_invalid");
    }
    return validateState(value);
  }

  function cloneRuns(runs) {
    const result = {};
    for (const [key, value] of Object.entries(runs)) {
      Object.defineProperty(result, key, {
        value: {
          job_ids: [...value.job_ids],
          payload_sha256: [...value.payload_sha256],
          confirmed_at: value.confirmed_at,
          completed: value.completed,
        },
        enumerable: true,
        configurable: true,
        writable: true,
      });
    }
    return result;
  }

  function identityFor(entries) {
    const sorted = [...entries].sort((left, right) => (
      left.request.chunk_index - right.request.chunk_index
    ));
    return {
      job_ids: sorted.map(entry => entry.request.job_id),
      payload_sha256: sorted.map(entry => entry.request.payload_sha256),
    };
  }

  function arraysEqual(left, right) {
    return Array.isArray(left)
      && Array.isArray(right)
      && left.length === right.length
      && left.every((value, index) => value === right[index]);
  }

  function confirmationMatches(state, runID, entries) {
    const previous = state.runs[runID];
    if (!previous) return false;
    const identity = identityFor(entries);
    return arraysEqual(previous.job_ids, identity.job_ids)
      && arraysEqual(previous.payload_sha256, identity.payload_sha256);
  }

  async function saveConfirmation(paths, state, runID, entries) {
    const identity = identityFor(entries);
    const updated = {
      schema_version: 1,
      runs: cloneRuns(state.runs),
      last_undo: null,
    };
    Object.defineProperty(updated.runs, runID, {
      value: {
        ...identity,
        confirmed_at: nowISO(),
        completed: false,
      },
      enumerable: true,
      configurable: true,
      writable: true,
    });
    await replaceJSON(paths.state, updated);
    return updated;
  }

  function reportError(code, context = {}) {
    const report = { code, ...context };
    lastStatus = `最近错误：${code}`;
    if (typeof zotero?.reportError === "function") zotero.reportError(report);
    return report;
  }

  async function archiveRejected(paths, path, preferredName = "") {
    let target;
    if (JOB_FILE_RE.test(preferredName)) {
      target = io.join(paths.archive, preferredName);
      if (await io.exists(target)) target = null;
    }
    if (!target) target = io.join(paths.archive, `rejected-${temporaryToken()}.json`);
    await io.move(path, target, { noOverwrite: true });
    return target;
  }

  async function collectRequests(paths) {
    const entries = [];
    for (const [location, directory] of [
      ["inbox", paths.inbox],
      ["processing", paths.processing],
    ]) {
      const children = [...await io.list(directory)].sort();
      for (const path of children) {
        const name = io.basename(path);
        try {
          if (!JOB_FILE_RE.test(name)) throw new Error("bridge_request_filename_invalid");
          const request = await readRequest(path);
          entries.push({ location, path, request });
        } catch (error) {
          const code = errorCode(error);
          reportError(code, { file: JOB_FILE_RE.test(name) ? name : "invalid" });
          try {
            await archiveRejected(paths, path, name);
          } catch (archiveError) {
            reportError(errorCode(archiveError), { file: "rejected" });
          }
        }
      }
    }
    return entries;
  }

  function classifyGroup(entries) {
    const first = entries[0]?.request;
    if (!first) return { status: "invalid", entries };
    const sharedFields = [
      "library_id",
      "collection_name",
      "created_at",
      "expires_at",
      "chunk_count",
    ];
    if (entries.some(entry => (
      sharedFields.some(field => entry.request[field] !== first[field])
    ))) {
      return { status: "invalid", entries };
    }

    const jobIDs = new Set();
    const chunkIndexes = new Set();
    const taskIDs = new Set();
    for (const entry of entries) {
      const request = entry.request;
      if (jobIDs.has(request.job_id) || chunkIndexes.has(request.chunk_index)) {
        return { status: "invalid", entries };
      }
      jobIDs.add(request.job_id);
      chunkIndexes.add(request.chunk_index);
      for (const item of request.items) {
        if (taskIDs.has(item.task_id)) return { status: "invalid", entries };
        taskIDs.add(item.task_id);
      }
    }

    if (entries.length > first.chunk_count) return { status: "invalid", entries };
    const complete = entries.length === first.chunk_count
      && Array.from({ length: first.chunk_count }, (_, index) => index + 1)
        .every(index => chunkIndexes.has(index));
    return {
      status: complete ? "complete" : "incomplete",
      entries: [...entries].sort((left, right) => (
        left.request.chunk_index - right.request.chunk_index
      )),
    };
  }

  function groupRequests(entries) {
    const grouped = new Map();
    for (const entry of entries) {
      const runID = entry.request.run_id;
      if (!grouped.has(runID)) grouped.set(runID, []);
      grouped.get(runID).push(entry);
    }
    return Array.from(grouped.entries())
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([runID, values]) => ({ runID, ...classifyGroup(values) }));
  }

  async function moveToProcessing(paths, entries) {
    for (const entry of entries) {
      if (entry.location !== "inbox") continue;
      const target = io.join(paths.processing, io.basename(entry.path));
      await io.move(entry.path, target, { noOverwrite: true });
      entry.path = target;
      entry.location = "processing";
    }
  }

  async function archiveEntries(paths, entries) {
    for (const entry of entries) {
      await archiveRejected(paths, entry.path, io.basename(entry.path));
      entry.location = "archive";
    }
  }

  function resultDocument(request, rows, startedAt, finishedAt) {
    return {
      schema_version: 1,
      job_id: request.job_id,
      payload_sha256: request.payload_sha256,
      plugin_version: String(zotero?.pluginVersion || "0.1.0"),
      zotero_version: String(zotero?.version || "9.0"),
      started_at: startedAt,
      finished_at: finishedAt,
      rows,
    };
  }

  async function publishFailureGroup(paths, entries, status, reason) {
    const startedAt = nowISO();
    for (const entry of entries) {
      const finishedAt = nowISO();
      const rows = entry.request.items.map(item => (
        core.failureRow(item.task_id, status, reason)
      ));
      const target = io.join(paths.outbox, `${entry.request.job_id}.result.json`);
      await publishJSON(
        target,
        resultDocument(entry.request, rows, startedAt, finishedAt),
      );
    }
    await archiveEntries(paths, entries);
  }

  async function confirmRun(group) {
    const first = group.entries[0].request;
    const itemCount = group.entries.reduce((total, entry) => (
      total + entry.request.items.length
    ), 0);
    const libraryName = typeof zotero?.getLibraryName === "function"
      ? await zotero.getLibraryName(first.library_id)
      : `文库 ${first.library_id}`;
    const message = [
      `目标文库：${libraryName}（ID: ${first.library_id}）`,
      `文献数量：${itemCount}`,
      `目标集合：${first.collection_name}`,
      "",
      "插件将查找或新增这些文献，并尝试获取可用 PDF。现有附件不会被修改。",
      "是否继续？",
    ].join("\n");
    return Boolean(await prompt.confirm({
      runID: group.runID,
      libraryID: first.library_id,
      libraryName,
      itemCount,
      collectionName: first.collection_name,
      message,
    }));
  }

  async function processRun(group, { confirmed, paths = queuePaths() } = {}) {
    if (!confirmed) {
      await publishFailureGroup(
        paths,
        group.entries,
        "user_cancelled",
        "user_cancelled",
      );
      lastStatus = `批次 ${group.runID} 已取消，未写入 Zotero。`;
      return { status: "cancelled", runID: group.runID };
    }

    // Task 4 adds item resolution and available-PDF handling here. Keeping the
    // requests in processing makes this checkpoint restart-safe without writes.
    lastStatus = `批次 ${group.runID} 已确认，等待处理文献。`;
    return { status: "confirmed", runID: group.runID };
  }

  async function scanOnce() {
    const paths = await ensureQueue();
    let state;
    try {
      state = await loadState(paths);
    } catch (error) {
      reportError(errorCode(error));
      return { status: "state_invalid", completeRuns: 0, incompleteRuns: 0 };
    }

    const groups = groupRequests(await collectRequests(paths));
    let completeRuns = 0;
    let incompleteRuns = 0;
    for (const group of groups) {
      if (group.status === "incomplete") {
        incompleteRuns += 1;
        continue;
      }
      if (group.status === "invalid") {
        reportError("bridge_run_chunks_invalid", { run_id: group.runID });
        try {
          await publishFailureGroup(
            paths,
            group.entries,
            "plugin_error",
            "bridge_run_chunks_invalid",
          );
        } catch (error) {
          reportError(errorCode(error), { run_id: group.runID });
        }
        continue;
      }

      completeRuns += 1;
      try {
        await moveToProcessing(paths, group.entries);
        const alreadyConfirmed = confirmationMatches(state, group.runID, group.entries);
        let confirmed = alreadyConfirmed;
        if (!alreadyConfirmed) {
          confirmed = await confirmRun(group);
          if (confirmed) {
            state = await saveConfirmation(paths, state, group.runID, group.entries);
          }
        }
        await processRun(group, { confirmed, paths });
      } catch (error) {
        reportError(errorCode(error), { run_id: group.runID });
      }
    }

    if (!groups.length) lastStatus = "没有待处理的 Zotero 桥接任务。";
    else if (incompleteRuns) lastStatus = `有 ${incompleteRuns} 个批次仍在等待完整分块。`;
    return { status: "scanned", completeRuns, incompleteRuns };
  }

  function scanNow() {
    if (scanInFlight) return scanInFlight;
    const current = Promise.resolve().then(scanOnce);
    scanInFlight = current;
    current.then(
      () => {
        if (scanInFlight === current) scanInFlight = null;
      },
      () => {
        if (scanInFlight === current) scanInFlight = null;
      },
    );
    return current;
  }

  async function startup() {
    if (timer) return;
    await scanNow();
    if (typeof clock.setInterval === "function") {
      timer = clock.setInterval(() => {
        scanNow().catch(error => reportError(errorCode(error)));
      }, POLL_INTERVAL_MS);
    }
  }

  async function shutdown() {
    if (timer && typeof clock.clearInterval === "function") clock.clearInterval(timer);
    timer = null;
    if (scanInFlight) await scanInFlight;
  }

  function showStatus() {
    if (typeof prompt.alert === "function") prompt.alert("文献下载桥接", lastStatus);
    return lastStatus;
  }

  async function undoLastBatch() {
    const message = "当前没有可撤销的批次。";
    if (typeof prompt.alert === "function") prompt.alert("文献下载桥接", message);
    return { status: "nothing_to_undo" };
  }

  return {
    queuePaths,
    readRequest,
    publishJSON,
    scanNow,
    confirmRun,
    processRun,
    startup,
    shutdown,
    showStatus,
    undoLastBatch,
  };
});
