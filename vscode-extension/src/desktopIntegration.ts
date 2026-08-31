import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { createWorkspace, DEFAULT_WORKSPACE_PROFILE, joinWorkspace, MANIFEST_FILENAME } from "./workspace";

export type OutputMode = "project" | "database" | "custom";

export interface DesktopLauncher {
  executable: string;
  args: string[];
}

export interface DesktopIntegrationState {
  version?: unknown;
  workspacePath?: unknown;
  fragmentPath?: unknown;
  installationId?: unknown;
  databasePath?: unknown;
  legacyDatabasePath?: unknown;
  outputPath?: unknown;
  outputMode?: unknown;
  profilesPath?: unknown;
  selectedProfileId?: unknown;
  language?: unknown;
  renderProfile?: unknown;
  launcher?: unknown;
  [key: string]: unknown;
}

export function desktopLaunchArguments(
  launcherArguments: readonly string[],
  extraArguments: readonly string[],
  workspacePath?: string,
  outputPath?: string,
): string[] {
  const databaseArguments = workspacePath ? ["--workspace", workspacePath] : [];
  const outputArguments = outputPath ? ["--output", outputPath] : [];
  return [...launcherArguments, ...extraArguments, ...databaseArguments, ...outputArguments];
}

export function tacromanUserDirectory(home: string = os.homedir()): string {
  return path.join(home, "TAcroMan");
}

export function desktopIntegrationStatePath(
  _platform: NodeJS.Platform = process.platform,
  _env: NodeJS.ProcessEnv = process.env,
  home: string = os.homedir(),
): string {
  return path.join(tacromanUserDirectory(home), "state.json");
}

export function defaultWorkspacePath(home: string = os.homedir()): string {
  return path.join(tacromanUserDirectory(home), "workspace");
}

function objectState(raw: unknown): DesktopIntegrationState | undefined {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return undefined;
  }
  return raw as DesktopIntegrationState;
}

function nonEmptyString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

export function workspacePathFromIntegrationState(raw: unknown): string | undefined {
  return nonEmptyString(objectState(raw)?.workspacePath);
}

export function fragmentPathFromIntegrationState(raw: unknown): string | undefined {
  return nonEmptyString(objectState(raw)?.fragmentPath);
}

export function installationIdFromIntegrationState(raw: unknown): string | undefined {
  const value = nonEmptyString(objectState(raw)?.installationId);
  return value && /^[0-9a-f-]{36}$/i.test(value) ? value : undefined;
}

export function databasePathFromIntegrationState(raw: unknown): string | undefined {
  return nonEmptyString(objectState(raw)?.databasePath);
}

export function outputPathFromIntegrationState(raw: unknown): string | undefined {
  return nonEmptyString(objectState(raw)?.outputPath);
}

export function outputModeFromIntegrationState(raw: unknown): OutputMode | undefined {
  const mode = objectState(raw)?.outputMode;
  return mode === "project" || mode === "database" || mode === "custom" ? mode : undefined;
}

export function launcherFromIntegrationState(raw: unknown): DesktopLauncher | undefined {
  const launcher = objectState(raw)?.launcher;
  if (!launcher || typeof launcher !== "object" || Array.isArray(launcher)) {
    return undefined;
  }

  const candidate = launcher as { executable?: unknown; args?: unknown };
  if (typeof candidate.executable !== "string" || !candidate.executable.trim()) {
    return undefined;
  }

  const args = candidate.args === undefined ? [] : candidate.args;
  if (!Array.isArray(args) || !args.every((value) => typeof value === "string")) {
    return undefined;
  }

  return { executable: candidate.executable.trim(), args: [...args] };
}

async function readJsonFile(filePath: string): Promise<DesktopIntegrationState | undefined> {
  try {
    return objectState(JSON.parse(await readFile(filePath, "utf8")) as unknown);
  } catch {
    return undefined;
  }
}

export async function readDesktopIntegrationState(
  statePath: string = desktopIntegrationStatePath(),
): Promise<DesktopIntegrationState | undefined> {
  return readJsonFile(statePath);
}

async function atomicWriteJson(filePath: string, value: unknown): Promise<void> {
  await mkdir(path.dirname(filePath), { recursive: true });
  const temporary = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  await rename(temporary, filePath);
}

export async function updateDesktopIntegrationState(
  changes: Partial<DesktopIntegrationState>,
  statePath: string = desktopIntegrationStatePath(),
): Promise<DesktopIntegrationState> {
  const current = await readDesktopIntegrationState(statePath) ?? {};
  const next: DesktopIntegrationState = { ...current, ...changes, version: 2 };
  delete next.last_database_path;
  if (nonEmptyString(next.workspacePath)) {
    delete next.databasePath;
    delete next.profilesPath;
    delete next.selectedProfileId;
    delete next.renderProfile;
  }
  await atomicWriteJson(statePath, next);
  return next;
}

export async function ensureDesktopIntegrationState(
  projectOutputPath?: string,
  statePath: string = desktopIntegrationStatePath(),
  initialWorkspacePath: string = defaultWorkspacePath(),
): Promise<DesktopIntegrationState> {
  await mkdir(path.dirname(statePath), { recursive: true });
  const state = await readDesktopIntegrationState(statePath) ?? {};
  const legacyDatabasePath = nonEmptyString(state.legacyDatabasePath) ?? databasePathFromIntegrationState(state);

  const installationId = installationIdFromIntegrationState(state) ?? randomUUID();
  const workspacePath = workspacePathFromIntegrationState(state) ?? initialWorkspacePath;
  let workspace;
  try {
    workspace = await joinWorkspace(workspacePath, installationId);
  } catch (error) {
    const manifestPath = path.join(workspacePath, MANIFEST_FILENAME);
    try {
      await readFile(manifestPath);
      throw error;
    } catch (manifestError) {
      if (manifestError === error) throw error;
      workspace = await createWorkspace(workspacePath, installationId, DEFAULT_WORKSPACE_PROFILE);
    }
  }

  const existingOutput = outputPathFromIntegrationState(state);
  const outputMode = outputModeFromIntegrationState(state)
    ?? (projectOutputPath ? "project" : "database");
  const outputPath = outputMode === "project" && projectOutputPath
    ? projectOutputPath
    : outputMode === "database"
      ? path.join(workspacePath, "entries.tex")
      : existingOutput ?? projectOutputPath ?? path.join(workspacePath, "entries.tex");

  const next = {
    ...state,
    workspacePath,
    fragmentPath: workspace.localFragmentPath,
    installationId,
    outputPath,
    outputMode,
    ...(legacyDatabasePath ? { legacyDatabasePath } : {}),
  };
  delete next.databasePath;
  return updateDesktopIntegrationState(next, statePath);
}

export async function readDesktopWorkspacePath(): Promise<string | undefined> {
  return workspacePathFromIntegrationState(await readDesktopIntegrationState());
}

export async function readDesktopOutputPath(): Promise<string | undefined> {
  return outputPathFromIntegrationState(await readDesktopIntegrationState());
}

export async function readDesktopLauncher(): Promise<DesktopLauncher | undefined> {
  return launcherFromIntegrationState(await readDesktopIntegrationState());
}
