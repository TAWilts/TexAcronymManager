import assert from "node:assert/strict";
import * as path from "node:path";
import test from "node:test";
import {
  databasePathFromIntegrationState,
  desktopIntegrationStatePath,
} from "../src/desktopIntegration";

test("uses APPDATA for the Windows desktop integration state", () => {
  assert.equal(
    desktopIntegrationStatePath(
      "win32",
      { APPDATA: "C:\\Users\\Thomas\\AppData\\Roaming" },
      "C:\\Users\\Thomas",
    ),
    path.join("C:\\Users\\Thomas\\AppData\\Roaming", "TAcroMan", "vscode-integration.json"),
  );
});

test("reads a valid desktop database path", () => {
  assert.equal(
    databasePathFromIntegrationState({ databasePath: " D:\\Diss\\acronyms.json " }),
    "D:\\Diss\\acronyms.json",
  );
  assert.equal(databasePathFromIntegrationState({ databasePath: "" }), undefined);
  assert.equal(databasePathFromIntegrationState(null), undefined);
});
