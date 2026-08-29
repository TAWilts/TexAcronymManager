import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import test from "node:test";
import {
  databasePathFromIntegrationState,
  desktopLaunchArguments,
  desktopIntegrationStatePath,
  ensureDesktopIntegrationState,
  launcherFromIntegrationState,
  outputModeFromIntegrationState,
  outputPathFromIntegrationState,
  updateDesktopIntegrationState,
} from "../src/desktopIntegration";

test("starts the desktop application without a selected database", () => {
  assert.deepEqual(desktopLaunchArguments(["--profile", "default"], ["--debug"]), [
    "--profile",
    "default",
    "--debug",
  ]);
});

test("passes a selected database to the desktop application", () => {
  assert.deepEqual(desktopLaunchArguments([], [], "D:\\Diss\\acronyms.json", "D:\\Diss\\entries.tex"), [
    "--database",
    "D:\\Diss\\acronyms.json",
    "--output",
    "D:\\Diss\\entries.tex",
  ]);
});

test("uses one shared TAcroMan directory in the user home", () => {
  assert.equal(
    desktopIntegrationStatePath(
      "win32",
      { APPDATA: "C:\\Users\\Thomas\\AppData\\Roaming" },
      "C:\\Users\\Thomas",
    ),
    path.join("C:\\Users\\Thomas", "TAcroMan", "state.json"),
  );
});

test("reads a valid desktop database path", () => {
  assert.equal(
    databasePathFromIntegrationState({ databasePath: " D:\\Diss\\acronyms.json " }),
    "D:\\Diss\\acronyms.json",
  );
  assert.equal(databasePathFromIntegrationState({ databasePath: "" }), undefined);
  assert.equal(databasePathFromIntegrationState({ last_database_path: "D:\\Legacy\\entries.json" }), undefined);
  assert.equal(databasePathFromIntegrationState(null), undefined);
});

test("reads output path and synchronization mode", () => {
  const state = { outputPath: " D:\\Paper\\entries.tex ", outputMode: "project" };
  assert.equal(outputPathFromIntegrationState(state), "D:\\Paper\\entries.tex");
  assert.equal(outputModeFromIntegrationState(state), "project");
  assert.equal(outputModeFromIntegrationState({ outputMode: "invalid" }), undefined);
});

test("creates and updates shared state without VS Code settings", async () => {
  const temporary = await mkdtemp(path.join(os.tmpdir(), "tacroman-state-"));
  try {
    const statePath = path.join(temporary, "TAcroMan", "state.json");
    const databasePath = path.join(temporary, "TAcroMan", "entries.json");
    const projectOutput = path.join(temporary, "paper", "entries.tex");
    const state = await ensureDesktopIntegrationState(projectOutput, statePath, databasePath);
    assert.equal(state.databasePath, databasePath);
    assert.equal(state.outputPath, projectOutput);
    assert.equal(state.outputMode, "project");
    assert.deepEqual(JSON.parse(await readFile(databasePath, "utf8")), { schema_version: 2, entries: [] });

    const nextProjectOutput = path.join(temporary, "second-paper", "entries.tex");
    const moved = await ensureDesktopIntegrationState(nextProjectOutput, statePath, databasePath);
    assert.equal(moved.outputPath, nextProjectOutput);

    await updateDesktopIntegrationState({ outputPath: "custom.tex", outputMode: "custom" }, statePath);
    const updated = JSON.parse(await readFile(statePath, "utf8")) as Record<string, unknown>;
    assert.equal(updated.databasePath, databasePath);
    assert.equal(updated.outputPath, "custom.tex");
    assert.equal(updated.last_database_path, undefined);
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
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
