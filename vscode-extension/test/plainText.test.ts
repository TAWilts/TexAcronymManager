import assert from "node:assert/strict";
import test from "node:test";
import { candidatesFromDatabase } from "../src/database";
import {
  buildPlainAcronymCompletionForms,
  buildPlainAcronymForms,
  findPlainAcronymOccurrences,
  findPlainTextCompletionMatches,
  latexCommentStart,
  replacementForOccurrence,
} from "../src/plainText";

const candidates = candidatesFromDatabase({
  entries: [
    { command_id: "acronym", values: { short: "AUV", long: "autonomous underwater vehicle" } },
    { command_id: "acroplural", values: { key: "AUV", short_plural: "AUVs", long_plural: "autonomous underwater vehicles" } },
    { command_id: "acronym", values: { short: "DVL", long: "Doppler velocity log" } },
    { command_id: "acronym", values: { short: "CNN", long: "convolutional neural network" } },
  ],
});

const forms = buildPlainAcronymForms(candidates, { inferPlurals: true });
const completionForms = buildPlainAcronymCompletionForms(candidates, { inferPlurals: true });
const ignored = ["ac", "acp", "cite", "ref", "label"];

function scan(line: string) {
  return findPlainAcronymOccurrences(line, forms, { ignoredArgumentCommands: ignored });
}

test("finds singular plain-text acronyms", () => {
  assert.deepEqual(scan("The AUV uses a DVL.").map((item) => [item.text, item.key, item.plural]), [
    ["AUV", "AUV", false],
    ["DVL", "DVL", false],
  ]);
});

test("prefers an explicit plural over the singular prefix", () => {
  assert.deepEqual(scan("Two AUVs cooperate.").map((item) => [item.text, item.key, item.plural]), [
    ["AUVs", "AUV", true],
  ]);
});

test("infers a simple plural when no explicit plural record exists", () => {
  assert.deepEqual(scan("The CNNs are compared.").map((item) => [item.text, item.key, item.plural]), [
    ["CNNs", "CNN", true],
  ]);
});

test("ignores configured LaTeX acronym commands", () => {
  assert.deepEqual(scan("The \\ac{AUV} uses \\ac{DVL}."), []);
  assert.deepEqual(scan("Two \\acp{AUV} cooperate."), []);
});

test("ignores comments and escaped percent signs correctly", () => {
  assert.equal(latexCommentStart("AUV % DVL"), 4);
  assert.equal(latexCommentStart("90\\% AUV"), "90\\% AUV".length);
  assert.deepEqual(scan("Text % AUV DVL"), []);
  assert.equal(scan("90\\% AUV")[0].text, "AUV");
});

test("ignores common non-prose command arguments", () => {
  assert.deepEqual(scan("See \\label{AUV} and \\ref{DVL}."), []);
});

test("ignores acronym definition lines", () => {
  assert.deepEqual(scan("\\acro{AUV}{autonomous underwater vehicle}"), []);
  assert.deepEqual(scan("\\acroplural{AUV}[AUVs]{autonomous underwater vehicles}"), []);
});

test("does not match acronyms inside longer words", () => {
  assert.deepEqual(scan("AUVish pseudoDVLvalue"), []);
});

test("builds singular and plural Quick Fix replacements", () => {
  const singular = scan("AUV")[0];
  const plural = scan("AUVs")[0];
  assert.equal(replacementForOccurrence(singular, "ac", "acp"), "\\ac{AUV}");
  assert.equal(replacementForOccurrence(plural, "ac", "acp"), "\\acp{AUV}");
});


test("plain-text completion matches partial short forms", () => {
  const found = findPlainTextCompletionMatches("This is an AU", completionForms, {
    ignoredArgumentCommands: ignored,
  });
  assert.equal(found[0]?.key, "AUV");
  assert.equal(found[0]?.typedText, "AU");
  assert.equal(found[0]?.plural, false);
  assert.equal(found[0]?.startCharacter, "This is an ".length);
});

test("plain-text completion matches partial long forms", () => {
  const found = findPlainTextCompletionMatches("This is an autonomous under", completionForms, {
    ignoredArgumentCommands: ignored,
  });
  assert.equal(found[0]?.key, "AUV");
  assert.equal(found[0]?.typedText, "autonomous under");
  assert.equal(found[0]?.source, "long");
});

test("plain-text completion prefers plural forms once the plural is typed", () => {
  const found = findPlainTextCompletionMatches("Two AUVs", completionForms, {
    ignoredArgumentCommands: ignored,
  });
  assert.equal(found[0]?.key, "AUV");
  assert.equal(found[0]?.typedText, "AUVs");
  assert.equal(found[0]?.plural, true);
});

test("plain-text completion ignores acronym commands, citations, comments, and longer words", () => {
  assert.deepEqual(findPlainTextCompletionMatches("\\ac{AU", completionForms, { ignoredArgumentCommands: ignored }), []);
  assert.deepEqual(findPlainTextCompletionMatches("See \\cite{AU", completionForms, { ignoredArgumentCommands: ignored }), []);
  assert.deepEqual(findPlainTextCompletionMatches("Text % AU", completionForms, { ignoredArgumentCommands: ignored }), []);
  assert.deepEqual(findPlainTextCompletionMatches("pseudoAU", completionForms, { ignoredArgumentCommands: ignored }), []);
});

test("plain-text completion requires at least two typed characters", () => {
  assert.deepEqual(findPlainTextCompletionMatches("A", completionForms, { ignoredArgumentCommands: ignored }), []);
});
