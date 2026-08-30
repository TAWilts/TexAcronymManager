import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import * as path from "node:path";

export interface EditorField {
  id: string;
  label: string;
  required: boolean;
  multiline: boolean;
  comparisonGroup?: string;
}

export interface EditorCommand {
  id: string;
  label: string;
  description: string;
  fields: EditorField[];
}

export interface EditorProfile {
  id: string;
  name: string;
  commands: EditorCommand[];
}

export interface EditorEntry {
  uid: string;
  commandId: string;
  values: Record<string, string>;
}

export interface EditorDatabase {
  entries: EditorEntry[];
  revision: string;
}

export interface SaveEntryMutation {
  kind: "save";
  uid?: string;
  commandId: string;
  values: Record<string, string>;
}

export interface DeleteEntryMutation {
  kind: "delete";
  uid: string;
}

export type EditorMutation = SaveEntryMutation | DeleteEntryMutation;

export class DatabaseConflictError extends Error {
  constructor() {
    super("The database changed outside this editor. Reload it before saving again.");
    this.name = "DatabaseConflictError";
  }
}

function objectValue(raw: unknown): Record<string, unknown> | undefined {
  return raw && typeof raw === "object" && !Array.isArray(raw)
    ? raw as Record<string, unknown>
    : undefined;
}

function nonEmptyString(raw: unknown): string | undefined {
  return typeof raw === "string" && raw.trim() ? raw.trim() : undefined;
}

function stringValues(raw: unknown): Record<string, string> {
  const object = objectValue(raw);
  if (!object) return {};
  return Object.fromEntries(
    Object.entries(object).map(([key, value]) => [key, value === null || value === undefined ? "" : String(value)]),
  );
}

export function editorProfileFromRaw(raw: unknown): EditorProfile | undefined {
  const profile = objectValue(raw);
  if (!profile || !Array.isArray(profile.commands)) return undefined;

  const commands = profile.commands.flatMap((rawCommand): EditorCommand[] => {
    const command = objectValue(rawCommand);
    const id = nonEmptyString(command?.id);
    if (!command || !id || !Array.isArray(command.fields)) return [];
    const fields = command.fields.flatMap((rawField): EditorField[] => {
      const field = objectValue(rawField);
      const fieldId = nonEmptyString(field?.id);
      if (!field || !fieldId) return [];
      return [{
        id: fieldId,
        label: nonEmptyString(field.label) ?? fieldId,
        required: field.required === true,
        multiline: field.multiline === true,
        comparisonGroup: nonEmptyString(field.comparison_group),
      }];
    });
    if (!fields.length) return [];
    return [{
      id,
      label: nonEmptyString(command.label) ?? id,
      description: nonEmptyString(command.description) ?? "",
      fields,
    }];
  });
  if (!commands.length) return undefined;
  return {
    id: nonEmptyString(profile.id) ?? "profile",
    name: nonEmptyString(profile.name) ?? "TAcroMan",
    commands,
  };
}

function recordsFromRawDatabase(raw: unknown): unknown[] {
  if (Array.isArray(raw)) return raw;
  const database = objectValue(raw);
  if (database && Array.isArray(database.entries)) return database.entries;
  if (database && Array.isArray(database.acronyms)) return database.acronyms;
  throw new Error("The TAcroMan database must contain an entries array.");
}

export function editorEntriesFromDatabase(raw: unknown): EditorEntry[] {
  return recordsFromRawDatabase(raw).flatMap((rawRecord): EditorEntry[] => {
    const record = objectValue(rawRecord);
    if (!record) return [];
    const valuesObject = objectValue(record.values);
    const values = valuesObject
      ? stringValues(valuesObject)
      : stringValues({
        short: record.short,
        long: record.long,
        category: record.category,
        note: record.note,
      });
    return [{
      uid: nonEmptyString(record.uid) ?? randomUUID(),
      commandId: nonEmptyString(record.command_id) ?? "acronym",
      values,
    }];
  });
}

function normalizedComparison(value: string): string {
  return value.normalize("NFKC").trim().replace(/\s+/g, " ").toLocaleLowerCase();
}

export function validateEditorEntry(
  candidate: EditorEntry,
  entries: readonly EditorEntry[],
  profile: EditorProfile,
): string[] {
  const command = profile.commands.find((item) => item.id === candidate.commandId);
  if (!command) return [`Unknown command type: ${candidate.commandId}`];

  const errors: string[] = [];
  for (const field of command.fields) {
    const value = candidate.values[field.id] ?? "";
    if (field.required && !value.trim()) {
      errors.push(`${field.label} is required.`);
    }
    if (!field.multiline && /[\r\n]/.test(value)) {
      errors.push(`${field.label} must not contain a line break.`);
    }
    if (!field.comparisonGroup || !value.trim()) continue;

    const normalized = normalizedComparison(value);
    const duplicate = entries.some((entry) => {
      if (entry.uid === candidate.uid || entry.commandId !== candidate.commandId) return false;
      const existingCommand = profile.commands.find((item) => item.id === entry.commandId);
      return existingCommand?.fields.some((existingField) =>
        existingField.comparisonGroup === field.comparisonGroup
        && normalizedComparison(entry.values[existingField.id] ?? "") === normalized
      );
    });
    if (duplicate) errors.push(`${field.label} already exists for this command type.`);
  }
  return [...new Set(errors)];
}

function revisionFor(content: string): string {
  return createHash("sha256").update(content).digest("hex");
}

function serializeEntries(entries: readonly EditorEntry[]): string {
  return `${JSON.stringify({
    schema_version: 2,
    entries: entries.map((entry) => ({
      uid: entry.uid,
      command_id: entry.commandId,
      values: entry.values,
    })),
  }, null, 2)}\n`;
}

export async function readEditorDatabase(databasePath: string): Promise<EditorDatabase> {
  const content = await readFile(databasePath, "utf8");
  return {
    entries: editorEntriesFromDatabase(JSON.parse(content) as unknown),
    revision: revisionFor(content),
  };
}

export async function mutateEditorDatabase(
  databasePath: string,
  expectedRevision: string,
  mutation: EditorMutation,
  profile: EditorProfile,
): Promise<EditorDatabase> {
  const currentContent = await readFile(databasePath, "utf8");
  if (revisionFor(currentContent) !== expectedRevision) throw new DatabaseConflictError();

  let entries = editorEntriesFromDatabase(JSON.parse(currentContent) as unknown);
  if (mutation.kind === "delete") {
    if (!entries.some((entry) => entry.uid === mutation.uid)) {
      throw new Error("The selected entry no longer exists.");
    }
    entries = entries.filter((entry) => entry.uid !== mutation.uid);
  } else {
    const uid = mutation.uid ?? randomUUID();
    const candidate: EditorEntry = {
      uid,
      commandId: mutation.commandId,
      values: { ...mutation.values },
    };
    const errors = validateEditorEntry(candidate, entries, profile);
    if (errors.length) throw new Error(errors.join("\n"));
    const existing = entries.findIndex((entry) => entry.uid === uid);
    if (existing >= 0) entries[existing] = candidate;
    else entries.push(candidate);
  }

  const content = serializeEntries(entries);
  await mkdir(path.dirname(databasePath), { recursive: true });
  const temporary = `${databasePath}.${process.pid}.${Date.now()}.tmp`;
  await writeFile(temporary, content, "utf8");
  await rename(temporary, databasePath);
  return { entries, revision: revisionFor(content) };
}
