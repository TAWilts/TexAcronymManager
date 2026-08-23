import assert from "node:assert/strict";
import test from "node:test";
import { candidatesFromDatabase } from "../src/database";
import { findDocumentAcronymOccurrences } from "../src/acronymCheck";

const candidates = candidatesFromDatabase({
  entries: [
    { command_id: "acronym", values: { short: "AUV", long: "autonomous underwater vehicle" } },
    { command_id: "acroplural", values: { key: "AUV", short_plural: "AUVs", long_plural: "autonomous underwater vehicles" } },
    { command_id: "acronym", values: { short: "DVL", long: "Doppler velocity log" } },
    { command_id: "acronym", values: { short: "CNN", long: "convolutional neural network" } },
  ],
});

const options = {
  inferPlurals: true,
  ignoredArgumentCommands: ["ac", "acp", "cite", "ref", "label"],
};

test("finds short and long acronym forms in a document", () => {
  const found = findDocumentAcronymOccurrences(
    "An autonomous underwater vehicle uses a DVL. Another AUV follows.",
    candidates,
    options,
  );
  assert.deepEqual(found.map((item) => [item.text, item.key, item.source, item.plural]), [
    ["autonomous underwater vehicle", "AUV", "long", false],
    ["DVL", "DVL", "short", false],
    ["AUV", "AUV", "short", false],
  ]);
});

test("matches long forms case-insensitively and explicit plurals", () => {
  const found = findDocumentAcronymOccurrences(
    "Autonomous underwater vehicles and AUVs cooperate.",
    candidates,
    options,
  );
  assert.deepEqual(found.map((item) => [item.text, item.key, item.source, item.plural]), [
    ["Autonomous underwater vehicles", "AUV", "long", true],
    ["AUVs", "AUV", "short", true],
  ]);
});

test("infers plural forms when explicit plural metadata is absent", () => {
  const found = findDocumentAcronymOccurrences("CNNs are used.", candidates, options);
  assert.deepEqual(found.map((item) => [item.text, item.key, item.plural]), [
    ["CNNs", "CNN", true],
  ]);
});

test("ignores existing acronym commands, citations, definitions, comments and code blocks", () => {
  const source = [
    "Already \\ac{AUV} and \\acp{AUV}.",
    "See \\cite{AUV} and \\ref{DVL}.",
    "\\acro{CNN}{convolutional neural network}",
    "% AUV autonomous underwater vehicle DVL",
    "\\begin{verbatim}",
    "AUV autonomous underwater vehicle",
    "\\end{verbatim}",
  ].join("\n");
  assert.deepEqual(findDocumentAcronymOccurrences(source, candidates, options), []);
});

test("does not match acronym short forms inside longer words", () => {
  const found = findDocumentAcronymOccurrences("pseudoAUVvalue preDVLpost", candidates, options);
  assert.deepEqual(found, []);
});
