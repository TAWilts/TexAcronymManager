import assert from "node:assert/strict";
import * as path from "node:path";
import test from "node:test";
import {
  databasePathFromIntegrationState,
  desktopLaunchArguments,
  desktopIntegrationStatePath,
  launcherFromIntegrationState,
} from "../src/desktopIntegration";

test("starts the desktop application without a selected database", () => {
  assert.deepEqual(desktopLaunchArguments(["--profile", "default"], ["--debug"]), [
    "--profile",
    "default",
    "--debug",
  ]);
});

test("passes a selected database to the desktop application", () => {
  assert.deepEqual(desktopLaunchArguments([], [], "D:\\Diss\\acronyms.json"), [
    "--database",
    "D:\\Diss\\acronyms.json",
  ]);
});

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

test("reads a valid desktop launcher", () => {
  assert.deepEqual(
    launcherFromIntegrationState({
      launcher: {
        executable: " D:\\TAcroMan\\.venv\\Scripts\\tacroman.exe ",
        args: ["--example"],
      },
    }),
    {
      executable: "D:\\TAcroMan\\.venv\\Scripts\\tacroman.exe",
      args: ["--example"],
    },
  );
});

test("accepts a launcher without explicit args", () => {
  assert.deepEqual(
    launcherFromIntegrationState({ launcher: { executable: "tacroman" } }),
    { executable: "tacroman", args: [] },
  );
});

test("rejects invalid desktop launchers", () => {
  assert.equal(launcherFromIntegrationState({ launcher: null }), undefined);
  assert.equal(launcherFromIntegrationState({ launcher: { executable: "" } }), undefined);
  assert.equal(
    launcherFromIntegrationState({ launcher: { executable: "tacroman", args: [42] } }),
    undefined,
  );
});
