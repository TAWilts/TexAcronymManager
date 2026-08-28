export interface TAcroManRecord {
  uid?: string;
  command_id?: string;
  values?: Record<string, unknown>;
  short?: unknown;
  long?: unknown;
  category?: unknown;
  note?: unknown;
}

export interface AcronymCandidate {
  key: string;
  short: string;
  long: string;
  commandId: string;
  values: Record<string, string>;
  searchText: string;
}

function asString(value: unknown): string {
  return value === undefined || value === null ? "" : String(value);
}

function normaliseRecord(record: TAcroManRecord): { commandId: string; values: Record<string, string> } {
  if (record.values && typeof record.values === "object" && !Array.isArray(record.values)) {
    const values: Record<string, string> = {};
    for (const [key, value] of Object.entries(record.values)) {
      values[key] = asString(value);
    }
    return {
      commandId: asString(record.command_id || "entry"),
      values,
    };
  }

  return {
    commandId: asString(record.command_id || "acronym"),
    values: {
      short: asString(record.short),
      long: asString(record.long),
      category: asString(record.category),
      note: asString(record.note),
    },
  };
}

export function recordsFromDatabase(raw: unknown): TAcroManRecord[] {
  if (Array.isArray(raw)) {
    return raw.filter((item): item is TAcroManRecord => Boolean(item) && typeof item === "object" && !Array.isArray(item));
  }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("The TAcroMan database must contain a JSON object or array.");
  }

  const object = raw as Record<string, unknown>;
  const records = Array.isArray(object.entries)
    ? object.entries
    : Array.isArray(object.acronyms)
      ? object.acronyms
      : null;

  if (!records) {
    throw new Error("No TAcroMan entries were found in the JSON database.");
  }
  return records.filter((item): item is TAcroManRecord => Boolean(item) && typeof item === "object" && !Array.isArray(item));
}

function firstNonEmpty(values: Record<string, string>, fields: string[]): string {
  for (const field of fields) {
    const value = values[field]?.trim();
    if (value) {
      return value;
    }
  }
  return "";
}

function deriveKey(values: Record<string, string>): string {
  return firstNonEmpty(values, ["short", "key", "id", "label"]);
}

function deriveShort(values: Record<string, string>, key: string): string {
  return firstNonEmpty(values, ["short", "key", "id"]) || key;
}

function deriveLong(values: Record<string, string>): string {
  return firstNonEmpty(values, ["long", "description", "name"]);
}

export function candidatesFromDatabase(raw: unknown): AcronymCandidate[] {
  const records = recordsFromDatabase(raw);
  const candidates = new Map<string, AcronymCandidate>();

  for (const record of records) {
    const { commandId, values } = normaliseRecord(record);
    const key = deriveKey(values);
    if (!key) {
      continue;
    }

    const short = deriveShort(values, key);
    const long = deriveLong(values);
    const allValues = Object.values(values).filter(Boolean);
    const existing = candidates.get(key.toLocaleLowerCase());

    if (!existing) {
      candidates.set(key.toLocaleLowerCase(), {
        key,
        short,
        long,
        commandId,
        values: { ...values },
        searchText: [key, short, long, commandId, ...allValues].filter(Boolean).join(" "),
      });
      continue;
    }

    for (const [field, value] of Object.entries(values)) {
      if (value && !existing.values[field]) {
        existing.values[field] = value;
      }
    }
    // A regular acronym record is more descriptive than a plural/helper
    // record. Prefer its singular display values regardless of JSON order.
    if (values.short?.trim()) {
      existing.short = values.short.trim();
    }
    if (values.long?.trim()) {
      existing.long = values.long.trim();
    } else if (!existing.long && long) {
      existing.long = long;
    }
    existing.searchText = [
      existing.searchText,
      commandId,
      ...Object.values(values),
    ].filter(Boolean).join(" ");
  }

  return [...candidates.values()].sort((a, b) => a.key.localeCompare(b.key, undefined, { sensitivity: "base" }));
}

export function matchesQuery(candidate: AcronymCandidate, query: string): boolean {
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) {
    return true;
  }
  const haystack = candidate.searchText.toLocaleLowerCase();
  return terms.every((term) => haystack.includes(term));
}

function queryMatchRank(candidate: AcronymCandidate, query: string): number {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  if (!normalizedQuery) {
    return 0;
  }

  const key = candidate.key.toLocaleLowerCase();
  const short = candidate.short.toLocaleLowerCase();
  const long = candidate.long.toLocaleLowerCase();
  const otherValues = Object.entries(candidate.values)
    .filter(([field]) => field !== "short" && field !== "long")
    .map(([, value]) => value.toLocaleLowerCase());

  if (key === normalizedQuery) {
    return 0;
  }
  if (short === normalizedQuery) {
    return 1;
  }
  if (key.startsWith(normalizedQuery)) {
    return 2;
  }
  if (short.startsWith(normalizedQuery)) {
    return 3;
  }
  if (long.startsWith(normalizedQuery)) {
    return 4;
  }
  if (otherValues.some((value) => value.startsWith(normalizedQuery))) {
    return 5;
  }
  if (key.includes(normalizedQuery)) {
    return 6;
  }
  if (short.includes(normalizedQuery)) {
    return 7;
  }
  if (long.includes(normalizedQuery)) {
    return 8;
  }
  return 9;
}

/**
 * Sort matching candidates by how directly they match a completion query.
 * An exact acronym is always offered before entries which merely mention the
 * same text in their long form or metadata.
 */
export function rankCandidatesForQuery(
  candidates: readonly AcronymCandidate[],
  query: string,
): AcronymCandidate[] {
  return [...candidates].sort((a, b) =>
    queryMatchRank(a, query) - queryMatchRank(b, query)
    || a.key.localeCompare(b.key, undefined, { sensitivity: "base" })
  );
}
