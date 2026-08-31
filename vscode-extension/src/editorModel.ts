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

function objectValue(raw: unknown): Record<string, unknown> | undefined {
  return raw && typeof raw === "object" && !Array.isArray(raw)
    ? raw as Record<string, unknown>
    : undefined;
}

function nonEmptyString(raw: unknown): string | undefined {
  return typeof raw === "string" && raw.trim() ? raw.trim() : undefined;
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
