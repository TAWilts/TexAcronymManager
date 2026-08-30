import * as vscode from "vscode";
import { DatabaseManager } from "./databaseManager";
import {
  DatabaseConflictError,
  EditorProfile,
  editorProfileFromRaw,
  mutateEditorDatabase,
  readEditorDatabase,
} from "./editorModel";
import {
  outputPathFromIntegrationState,
  readDesktopIntegrationState,
  updateDesktopIntegrationState,
} from "./desktopIntegration";

type SnapshotReason = "initial" | "mutation" | "external" | "selection";

interface ManagerSnapshot {
  hostKind: "vscode";
  language: "de" | "en";
  databasePath: string;
  outputPath?: string;
  revision: string;
  entries: Awaited<ReturnType<typeof readEditorDatabase>>["entries"];
  profile: EditorProfile;
  profiles: Array<{ id: string; name: string }>;
}

interface SaveEntryMessage {
  type: "saveEntry";
  revision: string;
  entry: {
    uid?: string;
    commandId: string;
    values: Record<string, string>;
  };
}

interface DeleteEntryMessage {
  type: "deleteEntry";
  revision: string;
  uid: string;
}

type ManagerMessage =
  | { type: "ready" | "selectDatabase" | "selectOutput" | "openDesktop" }
  | { type: "selectProfile"; profileId: string }
  | SaveEntryMessage
  | DeleteEntryMessage;

function nonce(): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  return Array.from({ length: 32 }, () => alphabet[Math.floor(Math.random() * alphabet.length)]).join("");
}

function isObject(raw: unknown): raw is Record<string, unknown> {
  return Boolean(raw) && typeof raw === "object" && !Array.isArray(raw);
}

function stringRecord(raw: unknown): Record<string, string> | undefined {
  if (!isObject(raw)) return undefined;
  const entries = Object.entries(raw);
  return entries.every(([, value]) => typeof value === "string")
    ? Object.fromEntries(entries) as Record<string, string>
    : undefined;
}

function managerMessage(raw: unknown): ManagerMessage | undefined {
  if (!isObject(raw) || typeof raw.type !== "string") return undefined;
  if (["ready", "selectDatabase", "selectOutput", "openDesktop"].includes(raw.type)) {
    return { type: raw.type as "ready" | "selectDatabase" | "selectOutput" | "openDesktop" };
  }
  if (raw.type === "selectProfile" && typeof raw.profileId === "string") {
    return { type: "selectProfile", profileId: raw.profileId };
  }
  if (raw.type === "deleteEntry" && typeof raw.revision === "string" && typeof raw.uid === "string") {
    return { type: "deleteEntry", revision: raw.revision, uid: raw.uid };
  }
  if (raw.type === "saveEntry" && typeof raw.revision === "string" && isObject(raw.entry)) {
    const values = stringRecord(raw.entry.values);
    if (typeof raw.entry.commandId !== "string" || !values) return undefined;
    return {
      type: "saveEntry",
      revision: raw.revision,
      entry: {
        uid: typeof raw.entry.uid === "string" ? raw.entry.uid : undefined,
        commandId: raw.entry.commandId,
        values,
      },
    };
  }
  return undefined;
}

export class TAcroManManagerPanel implements vscode.Disposable {
  private static current: TAcroManManagerPanel | undefined;

  static async show(context: vscode.ExtensionContext, databases: DatabaseManager): Promise<void> {
    if (this.current) {
      this.current.panel.reveal(vscode.ViewColumn.Active);
      void this.current.postSnapshot("initial");
      return;
    }

    const assets = vscode.Uri.joinPath(context.extensionUri, "assets", "webview");
    const panel = vscode.window.createWebviewPanel(
      "tacroman.manager",
      "TAcroMan",
      vscode.ViewColumn.Active,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [assets],
      },
    );
    this.current = new TAcroManManagerPanel(context, databases, panel);
    await this.current.loadHtml(assets);
  }

  private readonly disposables: vscode.Disposable[] = [];
  private externalReloadTimer: NodeJS.Timeout | undefined;

  private constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly databases: DatabaseManager,
    readonly panel: vscode.WebviewPanel,
  ) {
    this.disposables.push(
      panel.onDidDispose(() => this.dispose()),
      panel.webview.onDidReceiveMessage((raw) => void this.handleMessage(raw)),
      databases.onDidChangeDatabase(() => this.scheduleExternalReload()),
    );
  }

  private async loadHtml(assets: vscode.Uri): Promise<void> {
    try {
      const templateUri = vscode.Uri.joinPath(assets, "index.html");
      const template = new TextDecoder("utf-8").decode(await vscode.workspace.fs.readFile(templateUri));
      const token = nonce();
      const stylesheet = this.panel.webview.asWebviewUri(vscode.Uri.joinPath(assets, "app.css"));
      const script = this.panel.webview.asWebviewUri(vscode.Uri.joinPath(assets, "app.js"));
      this.panel.webview.html = template
        .replaceAll("{{CSP}}", `default-src 'none'; style-src ${this.panel.webview.cspSource}; script-src 'nonce-${token}';`)
        .replaceAll("{{STYLE_URI}}", stylesheet.toString())
        .replaceAll("{{SCRIPT_URI}}", script.toString())
        .replaceAll("{{NONCE}}", token);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.panel.webview.html = `<!doctype html><html><body><h1>TAcroMan</h1><p>${this.escapeHtml(message)}</p></body></html>`;
    }
  }

  private escapeHtml(value: string): string {
    return value.replace(/[&<>"']/g, (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "\"": "&quot;",
      "'": "&#39;",
    })[character] ?? character);
  }

  dispose(): void {
    if (this.externalReloadTimer) clearTimeout(this.externalReloadTimer);
    this.externalReloadTimer = undefined;
    TAcroManManagerPanel.current = undefined;
    while (this.disposables.length) this.disposables.pop()?.dispose();
  }

  private scheduleExternalReload(): void {
    if (this.externalReloadTimer) clearTimeout(this.externalReloadTimer);
    this.externalReloadTimer = setTimeout(() => {
      this.externalReloadTimer = undefined;
      void this.postSnapshot("external");
    }, 200);
  }

  private async availableRawProfiles(): Promise<Record<string, unknown>[]> {
    const uri = vscode.Uri.joinPath(this.context.extensionUri, "assets", "webview", "default-profiles.json");
    const content = new TextDecoder("utf-8").decode(await vscode.workspace.fs.readFile(uri));
    const raw = JSON.parse(content) as unknown;
    if (!Array.isArray(raw)) throw new Error("The bundled TAcroMan profiles are invalid.");
    const state = await readDesktopIntegrationState();
    const merged = new Map<string, Record<string, unknown>>();
    for (const item of raw) {
      if (isObject(item) && typeof item.id === "string") merged.set(item.id, item);
    }
    if (typeof state?.profilesPath === "string" && state.profilesPath.trim()) {
      try {
        const customUri = vscode.Uri.file(state.profilesPath.trim());
        const customContent = new TextDecoder("utf-8").decode(await vscode.workspace.fs.readFile(customUri));
        const custom = JSON.parse(customContent) as unknown;
        if (Array.isArray(custom)) {
          for (const item of custom) {
            if (isObject(item) && typeof item.id === "string") merged.set(item.id, item);
          }
        }
      } catch {
        // Missing or temporarily invalid custom profiles must not hide the bundled defaults.
      }
    }
    if (isObject(state?.renderProfile) && typeof state.renderProfile.id === "string") {
      merged.set(state.renderProfile.id, state.renderProfile);
    }
    return [...merged.values()];
  }

  private async profileState(): Promise<{
    profile: EditorProfile;
    profiles: Array<{ id: string; name: string }>;
    raw: Record<string, unknown>;
  }> {
    const state = await readDesktopIntegrationState();
    const rawProfiles = await this.availableRawProfiles();
    const selectedId = typeof state?.selectedProfileId === "string" ? state.selectedProfileId : "acronym-package";
    const selectedRaw = rawProfiles.find((item) => item.id === selectedId) ?? rawProfiles[0];
    const profile = editorProfileFromRaw(selectedRaw);
    if (!selectedRaw || !profile) throw new Error("No usable TAcroMan profile was found.");
    const profiles = rawProfiles.flatMap((rawProfile) => {
      const normalized = editorProfileFromRaw(rawProfile);
      return normalized ? [{ id: normalized.id, name: normalized.name }] : [];
    });
    return { profile, profiles, raw: selectedRaw };
  }

  private async activeProfile(): Promise<EditorProfile> {
    return (await this.profileState()).profile;
  }

  private async selectProfile(profileId: string): Promise<void> {
    const rawProfiles = await this.availableRawProfiles();
    const selected = rawProfiles.find((item) => item.id === profileId);
    if (!selected || !editorProfileFromRaw(selected)) throw new Error("The selected profile is not available.");
    await updateDesktopIntegrationState({ selectedProfileId: profileId, renderProfile: selected });
    this.databases.clearCache();
  }

  private async snapshot(): Promise<ManagerSnapshot> {
    const database = await this.databases.getDatabaseUri();
    if (!database) throw new Error("No TAcroMan database is selected.");
    const [content, state, profiles] = await Promise.all([
      readEditorDatabase(database.fsPath),
      readDesktopIntegrationState(),
      this.profileState(),
    ]);
    return {
      hostKind: "vscode",
      language: state?.language === "de" ? "de" : "en",
      databasePath: database.fsPath,
      outputPath: outputPathFromIntegrationState(state),
      revision: content.revision,
      entries: content.entries,
      profile: profiles.profile,
      profiles: profiles.profiles,
    };
  }

  private async postSnapshot(reason: SnapshotReason): Promise<void> {
    try {
      await this.panel.webview.postMessage({ type: "snapshot", reason, snapshot: await this.snapshot() });
    } catch (error) {
      await this.postError(error);
    }
  }

  private async postError(error: unknown): Promise<void> {
    const message = error instanceof Error ? error.message : String(error);
    await this.panel.webview.postMessage({ type: "error", message });
  }

  private async mutate(message: SaveEntryMessage | DeleteEntryMessage): Promise<void> {
    const database = await this.databases.getDatabaseUri();
    if (!database) throw new Error("No TAcroMan database is selected.");
    const profile = await this.activeProfile();
    if (message.type === "saveEntry") {
      await mutateEditorDatabase(database.fsPath, message.revision, {
        kind: "save",
        uid: message.entry.uid,
        commandId: message.entry.commandId,
        values: message.entry.values,
      }, profile);
    } else {
      await mutateEditorDatabase(database.fsPath, message.revision, {
        kind: "delete",
        uid: message.uid,
      }, profile);
    }
    this.databases.clearCache();
    await this.postSnapshot("mutation");
  }

  private async handleMessage(raw: unknown): Promise<void> {
    const message = managerMessage(raw);
    if (!message) {
      await this.postError(new Error("The TAcroMan editor received an invalid request."));
      return;
    }
    try {
      switch (message.type) {
        case "ready":
          await this.postSnapshot("initial");
          break;
        case "selectDatabase":
          if (await this.databases.selectDatabase()) await this.postSnapshot("selection");
          break;
        case "selectOutput":
          if (await this.databases.selectOutput()) await this.postSnapshot("selection");
          break;
        case "openDesktop":
          await vscode.commands.executeCommand("tacroman.openDesktop");
          break;
        case "selectProfile":
          await this.selectProfile(message.profileId);
          await this.postSnapshot("selection");
          break;
        case "saveEntry":
        case "deleteEntry":
          await this.mutate(message);
          break;
      }
    } catch (error) {
      await this.postError(error);
      if (error instanceof DatabaseConflictError) await this.postSnapshot("external");
    }
  }

}
