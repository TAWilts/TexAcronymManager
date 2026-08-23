import assert from "node:assert/strict";
import test from "node:test";
import { findDocumentAcronymOccurrences } from "../src/acronymCheck";
import { candidatesFromDatabase } from "../src/database";
import { buildPlainAcronymCompletionForms, findPlainTextCompletionMatches } from "../src/plainText";
import { sidebarAcronymForms } from "../src/sidebarForms";

const database = {
  entries: [
    { command_id: "acronym", values: { short: "AUC", long: "Area under Curve" } },
    { command_id: "acroplural", values: { key: "AUC", long_plural: "Areas under Curve" } },
  ],
};

test("plural fields do not become singular display data", () => {
  const candidate = candidatesFromDatabase({
    entries: [{ command_id: "acroplural", values: { key: "AUC", long_plural: "Areas under Curve" } }],
  })[0];
  assert.equal(candidate.short, "AUC");
  assert.equal(candidate.long, "");
  assert.equal(candidate.values.long_plural, "Areas under Curve");
});

test("sidebar lists singular and explicit plural forms", () => {
  const candidate = candidatesFromDatabase(database)[0];
  assert.deepEqual(sidebarAcronymForms(candidate), [
    { plural: false, label: "AUC", long: "Area under Curve" },
    { plural: true, label: "AUC", long: "Areas under Curve" },
  ]);
});

test("plain prose completion recognizes explicit long plural", () => {
  const candidates = candidatesFromDatabase(database);
  const forms = buildPlainAcronymCompletionForms(candidates, { inferPlurals: true });
  const matches = findPlainTextCompletionMatches("The Areas under", forms, { minCharacters: 2 });
  assert.equal(matches.length, 1);
  assert.equal(matches[0].key, "AUC");
  assert.equal(matches[0].plural, true);
  assert.equal(matches[0].source, "long");
});

test("Check Current File recognizes explicit long plural", () => {
  const found = findDocumentAcronymOccurrences(
    "Areas under Curve are compared.",
    candidatesFromDatabase(database),
    { inferPlurals: true },
  );
  assert.deepEqual(found.map((x) => [x.text, x.key, x.plural, x.source]), [
    ["Areas under Curve", "AUC", true, "long"],
  ]);
});
