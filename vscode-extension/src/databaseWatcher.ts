import { stat } from "node:fs/promises";
import * as path from "node:path";
import * as vscode from "vscode";
import { DatabaseManager } from "./databaseManager";
import {
  desktopIntegrationStatePath,
  outputPathFromIntegrationState,
  readDesktopIntegrationState,
} from "./desktopIntegration";
import { generateOutputFile } from "./texGenerator";

/** Watches both the per-user state and the selected database outside VS Code. */
class ActiveDatabaseWatcher implements vscode.Disposable {
  private readonly disposables: vscode.Disposable[] = [];
  private watcherDisposables: vscode.Disposable[] = [];
  private watchedUri = "";
  private reloadTimer: NodeJS.Timeout | undefined;
  private stateTimer: NodeJS.Timeout | undefined;
  private stateGenerationSignature = "";
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
    const statePattern = new vscode.RelativePattern(path.dirname(statePath), path.basename(statePath));
    const stateWatcher = vscode.workspace.createFileSystemWatcher(statePattern, false, false, false);
    const stateChanged = () => this.scheduleStateReload();
    this.disposables.push(
      stateWatcher,
      stateWatcher.onDidChange(stateChanged),
      stateWatcher.onDidCreate(stateChanged),
      stateWatcher.onDidDelete(stateChanged),
    );
    void this.start();
  }

  dispose(): void {
    this.disposed = true;
    if (this.reloadTimer) clearTimeout(this.reloadTimer);
    if (this.stateTimer) clearTimeout(this.stateTimer);
    this.clearWatcher();
    for (const disposable of this.disposables) disposable.dispose();
  }

  private clearWatcher(): void {
    for (const disposable of this.watcherDisposables) disposable.dispose();
    this.watcherDisposables = [];
  }

  private async start(): Promise<void> {
    await this.captureStateGenerationSignature();
    await this.rebind();
    await this.generateOutput(true);
  }

  private async rebind(): Promise<void> {
    if (this.disposed) return;
    let database: vscode.Uri | undefined;
    try {
      database = await this.databases.getDatabaseUri(vscode.window.activeTextEditor?.document);
    } catch {
      database = undefined;
    }

    const next = database?.toString() ?? "";
    if (next === this.watchedUri) return;
    this.clearWatcher();
    this.watchedUri = next;
    if (!database || database.scheme !== "file") return;

    const pattern = new vscode.RelativePattern(path.dirname(database.fsPath), path.basename(database.fsPath));
    const watcher = vscode.workspace.createFileSystemWatcher(pattern, false, false, false);
    const changed = () => this.scheduleDatabaseReload();
    this.watcherDisposables = [
      watcher,
      watcher.onDidChange(changed),
      watcher.onDidCreate(changed),
      watcher.onDidDelete(changed),
    ];
  }

  private scheduleStateReload(): void {
    if (this.stateTimer) clearTimeout(this.stateTimer);
    this.stateTimer = setTimeout(() => {
      this.stateTimer = undefined;
      if (this.disposed) return;
      void this.reloadSharedState();
    }, 150);
  }

  private async captureStateGenerationSignature(): Promise<void> {
    const state = await readDesktopIntegrationState();
    this.stateGenerationSignature = JSON.stringify([
      state?.databasePath,
      state?.outputPath,
      state?.renderProfile,
    ]);
  }

  private async reloadSharedState(): Promise<void> {
    const previous = this.stateGenerationSignature;
    await this.captureStateGenerationSignature();
    const generationTargetChanged = Boolean(previous) && previous !== this.stateGenerationSignature;
    this.databases.sharedStateChanged();
    await this.rebind();
    if (generationTargetChanged) await this.generateOutput(true);
  }

  private scheduleDatabaseReload(): void {
    if (this.reloadTimer) clearTimeout(this.reloadTimer);
    this.reloadTimer = setTimeout(() => {
      this.reloadTimer = undefined;
      if (this.disposed) return;
      this.databases.clearCache();
      void this.generateOutput(false);
    }, 250);
  }

  private async generateOutput(force: boolean): Promise<void> {
    try {
      const state = await readDesktopIntegrationState();
      const database = await this.databases.getDatabaseUri();
      const outputPath = outputPathFromIntegrationState(state);
      if (!database || !outputPath) return;

      if (!force) {
        const databaseStat = await stat(database.fsPath);
        try {
          const outputStat = await stat(outputPath);
          // The desktop app writes the database first and output immediately
          // afterwards. Do not replace its profile/table-order result.
          if (outputStat.mtimeMs >= databaseStat.mtimeMs) return;
        } catch {
          // A missing output is exactly what should trigger generation.
        }
      }

      await generateOutputFile(database.fsPath, outputPath, state?.renderProfile);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      vscode.window.showWarningMessage(`TAcroMan could not generate the output file: ${message}`);
    }
  }
}

export function registerDatabaseWatcher(context: vscode.ExtensionContext, databases: DatabaseManager): void {
  context.subscriptions.push(new ActiveDatabaseWatcher(databases));
}
