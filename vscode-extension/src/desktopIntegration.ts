import { readFile } from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";

export interface DesktopLauncher {
  executable: string;
  args: string[];
}

export interface DesktopIntegrationState {
  databasePath?: unknown;
  launcher?: unknown;
}

export function desktopLaunchArguments(
  launcherArguments: readonly string[],
  extraArguments: readonly string[],
  databasePath?: string,
): string[] {
  const databaseArguments = databasePath ? ["--database", databasePath] : [];
  return [...launcherArguments, ...extraArguments, ...databaseArguments];
}

export function desktopIntegrationStatePath(
  platform: NodeJS.Platform = process.platform,
  env: NodeJS.ProcessEnv = process.env,
  home: string = os.homedir(),
): string {
  if (platform === "win32" && env.APPDATA) {
    return path.join(env.APPDATA, "TAcroMan", "vscode-integration.json");
  }
  if (platform === "darwin") {
    return path.join(home, "Library", "Application Support", "TAcroMan", "vscode-integration.json");
  }
  return path.join(env.XDG_CONFIG_HOME || path.join(home, ".config"), "tacroman", "vscode-integration.json");
}

function objectState(raw: unknown): DesktopIntegrationState | undefined {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return undefined;
  }
  return raw as DesktopIntegrationState;
}

export function databasePathFromIntegrationState(raw: unknown): string | undefined {
  const state = objectState(raw);
  const value = state?.databasePath;
  if (typeof value !== "string" || !value.trim()) {
    return undefined;
  }
  return value.trim();
}

export function launcherFromIntegrationState(raw: unknown): DesktopLauncher | undefined {
  const state = objectState(raw);
  const launcher = state?.launcher;
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

  return {
    executable: candidate.executable.trim(),
    args: [...args],
  };
}

async function readDesktopIntegrationState(): Promise<unknown | undefined> {
  try {
    const text = await readFile(desktopIntegrationStatePath(), "utf8");
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

export async function readDesktopDatabasePath(): Promise<string | undefined> {
  return databasePathFromIntegrationState(await readDesktopIntegrationState());
}

export async function readDesktopLauncher(): Promise<DesktopLauncher | undefined> {
  return launcherFromIntegrationState(await readDesktopIntegrationState());
}
