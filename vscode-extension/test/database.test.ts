import assert from "node:assert/strict";
import test from "node:test";
import { candidatesFromDatabase, matchesQuery, recordsFromDatabase } from "../src/database";

const v2 = {
  schema_version: 2,
  entries: [
    {
      uid: "1",
      command_id: "acronym",
      values: {
        short: "AUV",
        long: "autonomous underwater vehicle",
        category: "Robotics",
        note: "Vehicle",
      },
    },
    {
      uid: "2",
      command_id: "acroplural",
      values: {
        key: "AUV",
        short_plural: "AUVs",
        long_plural: "autonomous underwater vehicles",
      },
    },
    {
      uid: "3",
      command_id: "acronym",
      values: {
        short: "DVL",
        long: "Doppler velocity log",
      },
    },
  ],
};

test("reads current TAcroMan v2 entries", () => {
  assert.equal(recordsFromDatabase(v2).length, 3);
  const candidates = candidatesFromDatabase(v2);
  assert.deepEqual(candidates.map((item) => item.key), ["AUV", "DVL"]);
  assert.equal(candidates[0].long, "autonomous underwater vehicle");
  assert.equal(candidates[0].values.short_plural, "AUVs");
});

test("searches across short form, long form and other fields", () => {
  const auv = candidatesFromDatabase(v2)[0];
  assert.equal(matchesQuery(auv, "AUV"), true);
  assert.equal(matchesQuery(auv, "autonomous under"), true);
  assert.equal(matchesQuery(auv, "robotics vehicle"), true);
  assert.equal(matchesQuery(auv, "sonar"), false);
});

test("prefers singular display data even when plural record comes first", () => {
  const candidates = candidatesFromDatabase({
    entries: [
      { command_id: "acroplural", values: { key: "AUV", short_plural: "AUVs", long_plural: "autonomous underwater vehicles" } },
      { command_id: "acronym", values: { short: "AUV", long: "autonomous underwater vehicle" } },
    ],
  });
  assert.equal(candidates[0].short, "AUV");
  assert.equal(candidates[0].long, "autonomous underwater vehicle");
});

test("accepts legacy raw acronym arrays", () => {
  const candidates = candidatesFromDatabase([
    { short: "USBL", long: "ultra-short baseline", category: "Navigation" },
  ]);
  assert.equal(candidates[0].key, "USBL");
  assert.equal(candidates[0].long, "ultra-short baseline");
});

test("accepts legacy object with acronyms array", () => {
  const candidates = candidatesFromDatabase({
    acronyms: [{ short: "FLS", long: "forward-looking sonar" }],
  });
  assert.equal(candidates[0].key, "FLS");
});
