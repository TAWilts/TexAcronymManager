import { readFile } from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";

export interface DesktopIntegrationState {
  databasePath?: unknown;
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

export function databasePathFromIntegrationState(raw: unknown): string | undefined {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return undefined;
  }
  const value = (raw as DesktopIntegrationState).databasePath;
  if (typeof value !== "string" || !value.trim()) {
    return undefined;
  }
  return value.trim();
}

export async function readDesktopDatabasePath(): Promise<string | undefined> {
  try {
    const text = await readFile(desktopIntegrationStatePath(), "utf8");
    return databasePathFromIntegrationState(JSON.parse(text) as unknown);
  } catch {
    return undefined;
  }
}
