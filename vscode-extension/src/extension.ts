import { spawn } from "node:child_process";
import * as vscode from "vscode";
import { findCompletionContext } from "./context";
import { matchesQuery } from "./database";
import { DatabaseManager } from "./databaseManager";
import { readDesktopLauncher } from "./desktopIntegration";
import { registerTAcroManSidebar } from "./sidebar";
import { registerCheckAcronymsCommand } from "./acronymCheckCommand";
import { registerDatabaseWatcher } from "./databaseWatcher";
import {
  buildPlainAcronymCompletionForms,
  buildPlainAcronymForms,
  findPlainAcronymOccurrences,
  findPlainTextCompletionMatches,
  PlainAcronymOccurrence,
  replacementForOccurrence,
} from "./plainText";

const LATEX_SELECTOR: vscode.DocumentSelector = { language: "latex", scheme: "file" };
const DIAGNOSTIC_SOURCE = "TAcroMan";
const DIAGNOSTIC_CODE = "tacroman.plain-acronym";
const DEFINITION_COMMANDS = ["acro", "acroplural", "newacronym", "DeclareAcronym"];

function cleanCommand(value: string, fallback: string): string {
  return (value || fallback).trim().replace(/^\\/, "") || fallback;
}

function configuredCommands(document: vscode.TextDocument): string[] {
  return vscode.workspace
    .getConfiguration("tacroman", document.uri)
    .get<string[]>("latexCommands", ["ac", "acp"])
    .map((item) => item.trim().replace(/^\\/, ""))
    .filter(Boolean);
}

function ignoredArgumentCommands(document: vscode.TextDocument): string[] {
  const configured = vscode.workspace
    .getConfiguration("tacroman", document.uri)
    .get<string[]>("ignoredArgumentCommands", []);
  return [...new Set([...configuredCommands(document), ...configured.map((item) => item.trim().replace(/^\\/, "")).filter(Boolean)])];
}

class TAcroManCompletionProvider implements vscode.CompletionItemProvider {
  constructor(private readonly databases: DatabaseManager) {}

  async provideCompletionItems(
    document: vscode.TextDocument,
    position: vscode.Position,
  ): Promise<vscode.CompletionItem[] | undefined> {
    const linePrefix = document.lineAt(position.line).text.slice(0, position.character);
    const context = findCompletionContext(linePrefix, configuredCommands(document));
    if (!context) {
      return undefined;
    }

    let candidates;
    try {
      candidates = await this.databases.loadCandidates(document);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      vscode.window.setStatusBarMessage(`TAcroMan: ${message}`, 5000);
      return [];
    }

    const maxItems = vscode.workspace.getConfiguration("tacroman", document.uri).get<number>("maxCompletionItems", 250);
    const range = new vscode.Range(
      new vscode.Position(position.line, context.startCharacter),
      position,
    );

    return candidates
      .filter((candidate) => matchesQuery(candidate, context.query))
      .slice(0, maxItems)
      .map((candidate, index) => {
        const item = new vscode.CompletionItem(candidate.key, vscode.CompletionItemKind.Reference);
        item.range = range;
        item.insertText = candidate.key;
        item.detail = candidate.long || candidate.short || candidate.commandId;
        const metadata = [
          candidate.short && candidate.short !== candidate.key ? `Short: ${candidate.short}` : "",
          candidate.long ? `Long: ${candidate.long}` : "",
          candidate.values.category ? `Category: ${candidate.values.category}` : "",
          candidate.values.note ? `Note: ${candidate.values.note}` : "",
        ].filter(Boolean);
        item.documentation = new vscode.MarkdownString(metadata.join("  \n"));
        item.filterText = [candidate.key, candidate.short, candidate.long, candidate.searchText].filter(Boolean).join(" ");
        item.sortText = String(index).padStart(6, "0");
        return item;
      });
  }
}

class TAcroManPlainTextCompletionProvider implements vscode.CompletionItemProvider {
  constructor(private readonly databases: DatabaseManager) {}

  async provideCompletionItems(
    document: vscode.TextDocument,
    position: vscode.Position,
  ): Promise<vscode.CompletionItem[] | undefined> {
    const configuration = vscode.workspace.getConfiguration("tacroman", document.uri);
    if (!configuration.get<boolean>("plainTextCompletion", true)) {
      return undefined;
    }

    let candidates;
    try {
      candidates = await this.databases.loadCandidates(document);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      vscode.window.setStatusBarMessage(`TAcroMan: ${message}`, 5000);
      return [];
    }
    if (!candidates.length) {
      return [];
    }

    const linePrefix = document.lineAt(position.line).text.slice(0, position.character);
    const inferPlurals = configuration.get<boolean>("inferPlainTextPlurals", true);
    const forms = buildPlainAcronymCompletionForms(candidates, { inferPlurals });
    const matches = findPlainTextCompletionMatches(linePrefix, forms, {
      ignoredArgumentCommands: ignoredArgumentCommands(document),
      definitionCommands: DEFINITION_COMMANDS,
      minCharacters: 2,
    });
    if (!matches.length) {
      return [];
    }

    const singularCommand = cleanCommand(configuration.get<string>("quickFixSingularCommand", "ac"), "ac");
    const pluralCommand = cleanCommand(configuration.get<string>("quickFixPluralCommand", "acp"), "acp");
    const maxItems = configuration.get<number>("maxCompletionItems", 250);
    const byKey = new Map(candidates.map((candidate) => [candidate.key.toLocaleLowerCase(), candidate]));

    return matches.slice(0, maxItems).map((match, index) => {
      const candidate = byKey.get(match.key.toLocaleLowerCase());
      const command = match.plural ? pluralCommand : singularCommand;
      const replacement = `\\${command}{${match.key}}`;
      const range = new vscode.Range(
        new vscode.Position(position.line, match.startCharacter),
        position,
      );
      const label: vscode.CompletionItemLabel = {
        label: match.plural ? (candidate?.values.short_plural || `${match.key}s`) : match.key,
        description: candidate?.long || match.text,
      };
      const item = new vscode.CompletionItem(label, vscode.CompletionItemKind.Reference);
      item.range = range;
      item.insertText = replacement;
      item.filterText = match.typedText;
      item.sortText = `${String(index).padStart(6, "0")}-${match.key.toLocaleLowerCase()}`;
      item.detail = `TAcroMan: replace with ${replacement}`;
      item.documentation = new vscode.MarkdownString([
        candidate?.short ? `Short: ${candidate.short}` : "",
        candidate?.long ? `Long: ${candidate.long}` : "",
        match.plural ? "Plural form" : "Singular form",
      ].filter(Boolean).join("  \n"));
      return item;
    });
  }
}

function rangeKey(range: vscode.Range): string {
  return `${range.start.line}:${range.start.character}-${range.end.line}:${range.end.character}`;
}

class PlainAcronymDiagnostics implements vscode.Disposable {
  private readonly collection = vscode.languages.createDiagnosticCollection("tacroman");
  private readonly disposables: vscode.Disposable[] = [];
  private readonly occurrences = new Map<string, Map<string, PlainAcronymOccurrence>>();
  private readonly updateTimers = new Map<string, NodeJS.Timeout>();

  constructor(private readonly databases: DatabaseManager) {
    this.disposables.push(
      this.collection,
      vscode.workspace.onDidOpenTextDocument((document) => this.schedule(document)),
      vscode.workspace.onDidChangeTextDocument((event) => this.schedule(event.document)),
      vscode.workspace.onDidCloseTextDocument((document) => this.clearDocument(document)),
      vscode.workspace.onDidChangeConfiguration((event) => {
        if (
          event.affectsConfiguration("tacroman.plainTextDiagnostics")
          || event.affectsConfiguration("tacroman.inferPlainTextPlurals")
          || event.affectsConfiguration("tacroman.ignoredArgumentCommands")
          || event.affectsConfiguration("tacroman.latexCommands")
          || event.affectsConfiguration("tacroman.quickFixSingularCommand")
          || event.affectsConfiguration("tacroman.quickFixPluralCommand")
        ) {
          this.refreshAll();
        }
      }),
      databases.onDidChangeDatabase(() => this.refreshAll()),
    );

    this.refreshAll();
  }

  dispose(): void {
    for (const timer of this.updateTimers.values()) {
      clearTimeout(timer);
    }
    this.updateTimers.clear();
    for (const disposable of this.disposables) {
      disposable.dispose();
    }
  }

  findOccurrence(uri: vscode.Uri, range: vscode.Range): PlainAcronymOccurrence | undefined {
    return this.occurrences.get(uri.toString())?.get(rangeKey(range));
  }

  private refreshAll(): void {
    for (const document of vscode.workspace.textDocuments) {
      this.schedule(document, 0);
    }
  }

  private clearDocument(document: vscode.TextDocument): void {
    const key = document.uri.toString();
    const timer = this.updateTimers.get(key);
    if (timer) {
      clearTimeout(timer);
      this.updateTimers.delete(key);
    }
    this.collection.delete(document.uri);
    this.occurrences.delete(key);
  }

  private schedule(document: vscode.TextDocument, delay = 200): void {
    if (document.languageId !== "latex" || document.uri.scheme !== "file") {
      return;
    }
    const key = document.uri.toString();
    const previous = this.updateTimers.get(key);
    if (previous) {
      clearTimeout(previous);
    }
    const timer = setTimeout(() => {
      this.updateTimers.delete(key);
      void this.update(document);
    }, delay);
    this.updateTimers.set(key, timer);
  }

  private async update(document: vscode.TextDocument): Promise<void> {
    const configuration = vscode.workspace.getConfiguration("tacroman", document.uri);
    if (!configuration.get<boolean>("plainTextDiagnostics", true)) {
      this.collection.delete(document.uri);
      this.occurrences.delete(document.uri.toString());
      return;
    }

    let candidates;
    try {
      candidates = await this.databases.loadCandidates(document);
    } catch {
      // Completion already reports parse/load problems interactively. Diagnostics
      // stay quiet so a temporarily invalid JSON save does not flood the editor.
      this.collection.delete(document.uri);
      this.occurrences.delete(document.uri.toString());
      return;
    }

    const forms = buildPlainAcronymForms(candidates, {
      inferPlurals: configuration.get<boolean>("inferPlainTextPlurals", true),
    });
    const ignoredCommands = ignoredArgumentCommands(document);
    const singularCommand = cleanCommand(configuration.get<string>("quickFixSingularCommand", "ac"), "ac");
    const pluralCommand = cleanCommand(configuration.get<string>("quickFixPluralCommand", "acp"), "acp");
    const diagnostics: vscode.Diagnostic[] = [];
    const documentOccurrences = new Map<string, PlainAcronymOccurrence>();

    for (let lineNumber = 0; lineNumber < document.lineCount; lineNumber += 1) {
      const text = document.lineAt(lineNumber).text;
      const found = findPlainAcronymOccurrences(text, forms, {
        ignoredArgumentCommands: ignoredCommands,
        definitionCommands: DEFINITION_COMMANDS,
      });
      for (const occurrence of found) {
        const range = new vscode.Range(
          new vscode.Position(lineNumber, occurrence.startCharacter),
          new vscode.Position(lineNumber, occurrence.endCharacter),
        );
        const command = occurrence.plural ? pluralCommand : singularCommand;
        const diagnostic = new vscode.Diagnostic(
          range,
          `Known TAcroMan acronym written as plain text. Use \\${command}{${occurrence.key}}.`,
          vscode.DiagnosticSeverity.Hint,
        );
        diagnostic.source = DIAGNOSTIC_SOURCE;
        diagnostic.code = DIAGNOSTIC_CODE;
        diagnostics.push(diagnostic);
        documentOccurrences.set(rangeKey(range), occurrence);
      }
    }

    this.occurrences.set(document.uri.toString(), documentOccurrences);
    this.collection.set(document.uri, diagnostics);
  }
}

class TAcroManCodeActionProvider implements vscode.CodeActionProvider {
  static readonly providedCodeActionKinds = [vscode.CodeActionKind.QuickFix];

  constructor(private readonly diagnostics: PlainAcronymDiagnostics) {}

  provideCodeActions(
    document: vscode.TextDocument,
    _range: vscode.Range | vscode.Selection,
    context: vscode.CodeActionContext,
  ): vscode.CodeAction[] {
    const configuration = vscode.workspace.getConfiguration("tacroman", document.uri);
    const singularCommand = cleanCommand(configuration.get<string>("quickFixSingularCommand", "ac"), "ac");
    const pluralCommand = cleanCommand(configuration.get<string>("quickFixPluralCommand", "acp"), "acp");
    const actions: vscode.CodeAction[] = [];

    for (const diagnostic of context.diagnostics) {
      if (diagnostic.source !== DIAGNOSTIC_SOURCE || diagnostic.code !== DIAGNOSTIC_CODE) {
        continue;
      }
      const occurrence = this.diagnostics.findOccurrence(document.uri, diagnostic.range);
      if (!occurrence) {
        continue;
      }
      const replacement = replacementForOccurrence(occurrence, singularCommand, pluralCommand);
      const action = new vscode.CodeAction(`Replace with ${replacement}`, vscode.CodeActionKind.QuickFix);
      action.diagnostics = [diagnostic];
      action.isPreferred = true;
      action.edit = new vscode.WorkspaceEdit();
      action.edit.replace(document.uri, diagnostic.range, replacement);
      actions.push(action);
    }
    return actions;
  }
}

async function openTAcroMan(databases: DatabaseManager): Promise<void> {
  const document = vscode.window.activeTextEditor?.document;
  const database = await databases.getDatabaseUri(document);
  if (!database) {
    const action = await vscode.window.showWarningMessage(
      "TAcroMan: No database is selected or discoverable.",
      "Select database",
    );
    if (action === "Select database") {
      await databases.selectDatabase();
    }
    return;
  }

  const configuration = vscode.workspace.getConfiguration("tacroman", document?.uri);
  const configuredExecutable = configuration.get<string>("executablePath", "").trim();
  const extraArguments = configuration.get<string[]>("launchArguments", []);

  let executable = configuredExecutable;
  let launcherArguments: string[] = [];

  if (!executable) {
    const desktopLauncher = await readDesktopLauncher();
    if (desktopLauncher) {
      executable = desktopLauncher.executable;
      launcherArguments = desktopLauncher.args;
    } else {
      executable = "tacroman";
    }
  }

  const args = [...launcherArguments, ...extraArguments, "--database", database.fsPath];

  try {
    const child = spawn(executable, args, {
      detached: true,
      stdio: "ignore",
      windowsHide: true,
    });
    child.on("error", (error) => {
      vscode.window.showErrorMessage(`TAcroMan could not be started: ${error.message}`);
    });
    child.unref();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    vscode.window.showErrorMessage(`TAcroMan could not be started: ${message}`);
  }
}

export function activate(context: vscode.ExtensionContext): void {
  const databases = new DatabaseManager(context);
  const diagnostics = new PlainAcronymDiagnostics(databases);
  context.subscriptions.push(databases, diagnostics);
  registerTAcroManSidebar(context, databases);
  registerDatabaseWatcher(context, databases);
  registerCheckAcronymsCommand(context, databases);

  context.subscriptions.push(
    vscode.languages.registerCompletionItemProvider(
      LATEX_SELECTOR,
      new TAcroManCompletionProvider(databases),
      "{",
    ),
    vscode.languages.registerCompletionItemProvider(
      LATEX_SELECTOR,
      new TAcroManPlainTextCompletionProvider(databases),
    ),
    vscode.languages.registerCodeActionsProvider(
      LATEX_SELECTOR,
      new TAcroManCodeActionProvider(diagnostics),
      { providedCodeActionKinds: TAcroManCodeActionProvider.providedCodeActionKinds },
    ),
    vscode.commands.registerCommand("tacroman.selectDatabase", () => databases.selectDatabase()),
    vscode.commands.registerCommand("tacroman.reload", () => {
      databases.clearCache();
      vscode.window.setStatusBarMessage("TAcroMan: database cache cleared", 3000);
    }),
    vscode.commands.registerCommand("tacroman.open", () => openTAcroMan(databases)),
  );
}

export function deactivate(): void {
  // VS Code disposes all subscriptions registered in the extension context.
}
