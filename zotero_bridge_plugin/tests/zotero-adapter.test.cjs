const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const core = require("../content/bridge-core.js");

function loadProductionRuntime({ items = [], existingPaths = [] } = {}) {
  const calls = {
    identifiers: [],
    translators: [],
    translateOptions: [],
    collectionSaves: 0,
    collectionLookups: [],
    events: [],
  };
  const existingCollection = {
    id: 77,
    libraryID: 1,
    name: "Codex下载回退_adapter",
    deleted: false,
  };
  const translatedItem = {
    id: 901,
    libraryID: 1,
    isFeedItem: false,
    deleted: false,
    isRegularItem: () => true,
    getField(field) {
      return {
        DOI: "10.1000/adapter",
        title: "Adapter Contract",
        firstCreator: "Smith",
        year: "2026",
      }[field] || "";
    },
    getAttachments: () => [],
    getCollections: () => [77],
    addToCollection() {},
    async saveTx() {},
  };

  class Search {
    addCondition(field, operator, value) { this.condition = { field, operator, value }; }
    async search() {
      const { field, operator, value } = this.condition;
      // Zotero 9.0.6: `is` generates `=`, `contains` generates `LIKE`.
      return items.filter(item => item.libraryID === this.libraryID && (
        operator === "is" ? item.getField(field) === value
          : item.getField(field).toLowerCase().includes(value.toLowerCase())
      )).map(item => item.id);
    }
  }

  class Collection {
    async saveTx() {
      calls.collectionSaves += 1;
      this.id = 78;
    }
  }

  class TranslateSearch {
    setIdentifier(identifier) {
      calls.identifiers.push(identifier);
    }

    async getTranslators() {
      return ["fixture-translator"];
    }

    setTranslator(translators) {
      calls.translators.push(translators);
    }

    async translate(options) {
      calls.events.push("translate");
      calls.translateOptions.push(options);
      return [translatedItem];
    }
  }

  const context = vm.createContext({
    console,
    setInterval: () => 1,
    clearInterval: () => {},
    ZoteroPaperBridgeCore: core,
    IOUtils: {
      makeDirectory: async () => {},
      getChildren: async () => [],
      exists: async path => existingPaths.includes(path),
      readUTF8: async () => "",
      writeUTF8: async () => {},
      move: async () => {},
      remove: async () => {},
    },
    PathUtils: {
      join: (...parts) => parts.join("/"),
      filename: value => String(value).replaceAll("\\", "/").split("/").at(-1),
    },
    Services: {
      env: { get: () => "C:/LocalAppData" },
      prompt: { confirm: () => true, alert: () => {} },
    },
    Zotero: {
      version: "9.0.6-test",
      Libraries: {
        get: libraryID => ({
          libraryID,
          name: "我的文库",
          editable: true,
          filesEditable: true,
          isFeed: false,
        }),
      },
      Items: { getAsync: async ids => ids.map(id => items.find(item => item.id === id)).filter(Boolean) },
      Collections: {
        getByLibrary: libraryID => (
          libraryID === 1 ? [existingCollection] : []
        ),
        getAsync: async ids => ids.map(id => {
          calls.collectionLookups.push(id);
          return id === existingCollection.id ? existingCollection : null;
        }).filter(Boolean),
      },
      Attachments: { addAvailablePDF: async () => false },
      Translate: { Search: TranslateSearch },
      Search,
      Collection,
      logError() {},
    },
  });
  const source = fs.readFileSync(
    path.join(__dirname, "..", "content", "bridge-runtime.js"),
    "utf8",
  );
  vm.runInContext(source, context, { filename: "bridge-runtime.js" });
  return { runtime: context.Zotero.PaperDownloadBridge, calls, existingCollection };
}

test("production Zotero adapter passes the Zotero 9 translator contract exactly", async () => {
  const { runtime, calls } = loadProductionRuntime();

  const item = await runtime.importByDOI("10.1000/adapter", 1, 77);

  assert.equal(item.id, 901);
  assert.deepEqual(JSON.parse(JSON.stringify(calls.identifiers)), [{ DOI: "10.1000/adapter" }]);
  assert.deepEqual(JSON.parse(JSON.stringify(calls.translators)), [["fixture-translator"]]);
  assert.deepEqual(JSON.parse(JSON.stringify(calls.translateOptions)), [{
    libraryID: 1,
    collections: [77],
    saveAttachments: false,
  }]);
});

test("production Zotero adapter checkpoints import intent before translator write", async () => {
  const { runtime, calls } = loadProductionRuntime();
  const progress = {
    created_item_ids: [],
    created_attachment_ids: [],
    added_memberships: [],
    pending_write: null,
  };

  await runtime.importByDOI(
    "10.1000/adapter",
    1,
    77,
    progress,
    async () => calls.events.push(
      progress.pending_write === null ? "checkpoint:complete" : "checkpoint:intent",
    ),
    "paper-0001",
  );

  assert.deepEqual(calls.events, [
    "checkpoint:intent",
    "translate",
    "checkpoint:complete",
  ]);
  assert.deepEqual(progress.created_item_ids, [901]);
  assert.deepEqual(JSON.parse(JSON.stringify(progress.added_memberships)), [[901, 77]]);
  assert.equal(progress.pending_write, null);
});

test("production Zotero adapter reports whether collection creation was necessary", async () => {
  const { runtime, calls, existingCollection } = loadProductionRuntime();

  const outcome = await runtime.ensureCollection(1, existingCollection.name);

  assert.equal(outcome.collection.id, 77);
  assert.equal(outcome.created, false);
  assert.equal(calls.collectionSaves, 0);
});

test("production Zotero adapter reads a checkpointed collection by numeric id", async () => {
  const { runtime, calls } = loadProductionRuntime();

  const collection = await runtime.getCollectionByID(1, 77);

  assert.equal(collection.id, 77);
  assert.deepEqual(calls.collectionLookups, [77]);
});

function doiItem(id, doi, libraryID = 1) {
  return {
    id, libraryID, deleted: false, isFeedItem: false,
    isRegularItem: () => true,
    getField: field => ({ DOI: doi, title: 'Case-sensitive DOI regression', year: '2024' }[field] || ''),
  };
}

test('production DOI lookup finds uppercase and URL-prefixed DOIs without accepting suffix matches', async () => {
  const wanted = doiItem(501, 'https://doi.org/10.1107/S1600576714012576');
  const { runtime } = loadProductionRuntime({ items: [
    wanted, doiItem(502, '10.1107/S16005767140125760'),
    doiItem(503, '10.1107/S1600576714012576', 2),
  ] });
  assert.equal((await runtime.resolveItem({ doi: '10.1107/s1600576714012576' }, 1)).id, 501);
});

test('production DOI lookup keeps duplicate normalized matches ambiguous', async () => {
  const { runtime } = loadProductionRuntime({ items: [
    doiItem(501, '10.1107/S1600576714012576'),
    doiItem(502, 'https://doi.org/10.1107/s1600576714012576'),
  ] });
  await assert.rejects(runtime.resolveItem({ doi: '10.1107/s1600576714012576' }, 1), /metadata_uncertain/);
});

test('production attachment lookup skips a missing local PDF and reads the next local file', async () => {
  const paths = ['C:\\Zotero\\missing.pdf', 'C:\\Zotero\\present.pdf'];
  const parent = doiItem(501, '10.1000/example');
  parent.getAttachments = () => [601, 602];
  const attachments = paths.map((path, index) => ({
    id: 601 + index, libraryID: 1, parentItemID: 501,
    isAttachment: () => true, attachmentContentType: 'application/pdf',
    getFilePathAsync: async () => path,
  }));
  const { runtime } = loadProductionRuntime({ items: [parent, ...attachments], existingPaths: [paths[1]] });
  assert.equal((await runtime.findPDFAttachment(parent)).path, paths[1]);
});
