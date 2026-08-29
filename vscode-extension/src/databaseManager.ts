import * as path from "node:path";
import * as vscode from "vscode";
import { AcronymCandidate, candidatesFromDatabase } from "./database";
import { readDesktopDatabasePath } from "./desktopIntegration";

interface CachedDatabase {
  uri: vscode.Uri;
  mtime: number;
  candidates: AcronymCandidate[];
}

export class DatabaseManager implements vscode.Disposable {
  private cache: CachedDatabase | undefined;
  private readonly disposables: vscode.Disposable[] = [];
  private readonly databaseChangedEmitter = new vscode.EventEmitter<void>();
  private selectedDatabase: vscode.Uri | undefined;

  readonly onDidChangeDatabase = this.databaseChangedEmitter.event;

  constructor(private readonly context: vscode.ExtensionContext) {
    const watcher = vscode.workspace.createFileSystemWatcher("**/*.json");
    this.disposables.push(
      watcher,
      watcher.onDidChange((uri) => this.invalidateIfSelected(uri)),
      watcher.onDidDelete((uri) => this.invalidateIfSelected(uri)),
      watcher.onDidCreate(() => this.clearCache()),
      vscode.workspace.onDidChangeConfiguration((event) => {
        if (event.affectsConfiguration("tacroman.databasePath")) {
          this.selectedDatabase = undefined;
          this.clearCache();
        }
      }),
    );
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

  private invalidateIfSelected(uri: vscode.Uri): void {
    if (!this.cache || this.cache.uri.fsPath === uri.fsPath) {
      this.clearCache();
    }
  }

  async selectDatabase(): Promise<vscode.Uri | undefined> {
    // A database created or opened by the desktop application can be outside
    // the current workspace. Prefer that published path for the first run.
    const desktopPath = await readDesktopDatabasePath();
    if (desktopPath) {
      const desktopUri = vscode.Uri.file(desktopPath);
      try {
        await vscode.workspace.fs.stat(desktopUri);
        return this.selectUri(desktopUri);
      } catch {
        // Ignore stale desktop state and continue with workspace discovery.
      }
    }

    const choices = await this.discoverDatabases();
    if (!choices.length) {
      vscode.window.showWarningMessage("TAcroMan: No acronym database was found in this workspace.");
      return undefined;
    }

    const picked = await vscode.window.showQuickPick(
      choices.map((uri) => ({
        label: path.basename(uri.fsPath),
        description: vscode.workspace.asRelativePath(uri, false),
        uri,
      })),
      { placeHolder: "Select the TAcroMan database for this workspace" },
    );
    if (!picked) {
      return undefined;
    }

    return this.selectUri(picked.uri);
  }

  private async selectUri(uri: vscode.Uri): Promise<vscode.Uri> {
    this.selectedDatabase = uri;
    this.cache = undefined;
    const target = vscode.workspace.workspaceFolders?.length
      ? vscode.ConfigurationTarget.Workspace
      : vscode.ConfigurationTarget.Global;
    await vscode.workspace
      .getConfiguration("tacroman")
      .update("databasePath", uri.fsPath, target);
    await this.context.workspaceState.update("tacroman.selectedDatabase", undefined);
    this.databaseChangedEmitter.fire();
    vscode.window.setStatusBarMessage(`TAcroMan: ${vscode.workspace.asRelativePath(uri, false)}`, 4000);
    return uri;
  }

  async getDatabaseUri(activeDocument?: vscode.TextDocument): Promise<vscode.Uri | undefined> {
    const configured = this.configuredDatabaseUri(activeDocument);
    if (configured) {
      return configured;
    }

    // Default to the database currently selected in desktop TAcroMan.
    // An explicit VS Code tacroman.databasePath configuration still wins.
    const desktopPath = await readDesktopDatabasePath();
    if (desktopPath) {
      const desktopUri = vscode.Uri.file(desktopPath);
      try {
        await vscode.workspace.fs.stat(desktopUri);
        return desktopUri;
      } catch {
        // Stale desktop state: continue with the existing fallbacks.
      }
    }

    if (this.selectedDatabase) {
      return this.selectedDatabase;
    }

    const stored = this.context.workspaceState.get<string>("tacroman.selectedDatabase");
    if (stored) {
      const uri = vscode.Uri.parse(stored);
      try {
        await vscode.workspace.fs.stat(uri);
        this.selectedDatabase = uri;
        return uri;
      } catch {
        await this.context.workspaceState.update("tacroman.selectedDatabase", undefined);
      }
    }

    const choices = await this.discoverDatabases();
    if (!choices.length) {
      return undefined;
    }
    if (choices.length === 1) {
      this.selectedDatabase = choices[0];
      return choices[0];
    }

    const activeFolder = activeDocument ? vscode.workspace.getWorkspaceFolder(activeDocument.uri) : undefined;
    if (activeFolder) {
      const insideActiveFolder = choices.filter(
        (uri) => vscode.workspace.getWorkspaceFolder(uri)?.uri.toString() === activeFolder.uri.toString(),
      );
      if (insideActiveFolder.length === 1) {
        this.selectedDatabase = insideActiveFolder[0];
        return insideActiveFolder[0];
      }
    }

    return choices[0];
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
    const raw = JSON.parse(text) as unknown;
    const candidates = candidatesFromDatabase(raw);
    this.cache = { uri, mtime: stat.mtime, candidates };
    return candidates;
  }

  private configuredDatabaseUri(activeDocument?: vscode.TextDocument): vscode.Uri | undefined {
    const configuration = vscode.workspace.getConfiguration("tacroman", activeDocument?.uri);
    const configured = configuration.get<string>("databasePath", "").trim();
    if (!configured) {
      return undefined;
    }

    if (path.isAbsolute(configured)) {
      return vscode.Uri.file(configured);
    }

    const folder = activeDocument
      ? vscode.workspace.getWorkspaceFolder(activeDocument.uri)
      : vscode.workspace.workspaceFolders?.[0];
    if (!folder) {
      return undefined;
    }
    return vscode.Uri.joinPath(folder.uri, ...configured.split(/[\\/]+/));
  }

  private async discoverDatabases(): Promise<vscode.Uri[]> {
    const found = await vscode.workspace.findFiles(
      "**/acronyms.json",
      "**/{node_modules,.git,.venv,venv}/**",
      100,
    );
    return found.sort((a, b) => a.fsPath.localeCompare(b.fsPath));
  }
}
