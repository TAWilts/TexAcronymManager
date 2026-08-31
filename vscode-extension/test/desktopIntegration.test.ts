import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import test from "node:test";
import {
  databasePathFromIntegrationState,
  installationIdFromIntegrationState,
  desktopLaunchArguments,
  desktopIntegrationStatePath,
  ensureDesktopIntegrationState,
  launcherFromIntegrationState,
  outputModeFromIntegrationState,
  outputPathFromIntegrationState,
  workspacePathFromIntegrationState,
  updateDesktopIntegrationState,
} from "../src/desktopIntegration";

test("starts the desktop application without a selected workspace", () => {
  assert.deepEqual(desktopLaunchArguments(["--profile", "default"], ["--debug"]), [
    "--profile",
    "default",
    "--debug",
  ]);
});

test("passes a selected workspace to the desktop application", () => {
  assert.deepEqual(desktopLaunchArguments([], [], "D:\\Diss\\TAcroMan", "D:\\Diss\\entries.tex"), [
    "--workspace",
    "D:\\Diss\\TAcroMan",
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

test("reads workspace and installation identity", () => {
  const id = "f3181be7-a1a4-4d4c-8e4d-f24249546e45";
  assert.equal(workspacePathFromIntegrationState({ workspacePath: " D:\\Shared " }), "D:\\Shared");
  assert.equal(installationIdFromIntegrationState({ installationId: id }), id);
  assert.equal(installationIdFromIntegrationState({ installationId: "invalid" }), undefined);
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
    const workspacePath = path.join(temporary, "TAcroMan", "workspace");
    await mkdir(path.dirname(statePath), { recursive: true });
    const projectOutput = path.join(temporary, "paper", "entries.tex");
    const state = await ensureDesktopIntegrationState(projectOutput, statePath, workspacePath);
    assert.equal(state.workspacePath, workspacePath);
    assert.equal(typeof state.installationId, "string");
    assert.equal(typeof state.fragmentPath, "string");
    assert.equal(state.outputPath, projectOutput);
    assert.equal(state.outputMode, "project");
    assert.equal(JSON.parse(await readFile(path.join(workspacePath, ".tacroman-workspace.json"), "utf8")).format, "tacroman-workspace");

    const nextProjectOutput = path.join(temporary, "second-paper", "entries.tex");
    const moved = await ensureDesktopIntegrationState(nextProjectOutput, statePath, workspacePath);
    assert.equal(moved.outputPath, nextProjectOutput);

    await updateDesktopIntegrationState({ outputPath: "custom.tex", outputMode: "custom" }, statePath);
    const updated = JSON.parse(await readFile(statePath, "utf8")) as Record<string, unknown>;
    assert.equal(updated.workspacePath, workspacePath);
    assert.equal(updated.databasePath, undefined);
    assert.equal(updated.outputPath, "custom.tex");
    assert.equal(updated.last_database_path, undefined);
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
});

test("database output mode always targets entries.tex inside the workspace", async () => {
  const temporary = await mkdtemp(path.join(os.tmpdir(), "tacroman-database-output-"));
  try {
    const statePath = path.join(temporary, "TAcroMan", "state.json");
    const workspacePath = path.join(temporary, "TAcroMan", "workspace");
    await mkdir(path.dirname(statePath), { recursive: true });
    await writeFile(statePath, JSON.stringify({
      outputMode: "database",
      outputPath: path.join(temporary, "legacy", "entries.tex"),
    }), "utf8");
    const state = await ensureDesktopIntegrationState(undefined, statePath, workspacePath);
    assert.equal(state.outputPath, path.join(workspacePath, "entries.tex"));
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
