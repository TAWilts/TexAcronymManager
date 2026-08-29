import * as path from "node:path";
import * as vscode from "vscode";
import { AcronymCandidate, candidatesFromDatabase } from "./database";
import {
  databasePathFromIntegrationState,
  ensureDesktopIntegrationState,
  outputModeFromIntegrationState,
  outputPathFromIntegrationState,
  readDesktopIntegrationState,
  updateDesktopIntegrationState,
} from "./desktopIntegration";

interface CachedDatabase {
  uri: vscode.Uri;
  mtime: number;
  candidates: AcronymCandidate[];
}

export class DatabaseManager implements vscode.Disposable {
  private cache: CachedDatabase | undefined;
  private readonly disposables: vscode.Disposable[] = [];
  private readonly databaseChangedEmitter = new vscode.EventEmitter<void>();

  readonly onDidChangeDatabase = this.databaseChangedEmitter.event;

  constructor() {
    const watcher = vscode.workspace.createFileSystemWatcher("**/*.json");
    this.disposables.push(
      watcher,
      watcher.onDidChange((uri) => this.invalidateIfSelected(uri)),
      watcher.onDidDelete((uri) => this.invalidateIfSelected(uri)),
      watcher.onDidCreate(() => this.clearCache()),
    );
  }

  async initialize(): Promise<void> {
    await ensureDesktopIntegrationState(this.projectOutputPath());
    await this.syncProjectOutput();
    this.clearCache();
  }

  dispose(): void {
    for (const disposable of this.disposables) {
      disposable.dispose();
    }
    this.databaseChangedEmitter.dispose();
  }

  clearCache(): void {
    this.cache = undefined;
    this.databaseChangedEmitter.fire();
  }

  sharedStateChanged(): void {
    this.clearCache();
  }

  private invalidateIfSelected(uri: vscode.Uri): void {
    if (!this.cache || this.cache.uri.fsPath === uri.fsPath) {
      this.clearCache();
    }
  }

  async selectDatabase(): Promise<vscode.Uri | undefined> {
    const current = await this.getDatabaseUri();
    const picked = await vscode.window.showOpenDialog({
      defaultUri: current,
      canSelectFiles: true,
      canSelectFolders: false,
      canSelectMany: false,
      filters: { "TAcroMan database": ["json"] },
      title: "Select TAcroMan database",
    });
    if (!picked?.[0]) {
      return undefined;
    }
    return this.selectUri(picked[0]);
  }

  async selectOutput(): Promise<vscode.Uri | undefined> {
    const database = await this.getDatabaseUri();
    const current = await this.getOutputUri();
    const picked = await vscode.window.showSaveDialog({
      defaultUri: current ?? (database ? database.with({ path: database.path.replace(/\.json$/i, ".tex") }) : undefined),
      filters: { "TeX file": ["tex"] },
      title: "Select generated TeX output",
    });
    if (!picked) {
      return undefined;
    }
    await updateDesktopIntegrationState({ outputPath: picked.fsPath, outputMode: "custom" });
    this.clearCache();
    return picked;
  }

  async getOutputUri(): Promise<vscode.Uri | undefined> {
    const state = await readDesktopIntegrationState();
    const stored = outputPathFromIntegrationState(state);
    if (stored) {
      return vscode.Uri.file(stored);
    }
    const database = await this.getDatabaseUri();
    return database ? database.with({ path: database.path.replace(/\.json$/i, ".tex") }) : undefined;
  }

  async syncProjectOutput(document?: vscode.TextDocument): Promise<void> {
    const state = await readDesktopIntegrationState();
    if (outputModeFromIntegrationState(state) !== "project") {
      return;
    }
    const desired = this.projectOutputPath(document);
    if (desired && outputPathFromIntegrationState(state) !== desired) {
      await updateDesktopIntegrationState({ outputPath: desired, outputMode: "project" });
      this.clearCache();
    }
  }

  private async selectUri(uri: vscode.Uri): Promise<vscode.Uri> {
    const state = await readDesktopIntegrationState();
    const changes: Record<string, unknown> = { databasePath: uri.fsPath };
    if (outputModeFromIntegrationState(state) === "database") {
      changes.outputPath = uri.fsPath.replace(/\.json$/i, ".tex");
    }
    await updateDesktopIntegrationState(changes);
    this.clearCache();
    vscode.window.setStatusBarMessage(`TAcroMan: ${vscode.workspace.asRelativePath(uri, false)}`, 4000);
    return uri;
  }

  async getDatabaseUri(_activeDocument?: vscode.TextDocument): Promise<vscode.Uri | undefined> {
    const state = await readDesktopIntegrationState();
    const selected = databasePathFromIntegrationState(state);
    if (selected) {
      const uri = vscode.Uri.file(selected);
      try {
        await vscode.workspace.fs.stat(uri);
        return uri;
      } catch {
        return undefined;
      }
    }
    return undefined;
  }

  async loadCandidates(activeDocument?: vscode.TextDocument): Promise<AcronymCandidate[]> {
    const uri = await this.getDatabaseUri(activeDocument);
    if (!uri) {
      return [];
    }

    const stat = await vscode.workspace.fs.stat(uri);
    if (this.cache && this.cache.uri.fsPath === uri.fsPath && this.cache.mtime === stat.mtime) {
      return this.cache.candidates;
    }

    const bytes = await vscode.workspace.fs.readFile(uri);
    const text = new TextDecoder("utf-8").decode(bytes);
    const candidates = candidatesFromDatabase(JSON.parse(text) as unknown);
    this.cache = { uri, mtime: stat.mtime, candidates };
    return candidates;
  }

  private projectOutputPath(document?: vscode.TextDocument): string | undefined {
    const activeDocument = document ?? vscode.window.activeTextEditor?.document;
    const folder = (activeDocument ? vscode.workspace.getWorkspaceFolder(activeDocument.uri) : undefined)
      ?? vscode.workspace.workspaceFolders?.[0];
    return folder ? path.join(folder.uri.fsPath, "entries.tex") : undefined;
  }
}
