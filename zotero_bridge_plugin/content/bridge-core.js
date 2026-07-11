(function (factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else globalThis.ZoteroPaperBridgeCore = api;
})(function () {
  const SCHEMA_VERSION = 1;
  const MAX_ITEMS_PER_JOB = 100;
  const MAX_TEXT_LENGTH = 4096;
  const JOB_ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
  const SHA256_RE = /^[0-9a-f]{64}$/;
  const UTC_TIMESTAMP_RE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?Z$/;
  const REQUEST_FIELDS = new Set([
    "schema_version",
    "job_id",
    "payload_sha256",
    "created_at",
    "expires_at",
    "run_id",
    "library_id",
    "collection_name",
    "chunk_index",
    "chunk_count",
    "items",
  ]);
  const ITEM_FIELDS = new Set(["task_id", "doi", "title", "authors", "year"]);
  const SUCCESS_STATUSES = new Set(["existing_pdf", "downloaded"]);
  const FAILURE_STATUSES = new Set([
    "no_pdf",
    "not_found",
    "metadata_uncertain",
    "zotero_unavailable",
    "no_attachment",
    "download_failed",
    "zotero_api_unavailable",
    "user_cancelled",
    "job_expired",
    "job_id_conflict",
    "plugin_error",
  ]);

  function fail(code) {
    throw new Error(code);
  }

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function hasExactFields(value, expected) {
    if (!isPlainObject(value)) return false;
    const keys = Object.keys(value);
    return keys.length === expected.size && keys.every(key => expected.has(key));
  }

  function stableJSON(value) {
    if (Array.isArray(value)) return `[${value.map(stableJSON).join(",")}]`;
    if (isPlainObject(value)) {
      return `{${Object.keys(value).sort().map(key => (
        `${JSON.stringify(key)}:${stableJSON(value[key])}`
      )).join(",")}}`;
    }
    return JSON.stringify(value);
  }

  function canonicalPayload(request) {
    const payload = {};
    for (const key of Array.from(REQUEST_FIELDS).sort()) {
      if (key !== "payload_sha256") payload[key] = request[key];
    }
    return stableJSON(payload);
  }

  async function sha256Hex(text) {
    if (!globalThis.crypto || !globalThis.crypto.subtle || !globalThis.TextEncoder) {
      fail("zotero_api_unavailable");
    }
    const bytes = new TextEncoder().encode(text);
    const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(digest), value => (
      value.toString(16).padStart(2, "0")
    )).join("");
  }

  async function payloadHash(request) {
    return sha256Hex(canonicalPayload(request));
  }

  function normalizeDOI(value) {
    let normalized = String(value || "").trim();
    normalized = normalized.replace(/^doi:\s*/i, "");
    normalized = normalized.replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, "");
    return normalized.trim().toLocaleLowerCase("und");
  }

  function normalizeTitle(value) {
    return String(value || "")
      .normalize("NFKC")
      .toLocaleLowerCase("und")
      .replace(/[\p{White_Space}\p{P}\p{S}]/gu, "");
  }

  function firstCreatorKey(authors) {
    const raw = String(authors || "").trim();
    if (!raw) return "";
    const first = raw.split(/;|\band\b/i, 1)[0].split(",", 1)[0];
    return normalizeTitle(first);
  }

  function parseUTCInstant(value, errorCode) {
    if (typeof value !== "string") fail(errorCode);
    const match = UTC_TIMESTAMP_RE.exec(value);
    if (!match) fail(errorCode);
    const [
      _all,
      yearText,
      monthText,
      dayText,
      hourText,
      minuteText,
      secondText,
      fractionText = "",
    ] = match;
    const year = Number(yearText);
    const month = Number(monthText);
    const day = Number(dayText);
    const hour = Number(hourText);
    const minute = Number(minuteText);
    const second = Number(secondText);
    const baseMilliseconds = Date.UTC(year, month - 1, day, hour, minute, second);
    const date = new Date(baseMilliseconds);
    if (
      Number.isNaN(baseMilliseconds)
      || date.getUTCFullYear() !== year
      || date.getUTCMonth() !== month - 1
      || date.getUTCDate() !== day
      || date.getUTCHours() !== hour
      || date.getUTCMinutes() !== minute
      || date.getUTCSeconds() !== second
    ) {
      fail(errorCode);
    }
    const microseconds = Number((fractionText + "000000").slice(0, 6));
    return BigInt(baseMilliseconds) * 1000n + BigInt(microseconds);
  }

  function validateText(value, errorCode, { required = false } = {}) {
    if (typeof value !== "string" || value.length > MAX_TEXT_LENGTH || (required && !value)) {
      fail(errorCode);
    }
  }

  async function validateRequest(request, now = new Date()) {
    if (!hasExactFields(request, REQUEST_FIELDS)) fail("bridge_request_fields_invalid");
    if (request.schema_version !== SCHEMA_VERSION) fail("bridge_schema_version_invalid");
    if (typeof request.job_id !== "string" || !JOB_ID_RE.test(request.job_id)) {
      fail("bridge_job_id_invalid");
    }
    for (const field of [
      "payload_sha256",
      "created_at",
      "expires_at",
      "run_id",
      "collection_name",
    ]) {
      validateText(request[field], "bridge_request_value_invalid", { required: true });
    }
    if (!SHA256_RE.test(request.payload_sha256)) fail("bridge_payload_hash_invalid");
    if (!Number.isInteger(request.library_id) || request.library_id <= 0) {
      fail("bridge_library_id_invalid");
    }
    if (
      !Number.isInteger(request.chunk_index)
      || !Number.isInteger(request.chunk_count)
      || request.chunk_index < 1
      || request.chunk_index > request.chunk_count
    ) {
      fail("bridge_chunk_index_invalid");
    }
    if (!Array.isArray(request.items) || !request.items.length || request.items.length > MAX_ITEMS_PER_JOB) {
      fail("bridge_item_count_invalid");
    }
    const taskIds = new Set();
    for (const item of request.items) {
      if (!hasExactFields(item, ITEM_FIELDS)) fail("bridge_item_fields_invalid");
      for (const field of ITEM_FIELDS) validateText(item[field], "bridge_item_value_invalid");
      if (!item.task_id) fail("bridge_task_id_missing");
      if (taskIds.has(item.task_id)) fail("bridge_task_id_duplicate");
      taskIds.add(item.task_id);
    }
    const createdAt = parseUTCInstant(request.created_at, "bridge_request_time_invalid");
    const expiresAt = parseUTCInstant(request.expires_at, "bridge_request_time_invalid");
    if (expiresAt <= createdAt) fail("bridge_request_time_invalid");
    if (!(now instanceof Date) || Number.isNaN(now.getTime())) fail("bridge_request_time_invalid");
    if (expiresAt <= BigInt(now.getTime()) * 1000n) fail("job_expired");
    if (await payloadHash(request) !== request.payload_sha256) {
      fail("bridge_payload_hash_invalid");
    }
    return request;
  }

  function chooseCandidate(wanted, candidates) {
    if (!isPlainObject(wanted) || !Array.isArray(candidates)) fail("metadata_uncertain");
    const title = normalizeTitle(wanted.title);
    const year = String(wanted.year || "").trim();
    const creator = firstCreatorKey(wanted.authors);
    if (!title || (!year && !creator)) return null;
    const matches = candidates.filter(candidate => (
      isPlainObject(candidate)
      && normalizeTitle(candidate.title) === title
      && (
        (year && String(candidate.year || "").trim() === year)
        || (creator && firstCreatorKey(candidate.firstCreator) === creator)
      )
    ));
    if (matches.length > 1) fail("metadata_uncertain");
    return matches[0] || null;
  }

  function successRow(taskID, zoteroItemID, attachmentPath, status) {
    if (!SUCCESS_STATUSES.has(status)) fail("bridge_result_status_invalid");
    return {
      task_id: String(taskID),
      zotero_item_id: String(zoteroItemID),
      attachment_path: String(attachmentPath),
      status,
      reason: "",
    };
  }

  function failureRow(taskID, status, reason) {
    if (!FAILURE_STATUSES.has(status)) fail("bridge_result_status_invalid");
    return {
      task_id: String(taskID),
      zotero_item_id: "",
      attachment_path: "",
      status,
      reason: String(reason || ""),
    };
  }

  return {
    canonicalPayload,
    chooseCandidate,
    failureRow,
    firstCreatorKey,
    normalizeDOI,
    normalizeTitle,
    payloadHash,
    successRow,
    validateRequest,
  };
});
