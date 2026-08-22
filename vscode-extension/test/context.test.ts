import assert from "node:assert/strict";
import test from "node:test";
import { findCompletionContext } from "../src/context";

const commands = ["ac", "acp", "acs", "Ac"];

test("finds completion after opening brace", () => {
  assert.deepEqual(findCompletionContext("Text \\ac{", commands), {
    command: "ac",
    query: "",
    startCharacter: 9,
  });
});

test("keeps the typed text as search query", () => {
  const context = findCompletionContext("Text \\ac{autonomous under", commands);
  assert.equal(context?.command, "ac");
  assert.equal(context?.query, "autonomous under");
});

test("supports plural and capitalized commands", () => {
  assert.equal(findCompletionContext("\\acp{AUV", commands)?.command, "acp");
  assert.equal(findCompletionContext("\\Ac{DVL", commands)?.command, "Ac");
});

test("does not trigger outside configured acronym commands", () => {
  assert.equal(findCompletionContext("\\cite{smith", commands), null);
  assert.equal(findCompletionContext("normal text", commands), null);
});
