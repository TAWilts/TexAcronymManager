import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import test from "node:test";
import {
  DatabaseConflictError,
  EditorProfile,
  editorEntriesFromDatabase,
  editorProfileFromRaw,
  mutateEditorDatabase,
  readEditorDatabase,
  validateEditorEntry,
} from "../src/editorModel";

const profile: EditorProfile = {
  id: "acronym-package",
  name: "Acronyms",
  commands: [{
    id: "acronym",
    label: "Acronym",
    description: "",
    fields: [
      { id: "short", label: "Short form", required: true, multiline: false, comparisonGroup: "key" },
      { id: "long", label: "Long form", required: true, multiline: false },
      { id: "note", label: "Note", required: false, multiline: true },
    ],
  }],
};

test("normalizes profile-defined fields for the shared editor", () => {
  assert.deepEqual(editorProfileFromRaw({
    id: "custom",
    name: "Custom profile",
    commands: [{
      id: "term",
      label: "Term",
      fields: [{ id: "key", label: "Key", required: true, comparison_group: "term-key" }],
    }],
  }), {
    id: "custom",
    name: "Custom profile",
    commands: [{
      id: "term",
      label: "Term",
      description: "",
      fields: [{ id: "key", label: "Key", required: true, multiline: false, comparisonGroup: "term-key" }],
    }],
  });
});

test("loads legacy acronym records into the generic editor model", () => {
  const entries = editorEntriesFromDatabase({ acronyms: [{ short: "AUV", long: "autonomous underwater vehicle" }] });
  assert.equal(entries.length, 1);
  assert.match(entries[0].uid, /\S/);
  assert.equal(entries[0].commandId, "acronym");
  assert.equal(entries[0].values.short, "AUV");
});

test("validates required fields and same-command comparison groups", () => {
  const entries = [{ uid: "one", commandId: "acronym", values: { short: "AUV", long: "vehicle" } }];
  assert.deepEqual(validateEditorEntry(
    { uid: "two", commandId: "acronym", values: { short: " auv ", long: "" } },
    entries,
    profile,
  ), ["Short form already exists for this command type.", "Long form is required."]);
});

test("atomically saves and deletes entries while detecting external changes", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "tacroman-editor-"));
  const databasePath = path.join(directory, "entries.json");
  try {
    await writeFile(databasePath, `${JSON.stringify({ schema_version: 2, entries: [] }, null, 2)}\n`, "utf8");
    const initial = await readEditorDatabase(databasePath);
    const saved = await mutateEditorDatabase(databasePath, initial.revision, {
      kind: "save",
      commandId: "acronym",
      values: { short: "AUV", long: "autonomous underwater vehicle", note: "" },
    }, profile);
    assert.equal(saved.entries.length, 1);
    assert.equal(saved.entries[0].values.short, "AUV");

    await assert.rejects(
      mutateEditorDatabase(databasePath, initial.revision, {
        kind: "save",
        commandId: "acronym",
        values: { short: "DVL", long: "Doppler velocity log" },
      }, profile),
      DatabaseConflictError,
    );

    const deleted = await mutateEditorDatabase(databasePath, saved.revision, {
      kind: "delete",
      uid: saved.entries[0].uid,
    }, profile);
    assert.equal(deleted.entries.length, 0);
    assert.deepEqual(JSON.parse(await readFile(databasePath, "utf8")), { schema_version: 2, entries: [] });
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
