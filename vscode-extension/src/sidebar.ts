import * as vscode from "vscode";
import { AcronymCandidate, matchesQuery } from "./database";
import { DatabaseManager } from "./databaseManager";

const VIEW_ID = "tacroman.acronymExplorer";
const FILTER_CONTEXT = "tacroman.sidebar.filterActive";

type GroupKind = "database" | "acronyms";

interface GroupNode {
  type: "group";
  group: GroupKind;
  label: string;
}

interface DatabaseNode {
  type: "database";
  uri: vscode.Uri;
}

interface ActionNode {
  type: "action";
  label: string;
  description?: string;
  command: string;
  icon: string;
}

export interface AcronymNode {
  type: "acronym";
  candidate: AcronymCandidate;
}

interface MessageNode {
  type: "message";
  label: string;
  icon: string;
}

type SidebarNode = GroupNode | DatabaseNode | ActionNode | AcronymNode | MessageNode;

interface SidebarSnapshot {
  database?: vscode.Uri;
  candidates: AcronymCandidate[];
  error?: string;
}

function acronymTooltip(candidate: AcronymCandidate): vscode.MarkdownString {
  const tooltip = new vscode.MarkdownString(undefined, true);
  tooltip.appendMarkdown(`**${candidate.short || candidate.key}**`);
  if (candidate.long) {
    tooltip.appendMarkdown(`  \n${candidate.long}`);
  }
  tooltip.appendMarkdown(`  \n\nKey: \`${candidate.key}\``);

  const shortPlural = candidate.values.short_plural?.trim();
  const longPlural = candidate.values.long_plural?.trim();
  if (shortPlural) {
    tooltip.appendMarkdown(`  \nShort plural: ${shortPlural}`);
  }
  if (longPlural) {
    tooltip.appendMarkdown(`  \nLong plural: ${longPlural}`);
  }
  return tooltip;
}

export class TAcroManSidebarProvider implements vscode.TreeDataProvider<SidebarNode>, vscode.Disposable {
  private readonly changedEmitter = new vscode.EventEmitter<SidebarNode | undefined | null | void>();
  private readonly disposables: vscode.Disposable[] = [];
  private snapshot: SidebarSnapshot | undefined;
  private filterQuery = "";

  readonly onDidChangeTreeData = this.changedEmitter.event;

  constructor(private readonly databases: DatabaseManager) {
    this.disposables.push(
      this.databases.onDidChangeDatabase(() => this.refresh()),
      vscode.window.onDidChangeActiveTextEditor(() => this.refresh()),
    );
  }

  dispose(): void {
    for (const disposable of this.disposables) {
      disposable.dispose();
    }
    this.changedEmitter.dispose();
  }

  refresh(): void {
    this.snapshot = undefined;
    this.changedEmitter.fire();
  }

  async setFilter(query: string): Promise<void> {
    this.filterQuery = query.trim();
    await vscode.commands.executeCommand("setContext", FILTER_CONTEXT, Boolean(this.filterQuery));
    this.refresh();
  }

  getFilter(): string {
    return this.filterQuery;
  }

  getTreeItem(element: SidebarNode): vscode.TreeItem {
    switch (element.type) {
      case "group": {
        const item = new vscode.TreeItem(element.label, vscode.TreeItemCollapsibleState.Expanded);
        item.contextValue = `tacroman.${element.group}Group`;
        item.iconPath = new vscode.ThemeIcon(element.group === "database" ? "database" : "symbol-key");
        return item;
      }
      case "database": {
        const item = new vscode.TreeItem(element.uri.fsPath, vscode.TreeItemCollapsibleState.None);
        item.contextValue = "tacroman.database";
        item.iconPath = new vscode.ThemeIcon("json");
        item.tooltip = element.uri.fsPath;
        item.command = {
          command: "vscode.open",
          title: "Open database",
          arguments: [element.uri],
        };
        return item;
      }
      case "action": {
        const item = new vscode.TreeItem(element.label, vscode.TreeItemCollapsibleState.None);
        item.contextValue = "tacroman.action";
        item.iconPath = new vscode.ThemeIcon(element.icon);
        item.description = element.description;
        item.command = {
          command: element.command,
          title: element.label,
        };
        return item;
      }
      case "acronym": {
        const candidate = element.candidate;
        const label = candidate.short || candidate.key;
        const item = new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.None);
        item.contextValue = "tacroman.acronym";
        item.iconPath = new vscode.ThemeIcon("symbol-key");
        item.description = candidate.long || (candidate.key !== label ? candidate.key : "");
        item.tooltip = acronymTooltip(candidate);
        return item;
      }
      case "message": {
        const item = new vscode.TreeItem(element.label, vscode.TreeItemCollapsibleState.None);
        item.contextValue = "tacroman.message";
        item.iconPath = new vscode.ThemeIcon(element.icon);
        return item;
      }
    }
  }

  async getChildren(element?: SidebarNode): Promise<SidebarNode[]> {
    const snapshot = await this.loadSnapshot();

    if (!element) {
      const filteredCount = this.filteredCandidates(snapshot.candidates).length;
      const suffix = this.filterQuery ? ` / ${snapshot.candidates.length}` : "";
      return [
        { type: "group", group: "database", label: "Database" },
        { type: "group", group: "acronyms", label: `Acronyms (${filteredCount}${suffix})` },
      ];
    }

    if (element.type !== "group") {
      return [];
    }

    if (element.group === "database") {
      const checkAcronyms: ActionNode = {
        type: "action",
        label: "Check current file for acronyms",
        description: "Review and replace detected short/long forms",
        command: "tacroman.checkAcronyms",
        icon: "checklist",
      };
      const openTAcroMan: ActionNode = {
        type: "action",
        label: "Open TAcroMan",
        description: "Add or edit acronyms",
        command: "tacroman.open",
        icon: "edit",
      };
      if (snapshot.error) {
        return [checkAcronyms, openTAcroMan, { type: "message", label: snapshot.error, icon: "error" }];
      }
      if (!snapshot.database) {
        return [
          checkAcronyms,
          openTAcroMan,
          { type: "message", label: "No TAcroMan database selected", icon: "warning" },
        ];
      }
      return [checkAcronyms, openTAcroMan, { type: "database", uri: snapshot.database }];
    }

    if (snapshot.error) {
      return [{ type: "message", label: "Acronyms could not be loaded", icon: "error" }];
    }

    const candidates = this.filteredCandidates(snapshot.candidates);
    if (!candidates.length) {
      return [{
        type: "message",
        label: this.filterQuery ? `No acronyms match “${this.filterQuery}”` : "No acronyms found",
        icon: "search",
      }];
    }
    return candidates.map((candidate) => ({ type: "acronym", candidate }));
  }

  private filteredCandidates(candidates: AcronymCandidate[]): AcronymCandidate[] {
    if (!this.filterQuery) {
      return candidates;
    }
    return candidates.filter((candidate) => matchesQuery(candidate, this.filterQuery));
  }

  private async loadSnapshot(): Promise<SidebarSnapshot> {
    if (this.snapshot) {
      return this.snapshot;
    }

    const document = vscode.window.activeTextEditor?.document;
    try {
      const database = await this.databases.getDatabaseUri(document);
      const candidates = database ? await this.databases.loadCandidates(document) : [];
      this.snapshot = { database, candidates };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.snapshot = { candidates: [], error: message };
    }
    return this.snapshot;
  }
}

async function insertAcronym(node: AcronymNode | undefined, plural: boolean): Promise<void> {
  if (!node || node.type !== "acronym") {
    return;
  }

  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document.languageId !== "latex") {
    vscode.window.showWarningMessage("TAcroMan: Open a LaTeX editor before inserting an acronym.");
    return;
  }

  const configuration = vscode.workspace.getConfiguration("tacroman", editor.document.uri);
  const command = configuration
    .get<string>(plural ? "quickFixPluralCommand" : "quickFixSingularCommand", plural ? "acp" : "ac")
    .trim()
    .replace(/^\\+/, "") || (plural ? "acp" : "ac");
  const replacement = `\\${command}{${node.candidate.key}}`;

  await editor.edit((builder) => {
    for (const selection of editor.selections) {
      builder.replace(selection, replacement);
    }
  });
}

export function registerTAcroManSidebar(
  context: vscode.ExtensionContext,
  databases: DatabaseManager,
): void {
  const provider = new TAcroManSidebarProvider(databases);
  const tree = vscode.window.createTreeView(VIEW_ID, {
    treeDataProvider: provider,
    showCollapseAll: true,
  });

  context.subscriptions.push(
    provider,
    tree,
    vscode.commands.registerCommand("tacroman.sidebar.search", async () => {
      const query = await vscode.window.showInputBox({
        title: "Filter TAcroMan acronyms",
        prompt: "Search short form, long form, key, category, or other stored values",
        value: provider.getFilter(),
        placeHolder: "e.g. AUV or autonomous underwater",
      });
      if (query !== undefined) {
        await provider.setFilter(query);
      }
    }),
    vscode.commands.registerCommand("tacroman.sidebar.clearFilter", () => provider.setFilter("")),
    vscode.commands.registerCommand("tacroman.insertAcronym", (node?: AcronymNode) => insertAcronym(node, false)),
    vscode.commands.registerCommand("tacroman.insertAcronymPlural", (node?: AcronymNode) => insertAcronym(node, true)),
  );

  void vscode.commands.executeCommand("setContext", FILTER_CONTEXT, false);
}
