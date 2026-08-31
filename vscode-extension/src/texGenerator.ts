import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import * as path from "node:path";

interface Entry {
  commandId: string;
  values: Record<string, string>;
}

interface FieldDefinition {
  id: string;
  output_template?: unknown;
}

interface CommandDefinition {
  id: string;
  template: string;
  sort_by?: unknown;
  fields: FieldDefinition[];
}

interface RenderProfile {
  header?: unknown;
  footer?: unknown;
  separator?: unknown;
  sort_by?: unknown;
  escape_mode?: unknown;
  commands: CommandDefinition[];
}

const DEFAULT_PROFILE: RenderProfile = {
  header: "\\begin{acronym}\n",
  footer: "\n\\end{acronym}\n",
  separator: "\n",
  sort_by: "short",
  escape_mode: "none",
  commands: [
    {
      id: "acronym",
      template: "\\acro{[[short]]}{[[long]]}",
      fields: [{ id: "short" }, { id: "long" }, { id: "category" }, { id: "note" }],
    },
    {
      id: "acroplural",
      template: "\\acroplural{[[key]]}[[short_plural]]{[[long_plural]]}",
      sort_by: "key",
      fields: [
        { id: "key" },
        { id: "short_plural", output_template: "[[[value]]]" },
        { id: "long_plural" },
      ],
    },
  ],
};

function asString(value: unknown): string {
  return value === undefined || value === null ? "" : String(value);
}

function compareRenderValues(left: string, right: string): number {
  const fold = (value: string) => value.toLowerCase().replace(/ß/g, "ss").replace(/ς/g, "σ");
  return Buffer.from(fold(left), "utf8").compare(Buffer.from(fold(right), "utf8"));
}

function entriesFromDatabase(raw: unknown): Entry[] {
  let records: unknown[];
  if (Array.isArray(raw)) {
    records = raw;
  } else if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const object = raw as Record<string, unknown>;
    records = Array.isArray(object.entries) ? object.entries : Array.isArray(object.acronyms) ? object.acronyms : [];
  } else {
    records = [];
  }

  return records.flatMap((rawRecord) => {
    if (!rawRecord || typeof rawRecord !== "object" || Array.isArray(rawRecord)) {
      return [];
    }
    const record = rawRecord as Record<string, unknown>;
    const rawValues = record.values;
    if (rawValues && typeof rawValues === "object" && !Array.isArray(rawValues)) {
      return [{
        commandId: asString(record.command_id || "entry"),
        values: Object.fromEntries(Object.entries(rawValues).map(([key, value]) => [key, asString(value)])),
      }];
    }
    return [{
      commandId: asString(record.command_id || "acronym"),
      values: {
        short: asString(record.short),
        long: asString(record.long),
        category: asString(record.category),
        note: asString(record.note),
      },
    }];
  });
}

function renderProfile(raw: unknown): RenderProfile {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return DEFAULT_PROFILE;
  }
  const candidate = raw as Record<string, unknown>;
  if (!Array.isArray(candidate.commands)) {
    return DEFAULT_PROFILE;
  }
  const commands = candidate.commands.flatMap((rawCommand) => {
    if (!rawCommand || typeof rawCommand !== "object" || Array.isArray(rawCommand)) {
      return [];
    }
    const command = rawCommand as Record<string, unknown>;
    if (!asString(command.id) || typeof command.template !== "string" || !Array.isArray(command.fields)) {
      return [];
    }
    const fields = command.fields.flatMap((rawField) => {
      if (!rawField || typeof rawField !== "object" || Array.isArray(rawField)) {
        return [];
      }
      const field = rawField as Record<string, unknown>;
      return typeof field.id === "string" ? [{ id: field.id, output_template: field.output_template }] : [];
    });
    return [{ id: String(command.id), template: command.template, sort_by: command.sort_by, fields }];
  });
  return commands.length ? { ...candidate, commands } as RenderProfile : DEFAULT_PROFILE;
}

function escapeValue(value: string, mode: string): string {
  if (mode === "csv") {
    return /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
  }
  if (mode !== "latex") {
    return value;
  }
  const escapes: Record<string, string> = {
    "\\": "\\textbackslash{}", "&": "\\&", "%": "\\%", "$": "\\$", "#": "\\#",
    "_": "\\_", "{": "\\{", "}": "\\}", "~": "\\textasciitilde{}", "^": "\\textasciicircum{}",
  };
  return [...value].map((character) => escapes[character] ?? character).join("");
}

function identifier(value: string): string {
  const normalized = value.normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
  return normalized.replace(/[^A-Za-z0-9]+/g, "_").replace(/^_+|_+$/g, "").toLowerCase() || "entry";
}

function valuesForEntry(entry: Entry, command: CommandDefinition, mode: string): Record<string, string> {
  const values: Record<string, string> = {};
  for (const field of command.fields) {
    const rawValue = (entry.values[field.id] ?? "").trim();
    const template = typeof field.output_template === "string" ? field.output_template : "[[value]]";
    values[field.id] = rawValue ? template.replace(/\[\[value\]\]/g, escapeValue(rawValue, mode)) : "";
  }
  const seed = (entry.values.short || entry.values.key || Object.values(entry.values).find((value) => value.trim()) || entry.commandId).trim();
  values.id = escapeValue(entry.values.id?.trim() || identifier(seed), mode);
  values.command = escapeValue(entry.commandId, mode);
  return values;
}

export function renderGeneratedOutput(database: unknown, rawProfile?: unknown): string {
  const entries = entriesFromDatabase(database);
  const profile = renderProfile(rawProfile);
  const mode = asString(profile.escape_mode || "none");
  const lines: string[] = [];

  for (const command of profile.commands) {
    const group = entries.filter((entry) => entry.commandId === command.id);
    const sortBy = asString(command.sort_by || profile.sort_by || "none");
    if (sortBy !== "none") {
      group.sort((left, right) => {
        const leftValue = valuesForEntry(left, command, "none")[sortBy === "identifier" ? "id" : sortBy] ?? "";
        const rightValue = valuesForEntry(right, command, "none")[sortBy === "identifier" ? "id" : sortBy] ?? "";
        return compareRenderValues(leftValue, rightValue);
      });
    }
    for (const entry of group) {
      const values = valuesForEntry(entry, command, mode);
      lines.push(command.template.replace(/\[\[([A-Za-z][A-Za-z0-9_]*)\]\]/g, (token, key: string) => values[key] ?? token));
    }
  }

  return `${asString(profile.header)}${lines.join(asString(profile.separator ?? "\n"))}${asString(profile.footer)}`;
}

export async function generateWorkspaceOutput(
  entries: Array<{ uid?: string; commandId: string; values: Record<string, string> }>,
  outputPath: string,
  rawProfile: unknown,
): Promise<boolean> {
  const database = {
    entries: entries.map((entry) => ({
      uid: entry.uid,
      command_id: entry.commandId,
      values: entry.values,
    })),
  };
  const rendered = renderGeneratedOutput(database, rawProfile);
  try {
    if (await readFile(outputPath, "utf8") === rendered) return false;
  } catch {
    // Missing and temporarily unavailable output files are written atomically below.
  }
  await mkdir(path.dirname(outputPath), { recursive: true });
  const temporary = `${outputPath}.${process.pid}.${Date.now()}.tmp`;
  await writeFile(temporary, rendered, "utf8");
  await rename(temporary, outputPath);
  return true;
}
