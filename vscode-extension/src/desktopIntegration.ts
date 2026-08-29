import { mkdir, readFile, rename, stat, writeFile } from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";

export type OutputMode = "project" | "database" | "custom";

export interface DesktopLauncher {
  executable: string;
  args: string[];
}

export interface DesktopIntegrationState {
  version?: unknown;
  databasePath?: unknown;
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
  databasePath?: string,
  outputPath?: string,
): string[] {
  const databaseArguments = databasePath ? ["--database", databasePath] : [];
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

export function defaultDatabasePath(home: string = os.homedir()): string {
  return path.join(tacromanUserDirectory(home), "entries.json");
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
  const next: DesktopIntegrationState = { ...current, ...changes, version: 1 };
  delete next.last_database_path;
  await atomicWriteJson(statePath, next);
  return next;
}

export async function ensureDesktopIntegrationState(
  projectOutputPath?: string,
  statePath: string = desktopIntegrationStatePath(),
  initialDatabasePath: string = defaultDatabasePath(),
): Promise<DesktopIntegrationState> {
  await mkdir(path.dirname(statePath), { recursive: true });
  const state = await readDesktopIntegrationState(statePath) ?? {};

  const databasePath = databasePathFromIntegrationState(state) ?? initialDatabasePath;
  try {
    await stat(databasePath);
  } catch {
    await mkdir(path.dirname(databasePath), { recursive: true });
    await atomicWriteJson(databasePath, { schema_version: 2, entries: [] });
  }

  const existingOutput = outputPathFromIntegrationState(state);
  const outputMode = outputModeFromIntegrationState(state)
    ?? (projectOutputPath ? "project" : "database");
  const outputPath = outputMode === "project" && projectOutputPath
    ? projectOutputPath
    : existingOutput ?? projectOutputPath ?? databasePath.replace(/\.json$/i, ".tex");

  return updateDesktopIntegrationState({ ...state, databasePath, outputPath, outputMode }, statePath);
}

export async function readDesktopDatabasePath(): Promise<string | undefined> {
  return databasePathFromIntegrationState(await readDesktopIntegrationState());
}

export async function readDesktopOutputPath(): Promise<string | undefined> {
  return outputPathFromIntegrationState(await readDesktopIntegrationState());
}

export async function readDesktopLauncher(): Promise<DesktopLauncher | undefined> {
  return launcherFromIntegrationState(await readDesktopIntegrationState());
}
