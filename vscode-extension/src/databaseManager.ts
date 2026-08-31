import * as path from "node:path";
import * as vscode from "vscode";
import { AcronymCandidate, candidatesFromDatabase } from "./database";
import {
  ensureDesktopIntegrationState,
  installationIdFromIntegrationState,
  outputModeFromIntegrationState,
  outputPathFromIntegrationState,
  readDesktopIntegrationState,
  updateDesktopIntegrationState,
  workspacePathFromIntegrationState,
} from "./desktopIntegration";
import {
  createWorkspace as createWorkspaceOnDisk,
  DEFAULT_WORKSPACE_PROFILE,
  joinWorkspace,
  loadWorkspace,
  MANIFEST_FILENAME,
  WorkspaceSnapshot,
} from "./workspace";

interface CachedWorkspace {
  workspacePath: string;
  snapshot: WorkspaceSnapshot;
  candidates: AcronymCandidate[];
}

export class DatabaseManager implements vscode.Disposable {
  private cache: CachedWorkspace | undefined;
  private lastValid: CachedWorkspace | undefined;
  private workspaceError: string | undefined;
  private readonly disposables: vscode.Disposable[] = [];
  private readonly databaseChangedEmitter = new vscode.EventEmitter<void>();

  readonly onDidChangeDatabase = this.databaseChangedEmitter.event;

  async initialize(): Promise<void> {
    try {
      await ensureDesktopIntegrationState(this.projectOutputPath());
      await this.syncProjectOutput();
    } catch (error) {
      this.workspaceError = `TAcroMan workspace error: ${error instanceof Error ? error.message : String(error)}`;
    }
    this.clearCache();
  }

  dispose(): void {
    for (const disposable of this.disposables) disposable.dispose();
    this.databaseChangedEmitter.dispose();
  }

  clearCache(): void {
    this.cache = undefined;
    this.databaseChangedEmitter.fire();
  }

  sharedStateChanged(): void {
    this.clearCache();
  }

  getWorkspaceError(): string | undefined {
    return this.workspaceError;
  }

  setWorkspaceError(message: string | undefined): void {
    if (message === this.workspaceError) return;
    this.workspaceError = message;
    this.databaseChangedEmitter.fire();
  }

  async selectWorkspace(): Promise<vscode.Uri | undefined> {
    const current = await this.getWorkspaceUri();
    const picked = await vscode.window.showOpenDialog({
      defaultUri: current,
      canSelectFiles: false,
      canSelectFolders: true,
      canSelectMany: false,
      title: "Select or create a TAcroMan workspace folder",
    });
    if (!picked?.[0]) return undefined;
    return this.selectUri(picked[0]);
  }

  async selectDatabase(): Promise<vscode.Uri | undefined> {
    return this.selectWorkspace();
  }

  async createNewWorkspace(): Promise<vscode.Uri | undefined> {
    const picked = await vscode.window.showOpenDialog({
      canSelectFiles: false,
      canSelectFolders: true,
      canSelectMany: false,
      title: "Create a TAcroMan workspace in the selected folder",
    });
    if (!picked?.[0]) return undefined;
    const state = await readDesktopIntegrationState();
    const installationId = installationIdFromIntegrationState(state);
    if (!installationId) throw new Error("TAcroMan installation identity is missing.");
    const active = await this.loadWorkspace();
    const snapshot = await createWorkspaceOnDisk(
      picked[0].fsPath,
      installationId,
      active?.profile ?? DEFAULT_WORKSPACE_PROFILE,
    );
    await this.persistSelection(picked[0], snapshot, state);
    return picked[0];
  }

  async selectOutput(): Promise<vscode.Uri | undefined> {
    const workspace = await this.getWorkspaceUri();
    const current = await this.getOutputUri();
    const picked = await vscode.window.showSaveDialog({
      defaultUri: current ?? (workspace ? vscode.Uri.file(path.join(workspace.fsPath, "entries.tex")) : undefined),
      filters: { "TeX file": ["tex"] },
      title: "Select generated TeX output",
    });
    if (!picked) return undefined;
    await updateDesktopIntegrationState({ outputPath: picked.fsPath, outputMode: "custom" });
    this.clearCache();
    return picked;
  }

  async getOutputUri(): Promise<vscode.Uri | undefined> {
    const state = await readDesktopIntegrationState();
    if (outputModeFromIntegrationState(state) === "database") {
      const workspace = await this.getWorkspaceUri();
      return workspace ? vscode.Uri.file(path.join(workspace.fsPath, "entries.tex")) : undefined;
    }
    const stored = outputPathFromIntegrationState(state);
    if (stored) return vscode.Uri.file(stored);
    const workspace = await this.getWorkspaceUri();
    return workspace ? vscode.Uri.file(path.join(workspace.fsPath, "entries.tex")) : undefined;
  }

  async syncProjectOutput(document?: vscode.TextDocument): Promise<void> {
    const state = await readDesktopIntegrationState();
    if (outputModeFromIntegrationState(state) !== "project") return;
    const desired = this.projectOutputPath(document);
    if (desired && outputPathFromIntegrationState(state) !== desired) {
      await updateDesktopIntegrationState({ outputPath: desired, outputMode: "project" });
      this.clearCache();
    }
  }

  private async selectUri(uri: vscode.Uri): Promise<vscode.Uri> {
    const activeProfile = (await this.loadWorkspace())?.profile ?? DEFAULT_WORKSPACE_PROFILE;
    const state = await readDesktopIntegrationState();
    const installationId = installationIdFromIntegrationState(state);
    if (!installationId) throw new Error("TAcroMan installation identity is missing.");
    let snapshot: WorkspaceSnapshot;
    try {
      snapshot = await joinWorkspace(uri.fsPath, installationId);
    } catch (error) {
      try {
        await vscode.workspace.fs.stat(vscode.Uri.file(path.join(uri.fsPath, MANIFEST_FILENAME)));
        throw error;
      } catch (manifestError) {
        if (manifestError === error) throw error;
        snapshot = await createWorkspaceOnDisk(uri.fsPath, installationId, activeProfile);
      }
    }
    await this.persistSelection(uri, snapshot, state);
    return uri;
  }

  private async persistSelection(
    uri: vscode.Uri,
    snapshot: WorkspaceSnapshot,
    state: Awaited<ReturnType<typeof readDesktopIntegrationState>>,
  ): Promise<void> {
    const changes: Record<string, unknown> = {
      workspacePath: uri.fsPath,
      fragmentPath: snapshot.localFragmentPath,
    };
    if (outputModeFromIntegrationState(state) === "database") {
      changes.outputPath = path.join(uri.fsPath, "entries.tex");
    }
    await updateDesktopIntegrationState(changes);
    this.workspaceError = undefined;
    this.clearCache();
    vscode.window.setStatusBarMessage(`TAcroMan: ${vscode.workspace.asRelativePath(uri, false)}`, 4000);
  }

  async getWorkspaceUri(_activeDocument?: vscode.TextDocument): Promise<vscode.Uri | undefined> {
    const selected = workspacePathFromIntegrationState(await readDesktopIntegrationState());
    if (!selected) return undefined;
    const uri = vscode.Uri.file(selected);
    try {
      await vscode.workspace.fs.stat(uri);
      return uri;
    } catch {
      return undefined;
    }
  }

  async getDatabaseUri(activeDocument?: vscode.TextDocument): Promise<vscode.Uri | undefined> {
    return this.getWorkspaceUri(activeDocument);
  }

  async loadWorkspace(): Promise<WorkspaceSnapshot | undefined> {
    const state = await readDesktopIntegrationState();
    const workspacePath = workspacePathFromIntegrationState(state);
    const installationId = installationIdFromIntegrationState(state);
    if (!workspacePath || !installationId) return undefined;
    if (this.cache?.workspacePath === workspacePath) return this.cache.snapshot;
    try {
      return await this.readWorkspace(workspacePath, installationId);
    } catch (error) {
      if (this.lastValid?.workspacePath === workspacePath) return this.lastValid.snapshot;
      throw error;
    }
  }

  async reloadWorkspace(): Promise<WorkspaceSnapshot | undefined> {
    const state = await readDesktopIntegrationState();
    const workspacePath = workspacePathFromIntegrationState(state);
    const installationId = installationIdFromIntegrationState(state);
    if (!workspacePath || !installationId) return undefined;
    const previousRevision = this.lastValid?.workspacePath === workspacePath
      ? this.lastValid.snapshot.revision
      : undefined;
    this.cache = undefined;
    const snapshot = await this.readWorkspace(workspacePath, installationId);
    if (previousRevision !== snapshot.revision) this.databaseChangedEmitter.fire();
    return snapshot;
  }

  private async readWorkspace(workspacePath: string, installationId: string): Promise<WorkspaceSnapshot> {
    const snapshot = await loadWorkspace(workspacePath, installationId);
    const database = {
      entries: snapshot.entries.map((entry) => ({
        uid: entry.uid,
        command_id: entry.commandId,
        values: entry.values,
      })),
    };
    const candidates = candidatesFromDatabase(database);
    this.cache = { workspacePath, snapshot, candidates };
    this.lastValid = this.cache;
    return snapshot;
  }

  async loadCandidates(_activeDocument?: vscode.TextDocument): Promise<AcronymCandidate[]> {
    const snapshot = await this.loadWorkspace();
    if (!snapshot) return [];
    return this.cache?.candidates ?? [];
  }

  private projectOutputPath(document?: vscode.TextDocument): string | undefined {
    const activeDocument = document ?? vscode.window.activeTextEditor?.document;
    const folder = (activeDocument ? vscode.workspace.getWorkspaceFolder(activeDocument.uri) : undefined)
      ?? vscode.workspace.workspaceFolders?.[0];
    return folder ? path.join(folder.uri.fsPath, "entries.tex") : undefined;
  }
}
