import * as path from "node:path";
import * as vscode from "vscode";
import { DatabaseManager } from "./databaseManager";

/**
 * Watches the database that TAcroMan is actually using.
 *
 * DatabaseManager already watches JSON files inside the workspace. This
 * targeted watcher is deliberately bound to the resolved database URI so a
 * desktop TAcroMan database outside the current VS Code workspace is also
 * refreshed immediately.
 */
class ActiveDatabaseWatcher implements vscode.Disposable {
  private readonly disposables: vscode.Disposable[] = [];
  private watcherDisposables: vscode.Disposable[] = [];
  private watchedUri = "";
  private reloadTimer: NodeJS.Timeout | undefined;
  private disposed = false;

  constructor(private readonly databases: DatabaseManager) {
    this.disposables.push(
      databases.onDidChangeDatabase(() => void this.rebind()),
      vscode.window.onDidChangeActiveTextEditor(() => void this.rebind()),
      vscode.workspace.onDidChangeConfiguration((event) => {
        if (event.affectsConfiguration("tacroman.databasePath")) {
          void this.rebind();
        }
      }),
    );
    void this.rebind();
  }

  dispose(): void {
    this.disposed = true;
    if (this.reloadTimer) {
      clearTimeout(this.reloadTimer);
      this.reloadTimer = undefined;
    }
    this.clearWatcher();
    for (const disposable of this.disposables) {
      disposable.dispose();
    }
  }

  private clearWatcher(): void {
    for (const disposable of this.watcherDisposables) {
      disposable.dispose();
    }
    this.watcherDisposables = [];
  }

  private async rebind(): Promise<void> {
    if (this.disposed) {
      return;
    }

    const document = vscode.window.activeTextEditor?.document;
    let database: vscode.Uri | undefined;
    try {
      database = await this.databases.getDatabaseUri(document);
    } catch {
      database = undefined;
    }

    const next = database?.toString() ?? "";
    if (next === this.watchedUri) {
      return;
    }

    this.clearWatcher();
    this.watchedUri = next;

    if (!database || database.scheme !== "file") {
      return;
    }

    const directory = vscode.Uri.file(path.dirname(database.fsPath));
    const pattern = new vscode.RelativePattern(directory, path.basename(database.fsPath));
    const watcher = vscode.workspace.createFileSystemWatcher(pattern, false, false, false);
    const changed = () => this.scheduleReload();

    this.watcherDisposables = [
      watcher,
      watcher.onDidChange(changed),
      watcher.onDidCreate(changed),
      watcher.onDidDelete(changed),
    ];
  }

  private scheduleReload(): void {
    if (this.reloadTimer) {
      clearTimeout(this.reloadTimer);
    }

    // TAcroMan saves atomically, which can produce several file events in a
    // short burst. Debounce them into one cache refresh.
    this.reloadTimer = setTimeout(() => {
      this.reloadTimer = undefined;
      if (this.disposed) {
        return;
      }
      this.databases.clearCache();
      void this.rebind();
    }, 250);
  }
}

export function registerDatabaseWatcher(
  context: vscode.ExtensionContext,
  databases: DatabaseManager,
): void {
  context.subscriptions.push(new ActiveDatabaseWatcher(databases));
}
