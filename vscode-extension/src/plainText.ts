import { AcronymCandidate } from "./database";

export interface PlainAcronymForm {
  key: string;
  text: string;
  plural: boolean;
}

export interface PlainAcronymOccurrence extends PlainAcronymForm {
  startCharacter: number;
  endCharacter: number;
}

export interface PlainAcronymCompletionForm extends PlainAcronymForm {
  source: "short" | "long";
}

export interface PlainAcronymCompletionMatch extends PlainAcronymCompletionForm {
  startCharacter: number;
  typedText: string;
}

export interface PlainTextScanOptions {
  ignoredArgumentCommands?: readonly string[];
  definitionCommands?: readonly string[];
}

function uniqueForms(forms: PlainAcronymForm[]): PlainAcronymForm[] {
  const seen = new Set<string>();
  const result: PlainAcronymForm[] = [];
  for (const form of forms) {
    const marker = `${form.plural ? "p" : "s"}\u0000${form.text}`;
    if (!form.text || seen.has(marker)) {
      continue;
    }
    seen.add(marker);
    result.push(form);
  }
  // Plurals and otherwise longer forms must win before their singular prefix.
  return result.sort((a, b) => b.text.length - a.text.length || a.text.localeCompare(b.text));
}

export function buildPlainAcronymForms(
  candidates: readonly AcronymCandidate[],
  options: { inferPlurals?: boolean } = {},
): PlainAcronymForm[] {
  const inferPlurals = options.inferPlurals ?? true;
  const forms: PlainAcronymForm[] = [];
  for (const candidate of candidates) {
    const singular = (candidate.short || candidate.key).trim();
    if (!singular) {
      continue;
    }
    forms.push({ key: candidate.key, text: singular, plural: false });

    const explicitPlural = candidate.values.short_plural?.trim();
    const inferredPlural = inferPlurals && !explicitPlural ? `${singular}s` : "";
    const plural = explicitPlural || inferredPlural;
    if (plural && plural !== singular) {
      forms.push({ key: candidate.key, text: plural, plural: true });
    }
  }
  return uniqueForms(forms);
}


export function buildPlainAcronymCompletionForms(
  candidates: readonly AcronymCandidate[],
  options: { inferPlurals?: boolean } = {},
): PlainAcronymCompletionForm[] {
  const inferPlurals = options.inferPlurals ?? true;
  const forms: PlainAcronymCompletionForm[] = [];

  const add = (key: string, text: string, plural: boolean, source: "short" | "long") => {
    const cleaned = text.trim();
    if (cleaned) {
      forms.push({ key, text: cleaned, plural, source });
    }
  };

  for (const candidate of candidates) {
    const singularShort = (candidate.short || candidate.key).trim();
    const singularLong = candidate.long.trim();
    add(candidate.key, singularShort, false, "short");
    add(candidate.key, singularLong, false, "long");

    const explicitShortPlural = candidate.values.short_plural?.trim() || "";
    const inferredShortPlural = inferPlurals && !explicitShortPlural && singularShort ? `${singularShort}s` : "";
    add(candidate.key, explicitShortPlural || inferredShortPlural, true, "short");

    const explicitLongPlural = candidate.values.long_plural?.trim() || "";
    const inferredLongPlural = inferPlurals && !explicitLongPlural && singularLong ? `${singularLong}s` : "";
    add(candidate.key, explicitLongPlural || inferredLongPlural, true, "long");
  }

  const seen = new Set<string>();
  return forms.filter((form) => {
    const marker = `${form.key.toLocaleLowerCase()}\u0000${form.plural ? "p" : "s"}\u0000${form.source}\u0000${form.text.toLocaleLowerCase()}`;
    if (seen.has(marker)) {
      return false;
    }
    seen.add(marker);
    return true;
  });
}

function isEscaped(text: string, index: number): boolean {
  let backslashes = 0;
  for (let cursor = index - 1; cursor >= 0 && text[cursor] === "\\"; cursor -= 1) {
    backslashes += 1;
  }
  return backslashes % 2 === 1;
}

export function latexCommentStart(line: string): number {
  for (let index = 0; index < line.length; index += 1) {
    if (line[index] === "%" && !isEscaped(line, index)) {
      return index;
    }
  }
  return line.length;
}

function findClosingBrace(text: string, openingBrace: number): number {
  let depth = 0;
  for (let index = openingBrace; index < text.length; index += 1) {
    if (text[index] === "{" && !isEscaped(text, index)) {
      depth += 1;
    } else if (text[index] === "}" && !isEscaped(text, index)) {
      depth -= 1;
      if (depth === 0) {
        return index;
      }
    }
  }
  return text.length;
}

interface CharacterRange {
  start: number;
  end: number;
}

function ignoredFirstArgumentRanges(line: string, commands: ReadonlySet<string>): CharacterRange[] {
  if (!commands.size) {
    return [];
  }
  const ranges: CharacterRange[] = [];
  const expression = /\\([A-Za-z@]+)\*?\s*\{/g;
  for (let match = expression.exec(line); match; match = expression.exec(line)) {
    const command = match[1];
    if (!commands.has(command)) {
      continue;
    }
    const openingBrace = expression.lastIndex - 1;
    const closingBrace = findClosingBrace(line, openingBrace);
    ranges.push({ start: openingBrace + 1, end: closingBrace });
  }
  return ranges;
}

function lineContainsDefinitionCommand(line: string, commands: ReadonlySet<string>): boolean {
  if (!commands.size) {
    return false;
  }
  const expression = /\\([A-Za-z@]+)\*?\s*\{/g;
  for (let match = expression.exec(line); match; match = expression.exec(line)) {
    if (commands.has(match[1])) {
      return true;
    }
  }
  return false;
}

function isWordLike(character: string | undefined): boolean {
  return Boolean(character && /[\p{L}\p{N}_]/u.test(character));
}

function hasTokenBoundaries(line: string, start: number, end: number): boolean {
  return !isWordLike(line[start - 1]) && !isWordLike(line[end]);
}

function overlapsIgnoredRange(start: number, end: number, ranges: readonly CharacterRange[]): boolean {
  return ranges.some((range) => start < range.end && end > range.start);
}


export function replacementForOccurrence(
  occurrence: PlainAcronymOccurrence,
  singularCommand = "ac",
  pluralCommand = "acp",
): string {
  const command = occurrence.plural ? pluralCommand : singularCommand;
  return `\\${command}{${occurrence.key}}`;
}

export function findPlainAcronymOccurrences(
  line: string,
  forms: readonly PlainAcronymForm[],
  options: PlainTextScanOptions = {},
): PlainAcronymOccurrence[] {
  const visibleEnd = latexCommentStart(line);
  const visible = line.slice(0, visibleEnd);
  const definitionCommands = new Set(options.definitionCommands ?? ["acro", "acroplural", "newacronym", "DeclareAcronym"]);
  if (lineContainsDefinitionCommand(visible, definitionCommands)) {
    return [];
  }

  const ignoredCommands = new Set(options.ignoredArgumentCommands ?? []);
  const ignoredRanges = ignoredFirstArgumentRanges(visible, ignoredCommands);
  const occupied: CharacterRange[] = [];
  const occurrences: PlainAcronymOccurrence[] = [];

  for (const form of forms) {
    let start = visible.indexOf(form.text);
    while (start !== -1) {
      const end = start + form.text.length;
      if (
        hasTokenBoundaries(visible, start, end)
        && !overlapsIgnoredRange(start, end, ignoredRanges)
        && !overlapsIgnoredRange(start, end, occupied)
      ) {
        occurrences.push({ ...form, startCharacter: start, endCharacter: end });
        occupied.push({ start, end });
      }
      start = visible.indexOf(form.text, start + Math.max(1, form.text.length));
    }
  }

  return occurrences.sort((a, b) => a.startCharacter - b.startCharacter || b.text.length - a.text.length);
}


function cursorInsideIgnoredRange(position: number, ranges: readonly CharacterRange[]): boolean {
  return ranges.some((range) => position >= range.start && position <= range.end);
}

function validCompletionStart(linePrefix: string, start: number): boolean {
  if (start < 0 || start >= linePrefix.length) {
    return false;
  }
  const previous = linePrefix[start - 1];
  return !isWordLike(previous) && previous !== "\\";
}

export function findPlainTextCompletionMatches(
  linePrefix: string,
  forms: readonly PlainAcronymCompletionForm[],
  options: PlainTextScanOptions & { minCharacters?: number } = {},
): PlainAcronymCompletionMatch[] {
  const minCharacters = Math.max(1, options.minCharacters ?? 2);
  const commentStart = latexCommentStart(linePrefix);
  if (commentStart < linePrefix.length) {
    return [];
  }

  const definitionCommands = new Set(options.definitionCommands ?? ["acro", "acroplural", "newacronym", "DeclareAcronym"]);
  if (lineContainsDefinitionCommand(linePrefix, definitionCommands)) {
    return [];
  }

  const ignoredCommands = new Set(options.ignoredArgumentCommands ?? []);
  const ignoredRanges = ignoredFirstArgumentRanges(linePrefix, ignoredCommands);
  if (cursorInsideIgnoredRange(linePrefix.length, ignoredRanges)) {
    return [];
  }

  const lowerPrefix = linePrefix.toLocaleLowerCase();
  const bestByKey = new Map<string, PlainAcronymCompletionMatch>();

  for (const form of forms) {
    const lowerForm = form.text.toLocaleLowerCase();
    const maxLength = Math.min(lowerForm.length, lowerPrefix.length);
    let match: PlainAcronymCompletionMatch | undefined;

    for (let length = maxLength; length >= minCharacters; length -= 1) {
      const start = linePrefix.length - length;
      if (!validCompletionStart(linePrefix, start)) {
        continue;
      }
      const typed = lowerPrefix.slice(start);
      if (!lowerForm.startsWith(typed)) {
        continue;
      }
      match = {
        ...form,
        startCharacter: start,
        typedText: linePrefix.slice(start),
      };
      break;
    }

    if (!match) {
      continue;
    }

    const key = form.key.toLocaleLowerCase();
    const previous = bestByKey.get(key);
    if (
      !previous
      || match.typedText.length > previous.typedText.length
      || (match.typedText.length === previous.typedText.length && !match.plural && previous.plural)
      || (match.typedText.length === previous.typedText.length && match.source === "short" && previous.source === "long")
    ) {
      bestByKey.set(key, match);
    }
  }

  return [...bestByKey.values()].sort((a, b) =>
    b.typedText.length - a.typedText.length
    || Number(b.plural) - Number(a.plural)
    || a.key.localeCompare(b.key, undefined, { sensitivity: "base" })
  );
}
