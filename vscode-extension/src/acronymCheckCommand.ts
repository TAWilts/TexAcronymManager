import * as vscode from "vscode";
import { DatabaseManager } from "./databaseManager";
import { findDocumentAcronymOccurrences } from "./acronymCheck";

const DEFINITION_COMMANDS = ["acro", "acroplural", "newacronym", "DeclareAcronym"];

type ReviewAction = "replace" | "skip" | "stop";

interface ReviewItem extends vscode.QuickPickItem {
  action: ReviewAction;
}

function cleanCommand(value: string, fallback: string): string {
  return (value || fallback).trim().replace(/^\\+/, "") || fallback;
}

function ignoredArgumentCommands(document: vscode.TextDocument): string[] {
  const configuration = vscode.workspace.getConfiguration("tacroman", document.uri);
  const acronymCommands = configuration
    .get<string[]>("latexCommands", ["ac", "acp"])
    .map((value) => value.trim().replace(/^\\+/, ""))
    .filter(Boolean);
  const configured = configuration
    .get<string[]>("ignoredArgumentCommands", [])
    .map((value) => value.trim().replace(/^\\+/, ""))
    .filter(Boolean);
  return [...new Set([...acronymCommands, ...configured])];
}

async function checkCurrentFile(databases: DatabaseManager): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document.languageId !== "latex" || editor.document.uri.scheme !== "file") {
    vscode.window.showWarningMessage("TAcroMan: Open a local LaTeX file before checking for acronyms.");
    return;
  }

  const document = editor.document;
  let candidates;
  try {
    candidates = await databases.loadCandidates(document);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    vscode.window.showErrorMessage(`TAcroMan: Could not load the workspace: ${message}`);
    return;
  }

  if (!candidates.length) {
    vscode.window.showInformationMessage("TAcroMan: No conflict-free acronyms are available in the selected workspace.");
    return;
  }

  const configuration = vscode.workspace.getConfiguration("tacroman", document.uri);
  const inferPlurals = configuration.get<boolean>("inferPlainTextPlurals", true);
  const singularCommand = cleanCommand(configuration.get<string>("quickFixSingularCommand", "ac"), "ac");
  const pluralCommand = cleanCommand(configuration.get<string>("quickFixPluralCommand", "acp"), "acp");
  const ignoredCommands = ignoredArgumentCommands(document);

  let cursorOffset = 0;
  let replaced = 0;
  let skipped = 0;
  let stopped = false;

  while (true) {
    const currentText = document.getText();
    const occurrences = findDocumentAcronymOccurrences(currentText, candidates, {
      inferPlurals,
      ignoredArgumentCommands: ignoredCommands,
      definitionCommands: DEFINITION_COMMANDS,
    });
    const occurrence = occurrences.find((item) => item.start >= cursorOffset);
    if (!occurrence) {
      break;
    }

    const range = new vscode.Range(
      document.positionAt(occurrence.start),
      document.positionAt(occurrence.end),
    );
    editor.selection = new vscode.Selection(range.start, range.end);
    editor.revealRange(range, vscode.TextEditorRevealType.InCenterIfOutsideViewport);

    const command = occurrence.plural ? pluralCommand : singularCommand;
    const replacement = `\\${command}{${occurrence.key}}`;
    const line = range.start.line + 1;
    const remaining = occurrences.filter((item) => item.start >= cursorOffset).length;

    const choice = await vscode.window.showQuickPick<ReviewItem>(
      [
        {
          label: `$(replace) Replace with ${replacement}`,
          description: `${occurrence.source} form · line ${line}`,
          detail: `Found “${occurrence.text}” (${occurrence.key})`,
          action: "replace",
        },
        {
          label: "$(debug-step-over) Skip this occurrence",
          description: `Leave “${occurrence.text}” unchanged`,
          action: "skip",
        },
        {
          label: "$(stop-circle) Stop checking",
          description: "Keep all remaining occurrences unchanged",
          action: "stop",
        },
      ],
      {
        title: `TAcroMan: Check for acronyms (${remaining} remaining)`,
        placeHolder: `Review “${occurrence.text}” → ${replacement}`,
        ignoreFocusOut: true,
      },
    );

    if (!choice || choice.action === "stop") {
      stopped = true;
      break;
    }

    if (choice.action === "skip") {
      skipped += 1;
      cursorOffset = occurrence.end;
      continue;
    }

    const changed = await editor.edit((builder) => builder.replace(range, replacement));
    if (!changed) {
      vscode.window.showErrorMessage("TAcroMan: The acronym replacement could not be applied.");
      stopped = true;
      break;
    }
    replaced += 1;
    cursorOffset = occurrence.start + replacement.length;
  }

  // Clear the temporary review selection after the scan.
  const finalPosition = document.positionAt(Math.min(cursorOffset, document.getText().length));
  editor.selection = new vscode.Selection(finalPosition, finalPosition);

  const suffix = stopped ? " Check stopped." : " Check complete.";
  vscode.window.showInformationMessage(
    `TAcroMan: ${replaced} replaced, ${skipped} skipped.${suffix}`,
  );
}

export function registerCheckAcronymsCommand(
  context: vscode.ExtensionContext,
  databases: DatabaseManager,
): void {
  context.subscriptions.push(
    vscode.commands.registerCommand("tacroman.checkAcronyms", () => checkCurrentFile(databases)),
  );
}
