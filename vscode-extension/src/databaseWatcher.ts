import * as path from "node:path";
import * as vscode from "vscode";
import { DatabaseManager } from "./databaseManager";
import {
  desktopIntegrationStatePath,
  outputPathFromIntegrationState,
  readDesktopIntegrationState,
  workspacePathFromIntegrationState,
} from "./desktopIntegration";
import { generateWorkspaceOutput } from "./texGenerator";
import { FRAGMENT_SUFFIX, MANIFEST_FILENAME, WorkspaceSnapshot } from "./workspace";

const RETRY_DELAYS = [0, 250, 500];

class ActiveWorkspaceWatcher implements vscode.Disposable {
  private readonly disposables: vscode.Disposable[] = [];
  private watcherDisposables: vscode.Disposable[] = [];
  private watchedPath = "";
  private reloadTimer: NodeJS.Timeout | undefined;
  private stateTimer: NodeJS.Timeout | undefined;
  private reconcileTimer: NodeJS.Timeout | undefined;
  private lastRevision = "";
  private lastWarning = "";
  private disposed = false;

  constructor(private readonly databases: DatabaseManager) {
    this.disposables.push(
      databases.onDidChangeDatabase(() => void this.rebind()),
      vscode.window.onDidChangeActiveTextEditor((editor) => {
        void this.databases.syncProjectOutput(editor?.document);
        void this.rebind();
      }),
    );
    const statePath = desktopIntegrationStatePath();
    const watcher = vscode.workspace.createFileSystemWatcher(
      new vscode.RelativePattern(path.dirname(statePath), path.basename(statePath)),
      false,
      false,
      false,
    );
    const changed = () => this.scheduleStateReload();
    this.disposables.push(
      watcher,
      watcher.onDidChange(changed),
      watcher.onDidCreate(changed),
      watcher.onDidDelete(changed),
    );
    this.reconcileTimer = setInterval(() => void this.reload("reconcile"), 5000);
    void this.start();
  }

  dispose(): void {
    this.disposed = true;
    if (this.reloadTimer) clearTimeout(this.reloadTimer);
    if (this.stateTimer) clearTimeout(this.stateTimer);
    if (this.reconcileTimer) clearInterval(this.reconcileTimer);
    this.clearWatchers();
    for (const disposable of this.disposables) disposable.dispose();
  }

  private clearWatchers(): void {
    for (const disposable of this.watcherDisposables) disposable.dispose();
    this.watcherDisposables = [];
  }

  private async start(): Promise<void> {
    await this.rebind();
    await this.reload("initial");
  }

  private async rebind(): Promise<void> {
    if (this.disposed) return;
    const workspacePath = workspacePathFromIntegrationState(await readDesktopIntegrationState()) ?? "";
    if (workspacePath === this.watchedPath) return;
    this.clearWatchers();
    this.watchedPath = workspacePath;
    if (!workspacePath) return;
    const onChange = () => this.scheduleReload();
    for (const pattern of [MANIFEST_FILENAME, `*${FRAGMENT_SUFFIX}`]) {
      const watcher = vscode.workspace.createFileSystemWatcher(
        new vscode.RelativePattern(workspacePath, pattern),
        false,
        false,
        false,
      );
      this.watcherDisposables.push(
        watcher,
        watcher.onDidChange(onChange),
        watcher.onDidCreate(onChange),
        watcher.onDidDelete(onChange),
      );
    }
  }

  private scheduleStateReload(): void {
    if (this.stateTimer) clearTimeout(this.stateTimer);
    this.stateTimer = setTimeout(() => {
      this.stateTimer = undefined;
      void (async () => {
        this.databases.sharedStateChanged();
        await this.rebind();
        await this.reload("state");
      })();
    }, 150);
  }

  private scheduleReload(): void {
    if (this.reloadTimer) clearTimeout(this.reloadTimer);
    this.reloadTimer = setTimeout(() => {
      this.reloadTimer = undefined;
      void this.reload("filesystem");
    }, 250);
  }

  private async loadWithRetry(): Promise<WorkspaceSnapshot | undefined> {
    let lastError: unknown;
    for (const delay of RETRY_DELAYS) {
      if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
      try {
        return await this.databases.reloadWorkspace();
      } catch (error) {
        lastError = error;
      }
    }
    throw lastError;
  }

  private async reload(reason: string): Promise<void> {
    if (this.disposed) return;
    try {
      const snapshot = await this.loadWithRetry();
      if (!snapshot) return;
      this.databases.setWorkspaceError(undefined);
      const changed = snapshot.revision !== this.lastRevision;
      this.lastRevision = snapshot.revision;
      if (!changed && reason === "reconcile") return;
      if (snapshot.exportBlocked) {
        const message = `TAcroMan: ${snapshot.conflicts.length} workspace conflict(s) block output generation.`;
        if (message !== this.lastWarning) vscode.window.showWarningMessage(message);
        this.lastWarning = message;
        return;
      }
      this.lastWarning = "";
      const outputPath = outputPathFromIntegrationState(await readDesktopIntegrationState());
      if (outputPath) await generateWorkspaceOutput(snapshot.entries, outputPath, snapshot.profile);
    } catch (error) {
      const message = `TAcroMan workspace error: ${error instanceof Error ? error.message : String(error)}`;
      this.databases.setWorkspaceError(message);
      if (message !== this.lastWarning) vscode.window.showWarningMessage(message);
      this.lastWarning = message;
    }
  }
}

export function registerDatabaseWatcher(context: vscode.ExtensionContext, databases: DatabaseManager): void {
  context.subscriptions.push(new ActiveWorkspaceWatcher(databases));
}
