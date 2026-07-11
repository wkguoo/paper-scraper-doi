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
    async assertProcessingAPI(libraryID) {
      const requiredFunctions = [
        Zotero.Libraries?.get,
        Zotero.Items?.getAsync,
        Zotero.Collections?.getByLibrary,
        Zotero.Attachments?.addAvailablePDF,
      ];
      if (
        typeof Zotero.Search !== "function"
        || typeof Zotero.Collection !== "function"
        || typeof Zotero.Translate?.Search !== "function"
        || requiredFunctions.some(value => typeof value !== "function")
      ) {
        apiUnavailable();
      }
      const search = new Zotero.Search();
      const translate = new Zotero.Translate.Search();
      const collection = new Zotero.Collection();
      if (
        typeof search.addCondition !== "function"
        || typeof search.search !== "function"
        || typeof translate.setIdentifier !== "function"
        || typeof translate.getTranslators !== "function"
        || typeof translate.setTranslator !== "function"
        || typeof translate.translate !== "function"
        || typeof collection.saveTx !== "function"
      ) {
        apiUnavailable();
      }
      const library = Zotero.Libraries.get(libraryID);
      if (
        !library
        || library.isFeed
        || library.editable === false
        || library.filesEditable === false
      ) {
        throw new Error("zotero_unavailable");
      }
    },
    async searchByDOI(libraryID, doi) {
      const search = new Zotero.Search();
      search.libraryID = libraryID;
      search.addCondition("DOI", "is", doi);
      const ids = await search.search();
      return ids.length ? await Zotero.Items.getAsync(ids) : [];
    },
    async searchByTitle(libraryID, fragment) {
      const search = new Zotero.Search();
      search.libraryID = libraryID;
      search.addCondition("title", "contains", fragment);
      const ids = await search.search();
      return ids.length ? await Zotero.Items.getAsync(ids) : [];
    },
    async describeItem(item, libraryID) {
      const regular = Boolean(item && typeof item.isRegularItem === "function" && item.isRegularItem());
      return {
        item,
        id: item?.id,
        libraryID: item?.libraryID,
        eligible: regular
          && !item.isFeedItem
          && !item.deleted
          && item.libraryID === libraryID,
        doi: regular ? String(item.getField("DOI") || "") : "",
        title: regular ? String(item.getField("title") || "") : "",
        firstCreator: regular ? String(item.getField("firstCreator") || "") : "",
        year: regular ? String(item.getField("year") || "") : "",
      };
    },
    async listAttachments(item) {
      if (!item || typeof item.getAttachments !== "function") apiUnavailable();
      const ids = item.getAttachments(false);
      return ids.length ? await Zotero.Items.getAsync(ids) : [];
    },
    async describeAttachment(attachment, item) {
      const isAttachment = Boolean(
        attachment
        && typeof attachment.isAttachment === "function"
        && attachment.isAttachment(),
      );
      let path = "";
      if (isAttachment) {
        try {
          if (typeof attachment.getFilePathAsync === "function") {
            path = await attachment.getFilePathAsync();
          } else if (typeof attachment.getFilePath === "function") {
            path = attachment.getFilePath();
          } else {
            apiUnavailable();
          }
        } catch (_error) {
          path = "";
        }
      }
      return {
        attachment,
        id: attachment?.id,
        eligible: isAttachment
          && !attachment.deleted
          && attachment.libraryID === item.libraryID
          && attachment.parentItemID === item.id,
        contentType: isAttachment ? String(attachment.attachmentContentType || "") : "",
        path: path || "",
      };
    },
    async ensureCollection(libraryID, name) {
      const matches = Zotero.Collections.getByLibrary(libraryID, true, false)
        .filter(collection => !collection.deleted && collection.name === name);
      if (matches.length > 1) throw new Error("metadata_uncertain");
      if (matches.length === 1) return matches[0];
      const collection = new Zotero.Collection();
      collection.libraryID = libraryID;
      collection.name = name;
      await collection.saveTx();
      return collection;
    },
    async translateByDOI(doi, libraryID, collectionID) {
      const translate = new Zotero.Translate.Search();
      translate.setIdentifier({ DOI: doi });
      const translators = await translate.getTranslators();
      if (!translators.length) throw new Error("not_found");
      translate.setTranslator(translators);
      return translate.translate({
        libraryID,
        collections: [collectionID],
        saveAttachments: false,
      });
    },
    async addToCollection(item, collectionID) {
      if (
        !item
        || typeof item.getCollections !== "function"
        || typeof item.addToCollection !== "function"
        || typeof item.saveTx !== "function"
      ) {
        apiUnavailable();
      }
      if (item.getCollections(false).includes(collectionID)) return false;
      item.addToCollection(collectionID);
      await item.saveTx();
      return true;
    },
    addAvailablePDF(item) {
      return Zotero.Attachments.addAvailablePDF(item);
    },
    async assertUndoAPI() {
      if (typeof Zotero.Items?.getAsync !== "function") apiUnavailable();
    },
    async removeMembershipIfOwned(itemID, collectionID, libraryID) {
      const item = await Zotero.Items.getAsync(itemID);
      if (
        !item
        || typeof item.isRegularItem !== "function"
        || !item.isRegularItem()
        || item.isFeedItem
        || item.deleted
        || item.libraryID !== libraryID
        || typeof item.getCollections !== "function"
        || typeof item.removeFromCollection !== "function"
        || typeof item.saveTx !== "function"
      ) {
        return false;
      }
      if (!item.getCollections(false).includes(collectionID)) return false;
      item.removeFromCollection(collectionID);
      await item.saveTx();
      return true;
    },
    async eraseCreatedObject(id, kind, libraryID, identity) {
      const item = await Zotero.Items.getAsync(id);
      if (!item || item.deleted || item.libraryID !== libraryID || typeof item.eraseTx !== "function") {
        return false;
      }
      if (kind === "attachment") {
        if (typeof item.isAttachment !== "function" || !item.isAttachment()) return false;
        const parent = await Zotero.Items.getAsync(item.parentItemID);
        if (
          !parent
          || typeof parent.isRegularItem !== "function"
          || !parent.isRegularItem()
          || parent.isFeedItem
          || parent.deleted
          || parent.libraryID !== libraryID
        ) {
          return false;
        }
        const parentWasInBatch = identity.batchItemIDs.includes(parent.id)
          || (
            Number.isInteger(identity.collectionID)
            && identity.collectionID > 0
            && typeof parent.getCollections === "function"
            && parent.getCollections(false).includes(identity.collectionID)
          );
        if (!parentWasInBatch) return false;
        await item.eraseTx();
        return true;
      }
      if (
        kind !== "item"
        || typeof item.isRegularItem !== "function"
        || !item.isRegularItem()
        || item.isFeedItem
        || !Number.isInteger(identity.collectionID)
        || identity.collectionID <= 0
        || typeof item.getCollections !== "function"
        || !item.getCollections(false).includes(identity.collectionID)
      ) {
        return false;
      }
      await item.eraseTx();
      return true;
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
  const PROGRESS_FILE_RE = /^([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\.progress\.json$/;
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
  const PROGRESS_FIELDS = new Set([
    "schema_version",
    "job_id",
    "payload_sha256",
    "confirmed",
    "rows",
    "created_item_ids",
    "created_attachment_ids",
    "added_memberships",
  ]);
  const RESULT_FIELDS = new Set([
    "schema_version",
    "job_id",
    "payload_sha256",
    "plugin_version",
    "zotero_version",
    "started_at",
    "finished_at",
    "rows",
  ]);
  const UNDO_LEDGER_FIELDS = new Set([
    "run_id",
    "library_id",
    "collection_id",
    "collection_name",
    "job_ids",
    "payload_sha256",
    "created_item_ids",
    "created_attachment_ids",
    "added_memberships",
    "preexisting_item_ids",
    "preexisting_attachment_ids",
    "total_count",
    "success_count",
    "failure_count",
    "completed_at",
    "undone",
    "undo_result",
  ]);
  const UNDO_RESULT_FIELDS = new Set([
    "finished_at",
    "removed_memberships",
    "deleted_attachment_ids",
    "deleted_item_ids",
    "skipped_ids",
  ]);
  const RESULT_ROW_FIELDS = new Set([
    "task_id",
    "zotero_item_id",
    "attachment_path",
    "status",
    "reason",
  ]);
  const ITEM_FAILURE_STATUSES = new Set([
    "no_pdf",
    "not_found",
    "metadata_uncertain",
    "zotero_unavailable",
    "no_attachment",
    "download_failed",
    "zotero_api_unavailable",
    "job_expired",
    "job_id_conflict",
    "plugin_error",
  ]);
  const RESULT_STATUSES = new Set([
    ...ITEM_FAILURE_STATUSES,
    "existing_pdf",
    "downloaded",
    "user_cancelled",
  ]);
  const PROCESSING_METHODS = [
    "assertProcessingAPI",
    "searchByDOI",
    "searchByTitle",
    "describeItem",
    "listAttachments",
    "describeAttachment",
    "ensureCollection",
    "translateByDOI",
    "addToCollection",
    "addAvailablePDF",
  ];
  const ABSOLUTE_WINDOWS_PATH_RE = /^(?:[a-zA-Z]:[\\/].+|(?:\\\\|\/\/)[^\\/]+[\\/][^\\/]+[\\/].+)$/;
  const MAX_BRIDGE_TEXT_LENGTH = 4096;
  const MAX_TITLE_SEARCH_LENGTH = 256;
  const POLL_INTERVAL_MS = 1000;

  if (
    !core
    || typeof core.validateRequest !== "function"
    || typeof core.failureRow !== "function"
    || typeof core.successRow !== "function"
    || typeof core.normalizeDOI !== "function"
    || typeof core.normalizeTitle !== "function"
    || typeof core.firstCreatorKey !== "function"
    || typeof core.chooseCandidate !== "function"
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
  let lastRunSummary = null;

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

  function validIDArray(value) {
    return Array.isArray(value)
      && value.every(isPositiveInteger)
      && new Set(value).size === value.length;
  }

  function validMemberships(value) {
    return Array.isArray(value)
      && value.every(pair => (
        Array.isArray(pair)
        && pair.length === 2
        && pair.every(isPositiveInteger)
      ))
      && new Set(value.map(pair => pair.join(":"))).size === value.length;
  }

  function validUTCTimestamp(value) {
    return typeof value === "string"
      && UTC_TIMESTAMP_RE.test(value)
      && !Number.isNaN(Date.parse(value));
  }

  function validateUndoResult(value) {
    if (!hasExactFields(value, UNDO_RESULT_FIELDS)) return false;
    return validUTCTimestamp(value.finished_at)
      && validMemberships(value.removed_memberships)
      && validIDArray(value.deleted_attachment_ids)
      && validIDArray(value.deleted_item_ids)
      && validIDArray(value.skipped_ids);
  }

  function validateUndoLedger(value) {
    if (!hasExactFields(value, UNDO_LEDGER_FIELDS)) return false;
    if (
      typeof value.run_id !== "string"
      || !value.run_id
      || value.run_id.length > MAX_BRIDGE_TEXT_LENGTH
      || !isPositiveInteger(value.library_id)
      || !(value.collection_id === null || isPositiveInteger(value.collection_id))
      || typeof value.collection_name !== "string"
      || !value.collection_name
      || value.collection_name.length > MAX_BRIDGE_TEXT_LENGTH
      || !Array.isArray(value.job_ids)
      || !value.job_ids.length
      || !value.job_ids.every(id => typeof id === "string" && JOB_ID_RE.test(id))
      || new Set(value.job_ids).size !== value.job_ids.length
      || !Array.isArray(value.payload_sha256)
      || value.payload_sha256.length !== value.job_ids.length
      || !value.payload_sha256.every(hash => typeof hash === "string" && SHA256_RE.test(hash))
      || !validIDArray(value.created_item_ids)
      || !validIDArray(value.created_attachment_ids)
      || !validMemberships(value.added_memberships)
      || !validIDArray(value.preexisting_item_ids)
      || !validIDArray(value.preexisting_attachment_ids)
      || !Number.isInteger(value.total_count)
      || value.total_count < 0
      || !Number.isInteger(value.success_count)
      || value.success_count < 0
      || !Number.isInteger(value.failure_count)
      || value.failure_count < 0
      || value.total_count !== value.success_count + value.failure_count
      || !validUTCTimestamp(value.completed_at)
      || typeof value.undone !== "boolean"
      || (value.undone ? !validateUndoResult(value.undo_result) : value.undo_result !== null)
      || (
        (
          value.created_item_ids.length
          || value.created_attachment_ids.length
          || value.added_memberships.length
        )
        && value.collection_id === null
      )
      || value.added_memberships.some(pair => pair[1] !== value.collection_id)
    ) {
      return false;
    }
    return true;
  }

  function validateState(value) {
    if (!hasExactFields(value, STATE_FIELDS)) throw new Error("bridge_state_invalid");
    if (
      value.schema_version !== 1
      || !isPlainObject(value.runs)
      || !(value.last_undo === null || validateUndoLedger(value.last_undo))
    ) {
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
    if (value.last_undo) {
      const completedRun = value.runs[value.last_undo.run_id];
      if (
        !completedRun
        || !completedRun.completed
        || !arraysEqual(completedRun.job_ids, value.last_undo.job_ids)
        || !arraysEqual(completedRun.payload_sha256, value.last_undo.payload_sha256)
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

  function cloneUndoLedger(ledger) {
    return ledger === null ? null : JSON.parse(JSON.stringify(ledger));
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
    let lastUndo = cloneUndoLedger(state.last_undo);
    if (lastUndo?.run_id === runID) lastUndo = null;
    const updated = {
      schema_version: 1,
      runs: cloneRuns(state.runs),
      last_undo: lastUndo,
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
    validateState(updated);
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
        if (location === "processing" && PROGRESS_FILE_RE.test(name)) continue;
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

  function isPositiveInteger(value) {
    return Number.isInteger(value) && value > 0;
  }

  function emptyProgress(request) {
    return {
      schema_version: 1,
      job_id: request.job_id,
      payload_sha256: request.payload_sha256,
      confirmed: true,
      rows: [],
      created_item_ids: [],
      created_attachment_ids: [],
      added_memberships: [],
    };
  }

  function validateProgress(value, request) {
    if (!hasExactFields(value, PROGRESS_FIELDS)) throw new Error("bridge_progress_invalid");
    if (
      value.schema_version !== 1
      || value.job_id !== request.job_id
      || value.payload_sha256 !== request.payload_sha256
      || value.confirmed !== true
      || !Array.isArray(value.rows)
      || value.rows.length > request.items.length
    ) {
      throw new Error("bridge_progress_invalid");
    }
    for (let index = 0; index < value.rows.length; index += 1) {
      const row = value.rows[index];
      if (
        !hasExactFields(row, RESULT_ROW_FIELDS)
        || row.task_id !== request.items[index].task_id
        || !Object.values(row).every(field => (
          typeof field === "string" && field.length <= MAX_BRIDGE_TEXT_LENGTH
        ))
        || !RESULT_STATUSES.has(row.status)
      ) {
        throw new Error("bridge_progress_invalid");
      }
      const success = row.status === "existing_pdf" || row.status === "downloaded";
      if (success && (
        !isPositiveInteger(Number(row.zotero_item_id))
        || !isAbsoluteWindowsPath(row.attachment_path)
        || row.reason
      )) {
        throw new Error("bridge_progress_invalid");
      }
      if (!success && (row.zotero_item_id || row.attachment_path)) {
        throw new Error("bridge_progress_invalid");
      }
    }
    for (const field of ["created_item_ids", "created_attachment_ids"]) {
      if (
        !Array.isArray(value[field])
        || !value[field].every(isPositiveInteger)
        || new Set(value[field]).size !== value[field].length
      ) {
        throw new Error("bridge_progress_invalid");
      }
    }
    if (
      !Array.isArray(value.added_memberships)
      || !value.added_memberships.every(pair => (
        Array.isArray(pair)
        && pair.length === 2
        && pair.every(isPositiveInteger)
      ))
      || new Set(value.added_memberships.map(pair => pair.join(":"))).size
        !== value.added_memberships.length
    ) {
      throw new Error("bridge_progress_invalid");
    }
    return value;
  }

  async function loadProgress(paths, entry) {
    const name = `${entry.request.job_id}.progress.json`;
    const candidates = [
      { path: io.join(paths.processing, name), location: "processing" },
      { path: io.join(paths.archive, name), location: "archive" },
    ];
    const existing = [];
    for (const candidate of candidates) {
      if (await io.exists(candidate.path)) existing.push(candidate);
    }
    if (existing.length > 1) throw new Error("bridge_progress_conflict");
    if (!existing.length) {
      const record = {
        path: candidates[0].path,
        location: "processing",
        progress: emptyProgress(entry.request),
        entry,
      };
      await replaceJSON(record.path, record.progress);
      return record;
    }
    let value;
    try {
      value = JSON.parse(await io.readUTF8(existing[0].path));
    } catch (_error) {
      throw new Error("bridge_progress_invalid");
    }
    return {
      ...existing[0],
      progress: validateProgress(value, entry.request),
      entry,
    };
  }

  async function saveProgress(record) {
    validateProgress(record.progress, record.entry.request);
    await replaceJSON(record.path, record.progress);
  }

  async function archiveProgressRecords(paths, records) {
    for (const record of records) {
      if (record.location === "archive") continue;
      const target = io.join(paths.archive, io.basename(record.path));
      await io.move(record.path, target, { noOverwrite: true });
      record.path = target;
      record.location = "archive";
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

  function validateResultDocument(value, request, rows) {
    if (
      !hasExactFields(value, RESULT_FIELDS)
      || value.schema_version !== 1
      || value.job_id !== request.job_id
      || value.payload_sha256 !== request.payload_sha256
      || typeof value.plugin_version !== "string"
      || !value.plugin_version
      || value.plugin_version.length > MAX_BRIDGE_TEXT_LENGTH
      || typeof value.zotero_version !== "string"
      || !value.zotero_version
      || value.zotero_version.length > MAX_BRIDGE_TEXT_LENGTH
      || !validUTCTimestamp(value.started_at)
      || !validUTCTimestamp(value.finished_at)
      || Date.parse(value.finished_at) < Date.parse(value.started_at)
      || JSON.stringify(value.rows) !== JSON.stringify(rows)
    ) {
      throw new Error("bridge_result_conflict");
    }
    return value;
  }

  async function publishResultDocument(path, document, request, rows) {
    if (!await io.exists(path)) return publishJSON(path, document);
    let existing;
    try {
      existing = JSON.parse(await io.readUTF8(path));
    } catch (_error) {
      throw new Error("bridge_result_conflict");
    }
    validateResultDocument(existing, request, rows);
    return path;
  }

  async function publishFailureGroup(paths, entries, status, reason) {
    const startedAt = nowISO();
    for (const entry of entries) {
      const finishedAt = nowISO();
      const rows = entry.request.items.map(item => (
        core.failureRow(item.task_id, status, reason)
      ));
      const target = io.join(paths.outbox, `${entry.request.job_id}.result.json`);
      await publishResultDocument(
        target,
        resultDocument(entry.request, rows, startedAt, finishedAt),
        entry.request,
        rows,
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

  async function assertProcessingAPI(libraryID) {
    if (
      !zotero
      || PROCESSING_METHODS.some(method => typeof zotero[method] !== "function")
    ) {
      throw new Error("zotero_api_unavailable");
    }
    await zotero.assertProcessingAPI(libraryID);
  }

  async function eligibleItemDescriptors(candidates, libraryID) {
    if (!Array.isArray(candidates)) throw new Error("zotero_api_unavailable");
    const descriptors = [];
    for (const candidate of candidates) {
      const value = await zotero.describeItem(candidate, libraryID);
      if (
        !isPlainObject(value)
        || value.eligible !== true
        || value.libraryID !== libraryID
        || value.id === undefined
        || value.id === null
      ) {
        continue;
      }
      descriptors.push({ ...value, item: value.item || candidate });
    }
    return descriptors;
  }

  async function resolveItem(requestItem, libraryID) {
    const doi = core.normalizeDOI(requestItem.doi);
    if (doi) {
      const descriptors = await eligibleItemDescriptors(
        await zotero.searchByDOI(libraryID, doi),
        libraryID,
      );
      const exact = descriptors.filter(candidate => (
        core.normalizeDOI(candidate.doi) === doi
      ));
      if (exact.length > 1) throw new Error("metadata_uncertain");
      return exact.length === 1 ? exact[0].item : null;
    }

    const title = String(requestItem.title || "")
      .normalize("NFKC")
      .replace(/\s+/g, " ")
      .trim();
    const hasDisambiguator = Boolean(
      String(requestItem.year || "").trim()
      || core.firstCreatorKey(requestItem.authors),
    );
    if (!title || !hasDisambiguator) throw new Error("metadata_uncertain");
    const fragment = title.slice(0, MAX_TITLE_SEARCH_LENGTH);
    const descriptors = await eligibleItemDescriptors(
      await zotero.searchByTitle(libraryID, fragment),
      libraryID,
    );
    const selected = core.chooseCandidate(requestItem, descriptors);
    return selected ? selected.item : null;
  }

  async function ensureCollection(libraryID, name) {
    const collection = await zotero.ensureCollection(libraryID, name);
    if (
      !collection
      || collection.id === undefined
      || collection.id === null
      || collection.libraryID !== libraryID
      || collection.name !== name
      || collection.deleted === true
    ) {
      throw new Error("plugin_error");
    }
    return collection;
  }

  function recordID(values, id) {
    const numericID = Number(id);
    if (!isPositiveInteger(numericID)) throw new Error("zotero_api_unavailable");
    if (!values.includes(numericID)) values.push(numericID);
    return numericID;
  }

  function recordMembership(values, itemID, collectionID) {
    const pair = [Number(itemID), Number(collectionID)];
    if (!pair.every(isPositiveInteger)) throw new Error("zotero_api_unavailable");
    if (!values.some(value => value[0] === pair[0] && value[1] === pair[1])) {
      values.push(pair);
    }
    return pair;
  }

  async function importByDOI(doi, libraryID, collectionID, progress = null) {
    const normalized = core.normalizeDOI(doi);
    if (!normalized) throw new Error("not_found");
    const translated = await zotero.translateByDOI(normalized, libraryID, collectionID);
    const descriptors = await eligibleItemDescriptors(translated, libraryID);
    if (progress) {
      for (const descriptor of descriptors) {
        const itemID = recordID(progress.created_item_ids, descriptor.id);
        recordMembership(progress.added_memberships, itemID, collectionID);
      }
    }
    const exact = descriptors.filter(candidate => (
      core.normalizeDOI(candidate.doi) === normalized
    ));
    if (exact.length > 1) throw new Error("metadata_uncertain");
    if (!exact.length) throw new Error("not_found");
    return exact[0].item;
  }

  function isAbsoluteWindowsPath(path) {
    return typeof path === "string"
      && path === path.trim()
      && ABSOLUTE_WINDOWS_PATH_RE.test(path);
  }

  async function describePDFAttachment(attachment, item) {
    const descriptor = await zotero.describeAttachment(attachment, item);
    if (!isPlainObject(descriptor) || descriptor.eligible !== true) return null;
    const contentType = String(descriptor.contentType || "")
      .split(";", 1)[0]
      .trim()
      .toLocaleLowerCase("und");
    const path = typeof descriptor.path === "string" ? descriptor.path : "";
    if (contentType !== "application/pdf" || !isAbsoluteWindowsPath(path)) return null;
    return {
      attachment: descriptor.attachment || attachment,
      attachmentID: String(descriptor.id || ""),
      path,
    };
  }

  async function findPDFAttachment(item) {
    const attachments = await zotero.listAttachments(item);
    if (!Array.isArray(attachments)) throw new Error("zotero_api_unavailable");
    for (const attachment of attachments) {
      const match = await describePDFAttachment(attachment, item);
      if (match) return match;
    }
    return null;
  }

  async function addAvailablePDFOnce(item) {
    const created = await zotero.addAvailablePDF(item);
    if (created) {
      const direct = await describePDFAttachment(created, item);
      if (direct) return direct;
    }
    return findPDFAttachment(item);
  }

  async function collectionForContext(context) {
    if (!context.collectionPromise) {
      const pending = ensureCollection(context.libraryID, context.collectionName);
      context.collectionPromise = pending.catch(error => {
        context.collectionPromise = null;
        throw error;
      });
    }
    const collection = await context.collectionPromise;
    context.collectionID = collection.id;
    return collection;
  }

  function zoteroItemID(item) {
    const value = Number(item?.id);
    if (!Number.isInteger(value) || value <= 0) throw new Error("zotero_api_unavailable");
    return String(value);
  }

  async function processItem(requestItem, context) {
    let item = await resolveItem(requestItem, context.libraryID);
    let collection = null;
    let imported = false;
    if (item) {
      context.preexistingItemIDs.add(Number(item.id));
    }
    if (!item) {
      const doi = core.normalizeDOI(requestItem.doi);
      if (!doi) throw new Error("not_found");
      collection = await collectionForContext(context);
      item = await importByDOI(
        doi,
        context.libraryID,
        collection.id,
        context.progress,
      );
      imported = true;
    }
    if (!collection) collection = await collectionForContext(context);
    const membershipAdded = await zotero.addToCollection(item, collection.id);
    if (membershipAdded || imported) {
      recordMembership(context.progress.added_memberships, item.id, collection.id);
    }

    const existing = await findPDFAttachment(item);
    if (existing) {
      const attachmentID = Number(existing.attachmentID);
      if (isPositiveInteger(attachmentID)) context.preexistingAttachmentIDs.add(attachmentID);
      return core.successRow(
        requestItem.task_id,
        zoteroItemID(item),
        existing.path,
        "existing_pdf",
      );
    }

    const downloaded = await addAvailablePDFOnce(item);
    if (downloaded) {
      recordID(context.progress.created_attachment_ids, downloaded.attachmentID);
      return core.successRow(
        requestItem.task_id,
        zoteroItemID(item),
        downloaded.path,
        "downloaded",
      );
    }
    return core.failureRow(requestItem.task_id, "no_pdf", "no_available_pdf");
  }

  function failureRowFromError(taskID, error) {
    const code = errorCode(error);
    if (code === "no_available_pdf") {
      return core.failureRow(taskID, "no_pdf", code);
    }
    const status = ITEM_FAILURE_STATUSES.has(code) ? code : "plugin_error";
    return core.failureRow(taskID, status, code);
  }

  function uniqueSortedIDs(values) {
    return Array.from(new Set(values.map(Number).filter(isPositiveInteger)))
      .sort((left, right) => left - right);
  }

  function uniqueSortedMemberships(values) {
    const keyed = new Map();
    for (const pair of values) {
      if (Array.isArray(pair) && pair.length === 2 && pair.every(isPositiveInteger)) {
        keyed.set(pair.join(":"), [pair[0], pair[1]]);
      }
    }
    return Array.from(keyed.values()).sort((left, right) => (
      left[0] - right[0] || left[1] - right[1]
    ));
  }

  function summaryForRows(runID, state, rows) {
    const successCount = rows.filter(row => (
      row.status === "existing_pdf" || row.status === "downloaded"
    )).length;
    return {
      runID,
      state,
      totalCount: rows.length,
      successCount,
      failureCount: rows.length - successCount,
    };
  }

  function buildUndoLedger(group, progressRecords, context) {
    const rows = progressRecords.flatMap(record => record.progress.rows);
    const createdItemIDs = uniqueSortedIDs(
      progressRecords.flatMap(record => record.progress.created_item_ids),
    );
    const createdAttachmentIDs = uniqueSortedIDs(
      progressRecords.flatMap(record => record.progress.created_attachment_ids),
    );
    const addedMemberships = uniqueSortedMemberships(
      progressRecords.flatMap(record => record.progress.added_memberships),
    );
    const collectionIDs = new Set(addedMemberships.map(pair => pair[1]));
    if (isPositiveInteger(Number(context.collectionID))) {
      collectionIDs.add(Number(context.collectionID));
    }
    if (collectionIDs.size > 1) throw new Error("bridge_progress_invalid");
    const createdItems = new Set(createdItemIDs);
    const successfulItemIDs = rows
      .filter(row => row.status === "existing_pdf" || row.status === "downloaded")
      .map(row => Number(row.zotero_item_id));
    const preexistingItemIDs = uniqueSortedIDs([
      ...context.preexistingItemIDs,
      ...successfulItemIDs,
    ]).filter(id => !createdItems.has(id));
    const identity = identityFor(group.entries);
    const summary = summaryForRows(group.runID, "completed", rows);
    const ledger = {
      run_id: group.runID,
      library_id: group.entries[0].request.library_id,
      collection_id: collectionIDs.size ? Array.from(collectionIDs)[0] : null,
      collection_name: group.entries[0].request.collection_name,
      job_ids: identity.job_ids,
      payload_sha256: identity.payload_sha256,
      created_item_ids: createdItemIDs,
      created_attachment_ids: createdAttachmentIDs,
      added_memberships: addedMemberships,
      preexisting_item_ids: preexistingItemIDs,
      preexisting_attachment_ids: uniqueSortedIDs([...context.preexistingAttachmentIDs]),
      total_count: summary.totalCount,
      success_count: summary.successCount,
      failure_count: summary.failureCount,
      completed_at: nowISO(),
      undone: false,
      undo_result: null,
    };
    if (!validateUndoLedger(ledger)) throw new Error("bridge_state_invalid");
    return ledger;
  }

  async function saveRunCompletion(paths, group, progressRecords, context) {
    const state = await loadState(paths);
    if (!confirmationMatches(state, group.runID, group.entries)) {
      throw new Error("bridge_state_invalid");
    }
    const previous = state.runs[group.runID];
    const runs = cloneRuns(state.runs);
    runs[group.runID].completed = true;
    const ledger = previous.completed
      ? cloneUndoLedger(state.last_undo)
      : buildUndoLedger(group, progressRecords, context);
    const updated = {
      schema_version: 1,
      runs,
      last_undo: ledger,
    };
    validateState(updated);
    await replaceJSON(paths.state, updated);
    const rows = progressRecords.flatMap(record => record.progress.rows);
    lastRunSummary = summaryForRows(group.runID, "completed", rows);
    return updated;
  }

  async function processRun(group, { confirmed, paths = queuePaths() } = {}) {
    if (!confirmed) {
      await publishFailureGroup(
        paths,
        group.entries,
        "user_cancelled",
        "user_cancelled",
      );
      const totalCount = group.entries.reduce((total, entry) => (
        total + entry.request.items.length
      ), 0);
      lastRunSummary = {
        runID: group.runID,
        state: "completed",
        totalCount,
        successCount: 0,
        failureCount: totalCount,
      };
      lastStatus = `批次 ${group.runID} 已取消，未写入 Zotero。`;
      return { status: "cancelled", runID: group.runID };
    }

    const first = group.entries[0].request;
    const progressRecords = [];
    for (const entry of group.entries) {
      progressRecords.push(await loadProgress(paths, entry));
    }
    const existingRows = progressRecords.flatMap(record => record.progress.rows);
    const existingSuccesses = existingRows.filter(row => (
      row.status === "existing_pdf" || row.status === "downloaded"
    )).length;
    lastRunSummary = {
      runID: group.runID,
      state: "running",
      totalCount: group.entries.reduce((total, entry) => total + entry.request.items.length, 0),
      successCount: existingSuccesses,
      failureCount: existingRows.length - existingSuccesses,
    };
    let preflightError = null;
    try {
      await assertProcessingAPI(first.library_id);
    } catch (error) {
      preflightError = error;
    }

    const context = {
      libraryID: first.library_id,
      collectionName: first.collection_name,
      collectionPromise: null,
      collectionID: null,
      preexistingItemIDs: new Set(),
      preexistingAttachmentIDs: new Set(),
    };
    const startedAt = nowISO();
    const allRows = [];
    for (const record of progressRecords) {
      const { entry, progress } = record;
      context.progress = progress;
      for (let index = progress.rows.length; index < entry.request.items.length; index += 1) {
        const requestItem = entry.request.items[index];
        let row;
        if (preflightError) {
          row = failureRowFromError(requestItem.task_id, preflightError);
        } else {
          try {
            row = await processItem(requestItem, context);
          } catch (error) {
            row = failureRowFromError(requestItem.task_id, error);
          }
        }
        progress.rows.push(row);
        await saveProgress(record);
      }
      allRows.push(...progress.rows);
      const target = io.join(paths.outbox, `${entry.request.job_id}.result.json`);
      await publishResultDocument(
        target,
        resultDocument(entry.request, progress.rows, startedAt, nowISO()),
        entry.request,
        progress.rows,
      );
    }
    await saveRunCompletion(paths, group, progressRecords, context);
    await archiveProgressRecords(paths, progressRecords);
    await archiveEntries(paths, group.entries);
    if (preflightError) {
      lastStatus = `批次 ${group.runID} 无法访问所需 Zotero API，未写入条目。`;
      return { status: "api_unavailable", runID: group.runID, rows: allRows };
    }
    lastStatus = `批次 ${group.runID} 已处理 ${allRows.length} 项。`;
    return { status: "processed", runID: group.runID, rows: allRows };
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
    if (state.last_undo) {
      lastRunSummary = {
        runID: state.last_undo.run_id,
        state: state.last_undo.undone ? "undone" : "completed",
        totalCount: state.last_undo.total_count,
        successCount: state.last_undo.success_count,
        failureCount: state.last_undo.failure_count,
      };
    }

    const groups = groupRequests(await collectRequests(paths));
    let completeRuns = 0;
    let incompleteRuns = 0;
    for (const group of groups) {
      if (group.status === "incomplete") {
        incompleteRuns += 1;
        lastRunSummary = {
          runID: group.runID,
          state: "waiting",
          totalCount: group.entries.reduce((total, entry) => (
            total + entry.request.items.length
          ), 0),
          successCount: 0,
          failureCount: 0,
        };
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
    const labels = {
      waiting: "等待分块",
      running: "正在处理",
      completed: "已完成",
      undone: "已撤销",
    };
    const message = lastRunSummary
      ? [
        `批次：${lastRunSummary.runID}`,
        `状态：${labels[lastRunSummary.state] || lastRunSummary.state}`,
        `总数：${lastRunSummary.totalCount}`,
        `成功：${lastRunSummary.successCount}`,
        `失败：${lastRunSummary.failureCount}`,
      ].join("\n")
      : lastStatus;
    if (typeof prompt.alert === "function") prompt.alert("文献下载桥接", message);
    return message;
  }

  async function undoLastBatch() {
    const paths = await ensureQueue();
    let state;
    try {
      state = await loadState(paths);
    } catch (error) {
      const code = errorCode(error);
      reportError(code);
      if (typeof prompt.alert === "function") {
        prompt.alert("文献下载桥接", `无法读取撤销账本：${code}`);
      }
      return { status: "state_invalid" };
    }
    if (Object.values(state.runs).some(run => !run.completed)) {
      const message = "仍有已确认批次正在处理，暂不允许撤销旧批次。";
      if (typeof prompt.alert === "function") prompt.alert("文献下载桥接", message);
      return { status: "run_active" };
    }
    const ledger = state.last_undo;
    if (!ledger) {
      const message = "当前没有可撤销的批次。";
      if (typeof prompt.alert === "function") prompt.alert("文献下载桥接", message);
      return { status: "nothing_to_undo" };
    }
    if (ledger.undone) {
      const message = `批次 ${ledger.run_id} 已撤销，不能重复执行。`;
      if (typeof prompt.alert === "function") prompt.alert("文献下载桥接", message);
      return { status: "already_undone", runID: ledger.run_id };
    }

    const message = [
      `将撤销批次：${ledger.run_id}`,
      `新增条目：${ledger.created_item_ids.length}`,
      `新增附件：${ledger.created_attachment_ids.length}`,
      `集合成员关系：${ledger.added_memberships.length}`,
      "",
      "只会处理该批次账本中记录且身份仍匹配的对象。是否继续？",
    ].join("\n");
    const accepted = await prompt.confirm({
      kind: "undo",
      runID: ledger.run_id,
      itemCount: ledger.created_item_ids.length,
      attachmentCount: ledger.created_attachment_ids.length,
      membershipCount: ledger.added_memberships.length,
      message,
    });
    if (!accepted) return { status: "cancelled", runID: ledger.run_id };

    if (
      typeof zotero?.assertUndoAPI !== "function"
      || typeof zotero?.removeMembershipIfOwned !== "function"
      || typeof zotero?.eraseCreatedObject !== "function"
    ) {
      reportError("zotero_api_unavailable", { run_id: ledger.run_id });
      return { status: "api_unavailable", runID: ledger.run_id };
    }
    try {
      await zotero.assertUndoAPI();
    } catch (error) {
      reportError(errorCode(error), { run_id: ledger.run_id });
      return { status: "api_unavailable", runID: ledger.run_id };
    }

    const preexistingItems = new Set(ledger.preexisting_item_ids);
    const preexistingAttachments = new Set(ledger.preexisting_attachment_ids);
    const createdItems = ledger.created_item_ids.filter(id => !preexistingItems.has(id));
    const createdAttachments = ledger.created_attachment_ids
      .filter(id => !preexistingAttachments.has(id));
    const batchItemIDs = uniqueSortedIDs([
      ...createdItems,
      ...ledger.preexisting_item_ids,
      ...ledger.added_memberships.map(pair => pair[0]),
    ]);
    const identity = {
      collectionID: ledger.collection_id,
      batchItemIDs,
    };
    const removedMemberships = [];
    const deletedAttachmentIDs = [];
    const deletedItemIDs = [];
    const skippedIDs = [];

    for (const [itemID, collectionID] of [...ledger.added_memberships].reverse()) {
      if (createdItems.includes(itemID)) continue;
      try {
        if (await zotero.removeMembershipIfOwned(itemID, collectionID, ledger.library_id)) {
          removedMemberships.push([itemID, collectionID]);
        } else {
          reportError("undo_identity_mismatch", { run_id: ledger.run_id, object_id: itemID });
          skippedIDs.push(itemID);
        }
      } catch (error) {
        reportError(errorCode(error), { run_id: ledger.run_id });
        skippedIDs.push(itemID);
      }
    }
    for (const id of [...createdAttachments].reverse()) {
      try {
        if (await zotero.eraseCreatedObject(id, "attachment", ledger.library_id, identity)) {
          deletedAttachmentIDs.push(id);
        } else {
          reportError("undo_identity_mismatch", { run_id: ledger.run_id, object_id: id });
          skippedIDs.push(id);
        }
      } catch (error) {
        reportError(errorCode(error), { run_id: ledger.run_id });
        skippedIDs.push(id);
      }
    }
    for (const id of [...createdItems].reverse()) {
      try {
        if (await zotero.eraseCreatedObject(id, "item", ledger.library_id, identity)) {
          deletedItemIDs.push(id);
        } else {
          reportError("undo_identity_mismatch", { run_id: ledger.run_id, object_id: id });
          skippedIDs.push(id);
        }
      } catch (error) {
        reportError(errorCode(error), { run_id: ledger.run_id });
        skippedIDs.push(id);
      }
    }

    const undoResult = {
      finished_at: nowISO(),
      removed_memberships: removedMemberships,
      deleted_attachment_ids: deletedAttachmentIDs,
      deleted_item_ids: deletedItemIDs,
      skipped_ids: uniqueSortedIDs(skippedIDs),
    };
    const updated = {
      schema_version: 1,
      runs: cloneRuns(state.runs),
      last_undo: {
        ...cloneUndoLedger(ledger),
        undone: true,
        undo_result: undoResult,
      },
    };
    validateState(updated);
    await replaceJSON(paths.state, updated);
    lastRunSummary = {
      runID: ledger.run_id,
      state: "undone",
      totalCount: ledger.total_count,
      successCount: ledger.success_count,
      failureCount: ledger.failure_count,
    };
    lastStatus = `批次 ${ledger.run_id} 已完成安全撤销。`;
    return { status: "undone", runID: ledger.run_id, result: undoResult };
  }

  return {
    queuePaths,
    readRequest,
    publishJSON,
    scanNow,
    confirmRun,
    processRun,
    resolveItem,
    findPDFAttachment,
    importByDOI,
    ensureCollection,
    addAvailablePDFOnce,
    processItem,
    startup,
    shutdown,
    showStatus,
    undoLastBatch,
  };
});
