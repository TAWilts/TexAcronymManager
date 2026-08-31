import assert from "node:assert/strict";
import test from "node:test";
import {
  EditorProfile,
  editorProfileFromRaw,
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

test("validates required fields and same-command comparison groups", () => {
  const entries = [{ uid: "one", commandId: "acronym", values: { short: "AUV", long: "vehicle" } }];
  assert.deepEqual(validateEditorEntry(
    { uid: "two", commandId: "acronym", values: { short: " auv ", long: "" } },
    entries,
    profile,
  ), ["Short form already exists for this command type.", "Long form is required."]);
});
