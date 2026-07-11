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
        Zotero.Collections?.getAsync,
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
    async findCollectionByName(libraryID, name) {
      const matches = Zotero.Collections.getByLibrary(libraryID, true, false)
        .filter(collection => !collection.deleted && collection.name === name);
      if (matches.length > 1) throw new Error("metadata_uncertain");
      return matches.length === 1 ? matches[0] : null;
    },
    async createCollection(libraryID, name) {
      const collection = new Zotero.Collection();
      collection.libraryID = libraryID;
      collection.name = name;
      await collection.saveTx();
      return collection;
    },
    async getCollectionByID(libraryID, collectionID) {
      const matches = await Zotero.Collections.getAsync([collectionID]);
      const collection = Array.isArray(matches) ? matches[0] : matches;
      if (
        !collection
        || collection.deleted
        || collection.libraryID !== libraryID
        || collection.id !== collectionID
      ) {
        return null;
      }
      return collection;
    },
    async translateByDOI(doi, libraryID, collectionID, beforeWrite = null) {
      const translate = new Zotero.Translate.Search();
      translate.setIdentifier({ DOI: doi });
      const translators = await translate.getTranslators();
      if (!translators.length) throw new Error("not_found");
      translate.setTranslator(translators);
      if (typeof beforeWrite === "function") await beforeWrite();
      return translate.translate({
        libraryID,
        collections: [collectionID],
        saveAttachments: false,
      });
    },
    async addToCollection(item, collectionID, beforeWrite = null) {
      if (
        !item
        || typeof item.getCollections !== "function"
        || typeof item.addToCollection !== "function"
        || typeof item.saveTx !== "function"
      ) {
        apiUnavailable();
      }
      if (item.getCollections(false).includes(collectionID)) return false;
      if (typeof beforeWrite === "function") await beforeWrite();
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
  const CANCELLATION_FILE_RE = /^([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\.cancelled\.json$/;
  const COLLECTION_FILE_RE = /^([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\.collection\.json$/;
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
    "pending_write",
  ]);
  const PENDING_IMPORT_FIELDS = new Set([
    "kind",
    "task_id",
    "doi",
    "collection_id",
  ]);
  const PENDING_MEMBERSHIP_FIELDS = new Set([
    "kind",
    "task_id",
    "item_id",
    "collection_id",
  ]);
  const PENDING_ATTACHMENT_FIELDS = new Set([
    "kind",
    "task_id",
    "item_id",
    "preexisting_attachment_ids",
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
  const CANCELLATION_FIELDS = new Set([
    "schema_version",
    "run_id",
    "job_ids",
    "payload_sha256",
    "cancelled_at",
  ]);
  const COLLECTION_FIELDS = new Set([
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
    "undo_started_at",
    "undo_progress",
    "undone",
    "undo_result",
  ]);
  const UNDO_PROGRESS_FIELDS = new Set([
    "pending_action",
    "removed_memberships",
    "deleted_attachment_ids",
    "deleted_item_ids",
    "skipped_ids",
  ]);
  const UNDO_ACTION_FIELDS = new Set(["kind", "id", "collection_id"]);
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
    "findCollectionByName",
    "createCollection",
    "getCollectionByID",
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
  let undoInFlight = null;
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

  function fatalBridgeError(error, fallback = "bridge_checkpoint_failed") {
    let fatal = error instanceof Error ? error : new Error(fallback);
    try {
      fatal.bridgeFatal = true;
    } catch (_error) {
      fatal = new Error(errorCode(error, fallback));
      fatal.bridgeFatal = true;
    }
    return fatal;
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

  function validateUndoAction(value) {
    if (!hasExactFields(value, UNDO_ACTION_FIELDS)) return false;
    if (!isPositiveInteger(value.id)) return false;
    if (value.kind === "membership") return isPositiveInteger(value.collection_id);
    return (value.kind === "attachment" || value.kind === "item")
      && value.collection_id === null;
  }

  function validateUndoProgress(value) {
    if (!hasExactFields(value, UNDO_PROGRESS_FIELDS)) return false;
    return (value.pending_action === null || validateUndoAction(value.pending_action))
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
      || !(value.undo_started_at === null || validUTCTimestamp(value.undo_started_at))
      || !(value.undo_progress === null || validateUndoProgress(value.undo_progress))
      || typeof value.undone !== "boolean"
      || (value.undone && value.undo_started_at === null)
      || (value.undone ? !validateUndoResult(value.undo_result) : value.undo_result !== null)
      || (value.undo_started_at === null && value.undo_progress !== null)
      || (value.undo_started_at !== null && !value.undone && value.undo_progress === null)
      || (value.undone && value.undo_progress !== null)
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
    const membershipKeys = new Set(value.added_memberships.map(pair => pair.join(":")));
    const createdItemIDs = new Set(value.created_item_ids);
    const createdAttachmentIDs = new Set(value.created_attachment_ids);
    const ownedIDs = new Set([
      ...value.created_item_ids,
      ...value.created_attachment_ids,
      ...value.added_memberships.map(pair => pair[0]),
    ]);
    const outcomeBelongsToLedger = outcome => (
      outcome.removed_memberships.every(pair => membershipKeys.has(pair.join(":")))
      && outcome.deleted_attachment_ids.every(id => createdAttachmentIDs.has(id))
      && outcome.deleted_item_ids.every(id => createdItemIDs.has(id))
      && outcome.skipped_ids.every(id => ownedIDs.has(id))
    );
    if (value.undo_progress) {
      if (!outcomeBelongsToLedger(value.undo_progress)) return false;
      const pending = value.undo_progress.pending_action;
      if (pending) {
        const owned = pending.kind === "membership"
          ? membershipKeys.has(`${pending.id}:${pending.collection_id}`)
          : pending.kind === "attachment"
            ? createdAttachmentIDs.has(pending.id)
            : createdItemIDs.has(pending.id);
        if (!owned) return false;
      }
    }
    if (value.undo_result && !outcomeBelongsToLedger(value.undo_result)) return false;
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

  async function collectRequests(paths, state) {
    const entries = [];
    for (const [location, directory] of [
      ["inbox", paths.inbox],
      ["processing", paths.processing],
    ]) {
      const children = [...await io.list(directory)].sort();
      for (const path of children) {
        const name = io.basename(path);
        if (
          location === "processing"
          && (
            PROGRESS_FILE_RE.test(name)
            || CANCELLATION_FILE_RE.test(name)
            || COLLECTION_FILE_RE.test(name)
          )
        ) {
          continue;
        }
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
    const activeByRun = new Map();
    for (const entry of entries) {
      const runID = entry.request.run_id;
      if (!activeByRun.has(runID)) activeByRun.set(runID, []);
      activeByRun.get(runID).push(entry);
    }
    const knownJobIDs = new Set(entries.map(entry => entry.request.job_id));
    const recoveryIdentities = Object.entries(state?.runs || {}).map(([runID, run]) => ({
      runID,
      job_ids: run.job_ids,
      payload_sha256: run.payload_sha256,
    }));
    const cancellationRunIDs = new Set();
    for (const [runID, activeEntries] of activeByRun) {
      const stateRun = state?.runs?.[runID];
      const stateMatchesActive = stateRun && activeEntries.some(entry => {
        const index = stateRun.job_ids.indexOf(entry.request.job_id);
        return index !== -1
          && stateRun.payload_sha256[index] === entry.request.payload_sha256;
      });
      if (stateMatchesActive) continue;
      if (!activeEntries.some(entry => entry.location === "processing")) continue;
      const declaredChunks = activeEntries[0]?.request.chunk_count;
      const activeChunks = new Set(activeEntries.map(entry => entry.request.chunk_index));
      if (Number.isInteger(declaredChunks) && activeChunks.size < declaredChunks) {
        cancellationRunIDs.add(runID);
      }
    }
    if (cancellationRunIDs.size) {
      recoveryIdentities.push(
        ...await cancellationRecoveryIdentities(paths, cancellationRunIDs),
      );
    }
    for (const run of recoveryIdentities) {
      const runID = run.runID;
      const activeEntries = activeByRun.get(runID);
      if (!activeEntries?.length) continue;
      const activeMatchesLedger = activeEntries.some(entry => {
        const index = run.job_ids.indexOf(entry.request.job_id);
        return index !== -1
          && run.payload_sha256[index] === entry.request.payload_sha256;
      });
      if (!activeMatchesLedger) continue;
      for (let index = 0; index < run.job_ids.length; index += 1) {
        const jobID = run.job_ids[index];
        if (knownJobIDs.has(jobID)) continue;
        const path = io.join(paths.archive, `${jobID}.json`);
        if (!await io.exists(path)) continue;
        try {
          const request = await readRequest(path);
          if (
            request.run_id !== runID
            || request.payload_sha256 !== run.payload_sha256[index]
          ) {
            throw new Error("bridge_request_identity_invalid");
          }
          entries.push({ location: "archive", path, request });
          knownJobIDs.add(jobID);
        } catch (error) {
          reportError(errorCode(error), { file: `${jobID}.json` });
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
      if (entry.location === "archive") continue;
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
      pending_write: null,
    };
  }

  function validatePendingWrite(value, request, rowCount) {
    if (value === null) return true;
    const requestItem = request.items[rowCount];
    if (!requestItem || value.task_id !== requestItem.task_id) return false;
    if (value.kind === "import") {
      return hasExactFields(value, PENDING_IMPORT_FIELDS)
        && core.normalizeDOI(value.doi) === core.normalizeDOI(requestItem.doi)
        && Boolean(core.normalizeDOI(value.doi))
        && isPositiveInteger(value.collection_id);
    }
    if (value.kind === "membership") {
      return hasExactFields(value, PENDING_MEMBERSHIP_FIELDS)
        && isPositiveInteger(value.item_id)
        && isPositiveInteger(value.collection_id);
    }
    if (value.kind === "attachment") {
      return hasExactFields(value, PENDING_ATTACHMENT_FIELDS)
        && isPositiveInteger(value.item_id)
        && validIDArray(value.preexisting_attachment_ids);
    }
    return false;
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
      || !validatePendingWrite(value.pending_write, request, value.rows.length)
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

  function cancellationMarkerName(group) {
    const identity = identityFor(group.entries);
    return `${identity.job_ids[0]}.cancelled.json`;
  }

  function validateCancellationIdentity(value, expectedFirstJobID = null) {
    if (
      !hasExactFields(value, CANCELLATION_FIELDS)
      || value.schema_version !== 1
      || typeof value.run_id !== "string"
      || !value.run_id
      || value.run_id.length > MAX_BRIDGE_TEXT_LENGTH
      || !Array.isArray(value.job_ids)
      || !value.job_ids.length
      || !value.job_ids.every(id => typeof id === "string" && JOB_ID_RE.test(id))
      || new Set(value.job_ids).size !== value.job_ids.length
      || !Array.isArray(value.payload_sha256)
      || value.payload_sha256.length !== value.job_ids.length
      || !value.payload_sha256.every(hash => (
        typeof hash === "string" && SHA256_RE.test(hash)
      ))
      || !validUTCTimestamp(value.cancelled_at)
      || (expectedFirstJobID !== null && value.job_ids[0] !== expectedFirstJobID)
    ) {
      throw new Error("bridge_cancellation_invalid");
    }
    return value;
  }

  async function cancellationRecoveryIdentities(paths, wantedRunIDs) {
    const identities = new Map();
    for (const directory of [paths.processing, paths.archive]) {
      for (const path of await io.list(directory)) {
        const name = io.basename(path);
        const match = CANCELLATION_FILE_RE.exec(name);
        if (!match) continue;
        try {
          const marker = validateCancellationIdentity(
            JSON.parse(await io.readUTF8(path)),
            match[1],
          );
          if (!wantedRunIDs.has(marker.run_id)) continue;
          const key = JSON.stringify([
            marker.run_id,
            marker.job_ids,
            marker.payload_sha256,
          ]);
          identities.set(key, {
            runID: marker.run_id,
            job_ids: marker.job_ids,
            payload_sha256: marker.payload_sha256,
          });
        } catch (error) {
          reportError(errorCode(error), { file: name });
        }
      }
    }
    return [...identities.values()];
  }

  function validateCancellationMarker(value, group) {
    const identity = identityFor(group.entries);
    validateCancellationIdentity(value, identity.job_ids[0]);
    if (
      value.run_id !== group.runID
      || !arraysEqual(value.job_ids, identity.job_ids)
      || !arraysEqual(value.payload_sha256, identity.payload_sha256)
    ) {
      throw new Error("bridge_cancellation_invalid");
    }
    return value;
  }

  async function loadCancellationMarker(paths, group) {
    const name = cancellationMarkerName(group);
    const candidates = [
      { path: io.join(paths.processing, name), location: "processing" },
      { path: io.join(paths.archive, name), location: "archive" },
    ];
    const existing = [];
    for (const candidate of candidates) {
      if (await io.exists(candidate.path)) existing.push(candidate);
    }
    if (existing.length > 1) throw new Error("bridge_cancellation_conflict");
    if (!existing.length) return null;
    let value;
    try {
      value = JSON.parse(await io.readUTF8(existing[0].path));
    } catch (_error) {
      throw new Error("bridge_cancellation_invalid");
    }
    validateCancellationMarker(value, group);
    return { ...existing[0], value };
  }

  async function ensureCancellationMarker(paths, group) {
    const existing = await loadCancellationMarker(paths, group);
    if (existing) return existing;
    const identity = identityFor(group.entries);
    const marker = {
      schema_version: 1,
      run_id: group.runID,
      job_ids: identity.job_ids,
      payload_sha256: identity.payload_sha256,
      cancelled_at: nowISO(),
    };
    const path = io.join(paths.processing, cancellationMarkerName(group));
    await publishJSON(path, marker);
    return { path, location: "processing", value: marker };
  }

  async function archiveCancellationMarker(paths, marker) {
    if (marker.location === "archive") return;
    const target = io.join(paths.archive, io.basename(marker.path));
    await io.move(marker.path, target, { noOverwrite: true });
    marker.path = target;
    marker.location = "archive";
  }

  function collectionMarkerName(group) {
    const identity = identityFor(group.entries);
    return `${identity.job_ids[0]}.collection.json`;
  }

  function validateCollectionMarker(value, group) {
    const identity = identityFor(group.entries);
    const request = group.entries[0].request;
    if (
      !hasExactFields(value, COLLECTION_FIELDS)
      || value.schema_version !== 1
      || value.run_id !== group.runID
      || !arraysEqual(value.job_ids, identity.job_ids)
      || !arraysEqual(value.payload_sha256, identity.payload_sha256)
      || value.library_id !== request.library_id
      || value.collection_name !== request.collection_name
      || !(
        (
          value.phase === "pending"
          && value.collection_id === null
          && value.created === null
        )
        || (
          value.phase === "complete"
          && isPositiveInteger(value.collection_id)
          && typeof value.created === "boolean"
        )
      )
      || !validUTCTimestamp(value.recorded_at)
    ) {
      throw new Error("bridge_collection_invalid");
    }
    return value;
  }

  async function loadCollectionMarker(paths, group) {
    const name = collectionMarkerName(group);
    const candidates = [
      { path: io.join(paths.processing, name), location: "processing" },
      { path: io.join(paths.archive, name), location: "archive" },
    ];
    const existing = [];
    for (const candidate of candidates) {
      if (await io.exists(candidate.path)) existing.push(candidate);
    }
    if (existing.length > 1) throw new Error("bridge_collection_conflict");
    if (!existing.length) return null;
    let value;
    try {
      value = JSON.parse(await io.readUTF8(existing[0].path));
    } catch (_error) {
      throw new Error("bridge_collection_invalid");
    }
    validateCollectionMarker(value, group);
    return { ...existing[0], value };
  }

  async function archiveCollectionMarker(paths, marker) {
    if (!marker || marker.location === "archive") return;
    const target = io.join(paths.archive, io.basename(marker.path));
    await io.move(marker.path, target, { noOverwrite: true });
    marker.path = target;
    marker.location = "archive";
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

  async function publishFailureGroup(
    paths,
    entries,
    status,
    reason,
    { archive = true } = {},
  ) {
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
    if (archive) await archiveEntries(paths, entries);
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

  function validateCollectionObject(collection, libraryID, name) {
    if (
      !collection
      || !isPositiveInteger(Number(collection.id))
      || collection.libraryID !== libraryID
      || collection.name !== name
      || collection.deleted === true
    ) {
      throw new Error("plugin_error");
    }
    return collection;
  }

  async function findCollectionByName(libraryID, name) {
    const collection = await zotero.findCollectionByName(libraryID, name);
    return collection === null
      ? null
      : validateCollectionObject(collection, libraryID, name);
  }

  async function createCollection(libraryID, name) {
    return validateCollectionObject(
      await zotero.createCollection(libraryID, name),
      libraryID,
      name,
    );
  }

  async function ensureCollection(libraryID, name) {
    const existing = await findCollectionByName(libraryID, name);
    if (existing) return { collection: existing, created: false };
    return { collection: await createCollection(libraryID, name), created: true };
  }

  async function getCollectionByID(libraryID, collectionID) {
    const collection = await zotero.getCollectionByID(libraryID, collectionID);
    if (collection === null) return null;
    if (
      !collection
      || collection.id !== collectionID
      || collection.libraryID !== libraryID
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

  async function beginPendingWrite(context, pendingWrite) {
    if (context.progress.pending_write !== null) {
      throw fatalBridgeError(new Error("bridge_progress_invalid"));
    }
    context.progress.pending_write = pendingWrite;
    await context.checkpoint();
  }

  async function finishPendingWrite(context, recordOwnership = null) {
    if (typeof recordOwnership === "function") recordOwnership();
    context.progress.pending_write = null;
    await context.checkpoint();
  }

  async function importByDOI(
    doi,
    libraryID,
    collectionID,
    progress = null,
    checkpoint = null,
    taskID = "",
  ) {
    const normalized = core.normalizeDOI(doi);
    if (!normalized) throw new Error("not_found");
    const beforeWrite = progress && typeof checkpoint === "function"
      ? async () => {
        if (progress.pending_write !== null) {
          throw fatalBridgeError(new Error("bridge_progress_invalid"));
        }
        progress.pending_write = {
          kind: "import",
          task_id: taskID,
          doi: normalized,
          collection_id: collectionID,
        };
        try {
          await checkpoint();
        } catch (error) {
          throw fatalBridgeError(error);
        }
      }
      : null;
    let translated;
    try {
      translated = await zotero.translateByDOI(
        normalized,
        libraryID,
        collectionID,
        beforeWrite,
      );
    } catch (error) {
      if (progress?.pending_write?.kind === "import") throw fatalBridgeError(error);
      throw error;
    }
    if (!Array.isArray(translated)) {
      const error = new Error("zotero_api_unavailable");
      if (progress?.pending_write?.kind === "import") throw fatalBridgeError(error);
      throw error;
    }
    if (progress) {
      try {
        for (const item of translated) {
          const itemID = recordID(progress.created_item_ids, item?.id);
          recordMembership(progress.added_memberships, itemID, collectionID);
        }
        progress.pending_write = null;
        if (typeof checkpoint === "function") await checkpoint();
      } catch (error) {
        throw fatalBridgeError(error);
      }
    }
    const descriptors = await eligibleItemDescriptors(translated, libraryID);
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

  async function addAvailablePDFOnce(
    item,
    progress = null,
    checkpoint = null,
    taskID = "",
  ) {
    if (progress && typeof checkpoint === "function") {
      if (progress.pending_write !== null) {
        throw fatalBridgeError(new Error("bridge_progress_invalid"));
      }
      const attachments = await zotero.listAttachments(item);
      if (!Array.isArray(attachments)) throw new Error("zotero_api_unavailable");
      progress.pending_write = {
        kind: "attachment",
        task_id: taskID,
        item_id: Number(item.id),
        preexisting_attachment_ids: uniqueSortedIDs(
          attachments.map(attachment => attachment?.id),
        ),
      };
      try {
        await checkpoint();
      } catch (error) {
        throw fatalBridgeError(error);
      }
    }
    let created;
    try {
      created = await zotero.addAvailablePDF(item);
    } catch (error) {
      if (progress?.pending_write?.kind === "attachment") throw fatalBridgeError(error);
      throw error;
    }
    if (created) {
      if (progress) {
        try {
          recordID(progress.created_attachment_ids, created.id);
        } catch (error) {
          throw fatalBridgeError(error);
        }
      }
    }
    if (progress) {
      try {
        progress.pending_write = null;
        if (typeof checkpoint === "function") await checkpoint();
      } catch (error) {
        throw fatalBridgeError(error);
      }
    }
    if (created) {
      const direct = await describePDFAttachment(created, item);
      if (direct) return direct;
    }
    return findPDFAttachment(item);
  }

  async function collectionForContext(context) {
    if (!context.collectionPromise) {
      const pending = (async () => {
        const identity = identityFor(context.group.entries);
        const markerPath = io.join(
          context.paths.processing,
          collectionMarkerName(context.group),
        );
        const markerValue = (phase, collectionID, created) => ({
          schema_version: 1,
          run_id: context.group.runID,
          job_ids: identity.job_ids,
          payload_sha256: identity.payload_sha256,
          library_id: context.libraryID,
          collection_id: collectionID,
          collection_name: context.collectionName,
          created,
          phase,
          recorded_at: nowISO(),
        });
        const completeMarker = async (record, collection, created) => {
          const value = markerValue("complete", Number(collection.id), created);
          validateCollectionMarker(value, context.group);
          if (record) {
            await replaceJSON(record.path, value);
            record.value = value;
          } else {
            await publishJSON(markerPath, value);
            record = { path: markerPath, location: "processing", value };
          }
          context.collectionMarker = record;
          return collection;
        };

        if (context.collectionMarker) {
          if (context.collectionMarker.value.phase === "pending") {
            throw fatalBridgeError(new Error("write_outcome_uncertain"));
          }
          let collection;
          try {
            collection = await getCollectionByID(
              context.libraryID,
              context.collectionMarker.value.collection_id,
            );
          } catch (error) {
            throw fatalBridgeError(error, "bridge_collection_invalid");
          }
          if (
            !collection
            || collection.id !== context.collectionMarker.value.collection_id
            || collection.libraryID !== context.libraryID
            || collection.name !== context.collectionName
            || collection.deleted === true
          ) {
            throw fatalBridgeError(new Error("bridge_collection_invalid"));
          }
          return collection;
        }

        let existing;
        try {
          existing = await findCollectionByName(context.libraryID, context.collectionName);
        } catch (error) {
          if (errorCode(error) === "metadata_uncertain") throw error;
          throw fatalBridgeError(error, "bridge_collection_invalid");
        }
        if (existing) {
          try {
            return await completeMarker(null, existing, false);
          } catch (error) {
            throw fatalBridgeError(error, "bridge_collection_invalid");
          }
        }

        const marker = markerValue("pending", null, null);
        const record = { path: markerPath, location: "processing", value: marker };
        try {
          validateCollectionMarker(marker, context.group);
          await publishJSON(markerPath, marker);
          context.collectionMarker = record;
          const collection = await createCollection(
            context.libraryID,
            context.collectionName,
          );
          return await completeMarker(record, collection, true);
        } catch (error) {
          throw fatalBridgeError(error, "bridge_collection_invalid");
        }
      })();
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
    if (context.progress.pending_write !== null) {
      throw fatalBridgeError(new Error("write_outcome_uncertain"));
    }
    let item = await resolveItem(requestItem, context.libraryID);
    let collection = null;
    if (item && !context.progress.created_item_ids.includes(Number(item.id))) {
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
        context.checkpoint,
        requestItem.task_id,
      );
    }
    if (!collection) collection = await collectionForContext(context);
    let membershipAdded;
    try {
      membershipAdded = await zotero.addToCollection(
        item,
        collection.id,
        async () => beginPendingWrite(context, {
          kind: "membership",
          task_id: requestItem.task_id,
          item_id: Number(item.id),
          collection_id: collection.id,
        }),
      );
    } catch (error) {
      if (context.progress.pending_write?.kind === "membership") {
        throw fatalBridgeError(error);
      }
      throw error;
    }
    if (membershipAdded) {
      if (context.progress.pending_write?.kind !== "membership") {
        throw fatalBridgeError(new Error("bridge_progress_invalid"));
      }
      await finishPendingWrite(context, () => {
        recordMembership(context.progress.added_memberships, item.id, collection.id);
      });
    } else if (context.progress.pending_write !== null) {
      throw fatalBridgeError(new Error("bridge_progress_invalid"));
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

    const downloaded = await addAvailablePDFOnce(
      item,
      context.progress,
      context.checkpoint,
      requestItem.task_id,
    );
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
    const createdAttachments = new Set(createdAttachmentIDs);
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
      preexisting_attachment_ids: uniqueSortedIDs([...context.preexistingAttachmentIDs])
        .filter(id => !createdAttachments.has(id)),
      total_count: summary.totalCount,
      success_count: summary.successCount,
      failure_count: summary.failureCount,
      completed_at: nowISO(),
      undo_started_at: null,
      undo_progress: null,
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

  async function processRun(
    group,
    { confirmed, paths = queuePaths(), cancellationMarker = null } = {},
  ) {
    if (!confirmed) {
      const marker = cancellationMarker || await ensureCancellationMarker(paths, group);
      await publishFailureGroup(
        paths,
        group.entries,
        "user_cancelled",
        "user_cancelled",
        { archive: false },
      );
      await archiveCancellationMarker(paths, marker);
      await archiveEntries(paths, group.entries);
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
    const collectionMarker = await loadCollectionMarker(paths, group);
    const collectionWriteUncertain = collectionMarker?.value.phase === "pending";
    let sealedUncertainWrite = false;
    for (const record of progressRecords) {
      const { entry, progress } = record;
      if (collectionWriteUncertain) {
        const remaining = entry.request.items.slice(progress.rows.length);
        if (remaining.length) {
          for (const requestItem of remaining) {
            reportError("write_outcome_uncertain", {
              run_id: group.runID,
              task_id: requestItem.task_id,
            });
            progress.rows.push(core.failureRow(
              requestItem.task_id,
              "plugin_error",
              "write_outcome_uncertain",
            ));
          }
          progress.pending_write = null;
          await saveProgress(record);
          sealedUncertainWrite = true;
        }
      } else if (progress.pending_write !== null) {
        const requestItem = entry.request.items[progress.rows.length];
        reportError("write_outcome_uncertain", {
          run_id: group.runID,
          task_id: requestItem.task_id,
        });
        progress.rows.push(core.failureRow(
          requestItem.task_id,
          "plugin_error",
          "write_outcome_uncertain",
        ));
        progress.pending_write = null;
        await saveProgress(record);
        sealedUncertainWrite = true;
      }
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
    const hasRemainingItems = progressRecords.some(record => (
      record.progress.rows.length < record.entry.request.items.length
    ));
    if (sealedUncertainWrite && hasRemainingItems) {
      lastStatus = `批次 ${group.runID} 已本地封存不确定写入，等待下一次安全扫描。`;
      return {
        status: "write_outcome_uncertain",
        runID: group.runID,
        rows: existingRows,
      };
    }
    let preflightError = null;
    if (hasRemainingItems) {
      try {
        await assertProcessingAPI(first.library_id);
      } catch (error) {
        preflightError = error;
      }
    }

    const context = {
      group,
      paths,
      libraryID: first.library_id,
      collectionName: first.collection_name,
      collectionPromise: null,
      collectionMarker,
      collectionID: collectionMarker?.value.collection_id ?? null,
      checkpoint: null,
      preexistingItemIDs: new Set(),
      preexistingAttachmentIDs: new Set(),
    };
    const startedAt = nowISO();
    const allRows = [];
    for (const record of progressRecords) {
      const { entry, progress } = record;
      context.progress = progress;
      context.checkpoint = async () => {
        try {
          await saveProgress(record);
        } catch (error) {
          throw fatalBridgeError(error);
        }
      };
      for (let index = progress.rows.length; index < entry.request.items.length; index += 1) {
        const requestItem = entry.request.items[index];
        let row;
        if (preflightError) {
          row = failureRowFromError(requestItem.task_id, preflightError);
        } else {
          try {
            row = await processItem(requestItem, context);
          } catch (error) {
            if (error?.bridgeFatal === true) throw error;
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
    await archiveCollectionMarker(paths, context.collectionMarker);
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

    const groups = groupRequests(await collectRequests(paths, state));
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
        const cancellationMarker = await loadCancellationMarker(paths, group);
        if (cancellationMarker) {
          await processRun(group, {
            confirmed: false,
            paths,
            cancellationMarker,
          });
        } else {
          const alreadyConfirmed = confirmationMatches(state, group.runID, group.entries);
          let confirmed = alreadyConfirmed;
          if (!alreadyConfirmed) {
            confirmed = await confirmRun(group);
            if (confirmed) {
              state = await saveConfirmation(paths, state, group.runID, group.entries);
            }
          }
          await processRun(group, { confirmed, paths });
        }
      } catch (error) {
        reportError(errorCode(error), { run_id: group.runID });
      }
      try {
        state = await loadState(paths);
      } catch (error) {
        reportError(errorCode(error), { run_id: group.runID });
        return { status: "state_invalid", completeRuns, incompleteRuns };
      }
    }

    if (!groups.length) lastStatus = "没有待处理的 Zotero 桥接任务。";
    else if (incompleteRuns) lastStatus = `有 ${incompleteRuns} 个批次仍在等待完整分块。`;
    return { status: "scanned", completeRuns, incompleteRuns };
  }

  function scanNow() {
    if (scanInFlight) return scanInFlight;
    const current = Promise.resolve(undoInFlight).then(scanOnce);
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

  async function performUndoLastBatch() {
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

    const resuming = ledger.undo_started_at !== null;
    if (!resuming) {
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
    }

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

    if (!resuming) {
      const startedLedger = {
        ...cloneUndoLedger(ledger),
        undo_started_at: nowISO(),
        undo_progress: {
          pending_action: null,
          removed_memberships: [],
          deleted_attachment_ids: [],
          deleted_item_ids: [],
          skipped_ids: [],
        },
      };
      const startedState = {
        schema_version: 1,
        runs: cloneRuns(state.runs),
        last_undo: startedLedger,
      };
      validateState(startedState);
      await replaceJSON(paths.state, startedState);
      state = startedState;
      ledger.undo_started_at = startedLedger.undo_started_at;
      ledger.undo_progress = startedLedger.undo_progress;
    }

    async function checkpointUndoProgress() {
      const updated = {
        schema_version: 1,
        runs: cloneRuns(state.runs),
        last_undo: cloneUndoLedger(ledger),
      };
      validateState(updated);
      await replaceJSON(paths.state, updated);
      state = updated;
    }

    const undoProgress = ledger.undo_progress;
    if (undoProgress.pending_action) {
      recordID(undoProgress.skipped_ids, undoProgress.pending_action.id);
      undoProgress.pending_action = null;
      await checkpointUndoProgress();
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
    for (const [itemID, collectionID] of [...ledger.added_memberships].reverse()) {
      if (createdItems.includes(itemID)) continue;
      if (
        undoProgress.removed_memberships.some(pair => (
          pair[0] === itemID && pair[1] === collectionID
        ))
        || undoProgress.skipped_ids.includes(itemID)
      ) {
        continue;
      }
      undoProgress.pending_action = {
        kind: "membership",
        id: itemID,
        collection_id: collectionID,
      };
      await checkpointUndoProgress();
      try {
        if (await zotero.removeMembershipIfOwned(itemID, collectionID, ledger.library_id)) {
          recordMembership(undoProgress.removed_memberships, itemID, collectionID);
        } else {
          reportError("undo_identity_mismatch", { run_id: ledger.run_id, object_id: itemID });
          recordID(undoProgress.skipped_ids, itemID);
        }
      } catch (error) {
        if (error?.bridgeFatal === true) throw error;
        reportError(errorCode(error), { run_id: ledger.run_id });
        recordID(undoProgress.skipped_ids, itemID);
      }
      undoProgress.pending_action = null;
      await checkpointUndoProgress();
    }
    for (const id of [...createdAttachments].reverse()) {
      if (
        undoProgress.deleted_attachment_ids.includes(id)
        || undoProgress.skipped_ids.includes(id)
      ) {
        continue;
      }
      undoProgress.pending_action = { kind: "attachment", id, collection_id: null };
      await checkpointUndoProgress();
      try {
        if (await zotero.eraseCreatedObject(id, "attachment", ledger.library_id, identity)) {
          recordID(undoProgress.deleted_attachment_ids, id);
        } else {
          reportError("undo_identity_mismatch", { run_id: ledger.run_id, object_id: id });
          recordID(undoProgress.skipped_ids, id);
        }
      } catch (error) {
        if (error?.bridgeFatal === true) throw error;
        reportError(errorCode(error), { run_id: ledger.run_id });
        recordID(undoProgress.skipped_ids, id);
      }
      undoProgress.pending_action = null;
      await checkpointUndoProgress();
    }
    for (const id of [...createdItems].reverse()) {
      if (
        undoProgress.deleted_item_ids.includes(id)
        || undoProgress.skipped_ids.includes(id)
      ) {
        continue;
      }
      undoProgress.pending_action = { kind: "item", id, collection_id: null };
      await checkpointUndoProgress();
      try {
        if (await zotero.eraseCreatedObject(id, "item", ledger.library_id, identity)) {
          recordID(undoProgress.deleted_item_ids, id);
        } else {
          reportError("undo_identity_mismatch", { run_id: ledger.run_id, object_id: id });
          recordID(undoProgress.skipped_ids, id);
        }
      } catch (error) {
        if (error?.bridgeFatal === true) throw error;
        reportError(errorCode(error), { run_id: ledger.run_id });
        recordID(undoProgress.skipped_ids, id);
      }
      undoProgress.pending_action = null;
      await checkpointUndoProgress();
    }

    const undoResult = {
      finished_at: nowISO(),
      removed_memberships: undoProgress.removed_memberships,
      deleted_attachment_ids: undoProgress.deleted_attachment_ids,
      deleted_item_ids: undoProgress.deleted_item_ids,
      skipped_ids: uniqueSortedIDs(undoProgress.skipped_ids),
    };
    const updated = {
      schema_version: 1,
      runs: cloneRuns(state.runs),
      last_undo: {
        ...cloneUndoLedger(ledger),
        undo_progress: null,
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

  function undoLastBatch() {
    if (undoInFlight) return undoInFlight;
    undoInFlight = Promise.resolve(scanInFlight).then(performUndoLastBatch);
    undoInFlight = undoInFlight.then(
      result => {
        undoInFlight = null;
        return result;
      },
      error => {
        undoInFlight = null;
        throw error;
      },
    );
    return undoInFlight;
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
    getCollectionByID,
    addAvailablePDFOnce,
    processItem,
    startup,
    shutdown,
    showStatus,
    undoLastBatch,
  };
});
