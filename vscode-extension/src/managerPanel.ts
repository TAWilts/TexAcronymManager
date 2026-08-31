import { randomUUID } from "node:crypto";
import * as vscode from "vscode";
import { DatabaseManager } from "./databaseManager";
import { EditorProfile, editorProfileFromRaw, validateEditorEntry } from "./editorModel";
import {
  installationIdFromIntegrationState,
  outputPathFromIntegrationState,
  readDesktopIntegrationState,
  updateDesktopIntegrationState,
} from "./desktopIntegration";
import {
  legacyEntries,
  previewLocalEntries,
  renameParticipant,
  saveLocalEntries,
  saveWorkspaceProfile,
  WorkspaceConflictError,
  WorkspaceEntry,
  WorkspaceOwner,
} from "./workspace";

type SnapshotReason = "initial" | "mutation" | "external" | "selection";

interface ManagerSnapshot {
  hostKind: "vscode";
  language: "de" | "en";
  workspacePath: string;
  fragmentPath: string;
  outputPath?: string;
  legacyDatabasePath?: string;
  revision: string;
  entries: Array<WorkspaceEntry & { localUid?: string; editable: boolean; sources: Array<Record<string, unknown>> }>;
  conflicts: Array<Record<string, unknown>>;
  exportBlocked: boolean;
  owner: WorkspaceOwner;
  fragmentCount: number;
  workspaceError?: string;
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
  | { type: "ready" | "selectDatabase" | "selectOutput" | "openDesktop" | "dismissLegacySetup" }
  | { type: "selectProfile"; profileId: string; revision: string }
  | { type: "renameParticipant"; revision: string; displayName: string }
  | { type: "importDatabase"; revision: string }
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
  if (["ready", "selectDatabase", "selectOutput", "openDesktop", "dismissLegacySetup"].includes(raw.type)) {
    return { type: raw.type as "ready" | "selectDatabase" | "selectOutput" | "openDesktop" | "dismissLegacySetup" };
  }
  if (raw.type === "selectProfile" && typeof raw.profileId === "string" && typeof raw.revision === "string") {
    return { type: "selectProfile", profileId: raw.profileId, revision: raw.revision };
  }
  if (raw.type === "renameParticipant" && typeof raw.revision === "string" && typeof raw.displayName === "string") {
    return { type: "renameParticipant", revision: raw.revision, displayName: raw.displayName };
  }
  if (raw.type === "importDatabase" && typeof raw.revision === "string") {
    return { type: "importDatabase", revision: raw.revision };
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
    const merged = new Map<string, Record<string, unknown>>();
    for (const item of raw) {
      if (isObject(item) && typeof item.id === "string") merged.set(item.id, item);
    }
    const workspace = await this.databases.loadWorkspace();
    if (workspace && typeof workspace.profile.id === "string") merged.set(workspace.profile.id, workspace.profile);
    return [...merged.values()];
  }

  private async profileState(): Promise<{
    profile: EditorProfile;
    profiles: Array<{ id: string; name: string }>;
    raw: Record<string, unknown>;
  }> {
    const workspace = await this.databases.loadWorkspace();
    if (!workspace) throw new Error("No TAcroMan workspace is selected.");
    const rawProfiles = await this.availableRawProfiles();
    const selectedId = typeof workspace.profile.id === "string" ? workspace.profile.id : "acronym-package";
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

  private async selectProfile(profileId: string, expectedRevision: string): Promise<void> {
    const rawProfiles = await this.availableRawProfiles();
    const selected = rawProfiles.find((item) => item.id === profileId);
    if (!selected || !editorProfileFromRaw(selected)) throw new Error("The selected profile is not available.");
    const state = await readDesktopIntegrationState();
    const installationId = installationIdFromIntegrationState(state);
    const workspace = await this.databases.loadWorkspace();
    if (!workspace || !installationId) throw new Error("No TAcroMan workspace is selected.");
    await saveWorkspaceProfile(workspace.workspacePath, installationId, expectedRevision, selected);
    this.databases.clearCache();
  }

  private async snapshot(): Promise<ManagerSnapshot> {
    const [workspace, state, profiles] = await Promise.all([
      this.databases.loadWorkspace(),
      readDesktopIntegrationState(),
      this.profileState(),
    ]);
    if (!workspace) throw new Error("No TAcroMan workspace is selected.");
    return {
      hostKind: "vscode",
      language: state?.language === "de" ? "de" : "en",
      workspacePath: workspace.workspacePath,
      fragmentPath: workspace.localFragmentPath,
      outputPath: outputPathFromIntegrationState(state),
      legacyDatabasePath: typeof state?.legacyDatabasePath === "string" ? state.legacyDatabasePath : undefined,
      revision: workspace.revision,
      entries: workspace.entries.map((entry) => ({
        ...entry,
        sources: entry.sources.map((source) => ({
          owner: source.owner.display_name,
          installationId: source.owner.installation_id,
          fragment: source.fragmentPath,
          uid: source.entry.uid,
        })),
      })),
      conflicts: workspace.conflicts.map((conflict) => ({
        id: conflict.id,
        label: conflict.label,
        localUids: conflict.localUids,
        variants: conflict.variants.map((source) => ({
          uid: source.entry.uid,
          commandId: source.entry.commandId,
          values: source.entry.values,
          owner: source.owner.display_name,
          installationId: source.owner.installation_id,
          fragment: source.fragmentPath,
          editable: source.editable,
        })),
      })),
      exportBlocked: workspace.exportBlocked,
      owner: workspace.localOwner,
      fragmentCount: workspace.fragmentCount,
      workspaceError: this.databases.getWorkspaceError(),
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
    const workspace = await this.databases.loadWorkspace();
    const state = await readDesktopIntegrationState();
    const installationId = installationIdFromIntegrationState(state);
    if (!workspace || !installationId) throw new Error("No TAcroMan workspace is selected.");
    const profile = await this.activeProfile();
    let localEntries = [...workspace.localEntries];
    if (message.type === "saveEntry") {
      const uid = message.entry.uid ?? randomUUID();
      const candidate = { uid, commandId: message.entry.commandId, values: message.entry.values };
      const errors = validateEditorEntry(candidate, localEntries, profile);
      if (errors.length) throw new Error(errors.join("\n"));
      const index = localEntries.findIndex((entry) => entry.uid === uid);
      if (index >= 0) localEntries[index] = candidate;
      else localEntries.push(candidate);
    } else {
      if (!localEntries.some((entry) => entry.uid === message.uid)) throw new Error("The selected entry is read-only or no longer exists.");
      localEntries = localEntries.filter((entry) => entry.uid !== message.uid);
    }
    const existingConflicts = new Set(workspace.conflicts.map((conflict) => conflict.id));
    const introduced = previewLocalEntries(workspace, localEntries).conflicts
      .filter((conflict) => !existingConflicts.has(conflict.id));
    if (introduced.length) {
      throw new Error("An entry with the same profile key already exists with different values.");
    }
    await saveLocalEntries(workspace.workspacePath, installationId, message.revision, localEntries);
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
        case "dismissLegacySetup":
          await updateDesktopIntegrationState({ legacyDatabasePath: undefined, databasePath: undefined });
          break;
        case "selectProfile":
          await this.selectProfile(message.profileId, message.revision);
          await this.postSnapshot("selection");
          break;
        case "renameParticipant": {
          const state = await readDesktopIntegrationState();
          const installationId = installationIdFromIntegrationState(state);
          const workspace = await this.databases.loadWorkspace();
          if (!workspace || !installationId) throw new Error("No TAcroMan workspace is selected.");
          const renamed = await renameParticipant(workspace.workspacePath, installationId, message.revision, message.displayName);
          await updateDesktopIntegrationState({ fragmentPath: renamed.localFragmentPath });
          this.databases.clearCache();
          await this.postSnapshot("selection");
          break;
        }
        case "importDatabase": {
          const picked = await vscode.window.showOpenDialog({
            canSelectFiles: true,
            canSelectFolders: false,
            canSelectMany: false,
            filters: { "Legacy TAcroMan database": ["json"] },
            title: "Import existing TAcroMan database",
          });
          if (!picked?.[0]) break;
          const state = await readDesktopIntegrationState();
          const installationId = installationIdFromIntegrationState(state);
          const workspace = await this.databases.loadWorkspace();
          if (!workspace || !installationId) throw new Error("No TAcroMan workspace is selected.");
          const raw = JSON.parse(new TextDecoder("utf8").decode(await vscode.workspace.fs.readFile(picked[0]))) as unknown;
          const imported = legacyEntries(raw);
          const byUid = new Map(workspace.localEntries.map((entry) => [entry.uid, entry]));
          for (const entry of imported) byUid.set(entry.uid, entry);
          const proposed = [...byUid.values()];
          const preview = previewLocalEntries(workspace, proposed);
          const existingDuplicates = workspace.entries.reduce((count, entry) => count + Math.max(0, entry.sources.length - 1), 0);
          const proposedDuplicates = preview.entries.reduce((count, entry) => count + Math.max(0, entry.sources.length - 1), 0);
          const duplicateCount = Math.max(0, proposedDuplicates - existingDuplicates);
          const conflictLabels = preview.conflicts.map((conflict) => conflict.label);
          const decision = await vscode.window.showWarningMessage(
            `Import ${imported.length} entries into your participant fragment?`,
            {
              modal: true,
              detail: `Identical duplicates: ${duplicateCount}\nConflicts after import: ${conflictLabels.length ? conflictLabels.join(", ") : "0"}\n\nThe source file and foreign fragments will not be changed.`,
            },
            "Import",
          );
          if (decision !== "Import") break;
          await saveLocalEntries(workspace.workspacePath, installationId, message.revision, proposed);
          await updateDesktopIntegrationState({ legacyDatabasePath: undefined, databasePath: undefined });
          this.databases.clearCache();
          await this.postSnapshot("mutation");
          break;
        }
        case "saveEntry":
        case "deleteEntry":
          await this.mutate(message);
          break;
      }
    } catch (error) {
      await this.postError(error);
      if (error instanceof WorkspaceConflictError) await this.postSnapshot("external");
    }
  }

}
