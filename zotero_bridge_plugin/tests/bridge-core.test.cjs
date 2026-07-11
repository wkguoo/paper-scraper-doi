const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../content/bridge-core.js");

async function request() {
  const value = {
    schema_version: 1,
    job_id: "11111111-1111-4111-8111-111111111111",
    payload_sha256: "",
    created_at: "2026-07-11T09:00:00Z",
    expires_at: "2026-07-12T09:00:00Z",
    run_id: "paper_batch_20260711_090000",
    library_id: 1,
    collection_name: "Codex下载回退_20260711_090000",
    chunk_index: 1,
    chunk_count: 1,
    items: [{
      task_id: "paper-0001",
      doi: "https://doi.org/10.1000/ABC",
      title: "A—B",
      authors: "Smith, J.",
      year: "2025",
    }],
  };
  value.payload_sha256 = await core.payloadHash(value);
  return value;
}

test("normalizes DOI and Unicode title deterministically", () => {
  assert.equal(core.normalizeDOI(" DOI: https://doi.org/10.1000/ABC "), "10.1000/abc");
  assert.equal(core.normalizeTitle("Ａ—B: Test"), "abtest");
});

test("payload hash matches the Python canonical JSON contract", async () => {
  assert.equal(
    await core.payloadHash(await request()),
    "a937810801620e767e03abb42e5af6699a2e7a3102a0252aed610144c0864219",
  );
});

test("rejects unknown fields, duplicates, invalid ids, expired jobs, and bad hashes", async () => {
  const now = new Date("2026-07-11T10:00:00Z");
  const unknown = await request();
  unknown.extra = true;
  await assert.rejects(
    core.validateRequest(unknown, now),
    /bridge_request_fields_invalid/,
  );

  const duplicate = await request();
  duplicate.items.push({ ...duplicate.items[0] });
  duplicate.payload_sha256 = await core.payloadHash(duplicate);
  await assert.rejects(
    core.validateRequest(duplicate, now),
    /bridge_task_id_duplicate/,
  );

  const invalidId = await request();
  invalidId.job_id = "../bad";
  invalidId.payload_sha256 = await core.payloadHash(invalidId);
  await assert.rejects(
    core.validateRequest(invalidId, now),
    /bridge_job_id_invalid/,
  );

  await assert.rejects(
    core.validateRequest(await request(), new Date("2026-07-13T10:00:00Z")),
    /job_expired/,
  );

  const tampered = await request();
  tampered.items[0].title = "Changed";
  await assert.rejects(
    core.validateRequest(tampered, now),
    /bridge_payload_hash_invalid/,
  );
});

test("title match requires year or first author and rejects ambiguity", () => {
  const wanted = { title: "Example Paper", authors: "Smith, J.", year: "2025" };
  assert.equal(
    core.chooseCandidate(wanted, [{
      id: 1,
      title: "Example Paper",
      firstCreator: "Smith",
      year: "2025",
    }]).id,
    1,
  );
  assert.equal(
    core.chooseCandidate(wanted, [{
      id: 2,
      title: "Example Paper",
      firstCreator: "Jones",
      year: "2024",
    }]),
    null,
  );
  assert.throws(() => core.chooseCandidate(wanted, [
    { id: 1, title: "Example Paper", firstCreator: "Smith", year: "2025" },
    { id: 2, title: "Example Paper", firstCreator: "Smith", year: "2025" },
  ]), /metadata_uncertain/);
});

test("result helpers emit exactly five strings", () => {
  assert.deepEqual(Object.keys(core.successRow("paper-0001", 304, "C:\\a.pdf", "existing_pdf")), [
    "task_id",
    "zotero_item_id",
    "attachment_path",
    "status",
    "reason",
  ]);
  assert.deepEqual(core.failureRow("paper-0001", "no_pdf", "no_available_pdf"), {
    task_id: "paper-0001",
    zotero_item_id: "",
    attachment_path: "",
    status: "no_pdf",
    reason: "no_available_pdf",
  });
});
