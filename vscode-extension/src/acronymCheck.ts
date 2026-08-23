import { AcronymCandidate } from "./database";
import { buildPlainAcronymCompletionForms } from "./plainText";

export type AcronymOccurrenceSource = "short" | "long";

export interface DocumentAcronymOccurrence {
  key: string;
  text: string;
  plural: boolean;
  source: AcronymOccurrenceSource;
  start: number;
  end: number;
}

export interface DocumentAcronymScanOptions {
  inferPlurals?: boolean;
  ignoredArgumentCommands?: readonly string[];
  definitionCommands?: readonly string[];
}

const DEFAULT_DEFINITION_COMMANDS = ["acro", "acroplural", "newacronym", "DeclareAcronym"];
const VERBATIM_ENVIRONMENT_RE = /\\begin\{(verbatim\*?|Verbatim|lstlisting|minted|comment)\}[\s\S]*?\\end\{\1\}/g;
const COMMAND_RE = /\\([A-Za-z@]+)\*?/g;
const WORD_LIKE_RE = /[\p{L}\p{N}_]/u;

function isEscaped(text: string, index: number): boolean {
  let backslashes = 0;
  for (let cursor = index - 1; cursor >= 0 && text[cursor] === "\\"; cursor -= 1) {
    backslashes += 1;
  }
  return backslashes % 2 === 1;
}

function isWordLike(character: string | undefined): boolean {
  return Boolean(character && WORD_LIKE_RE.test(character));
}

function maskRange(chars: string[], start: number, endExclusive: number): void {
  for (let index = Math.max(0, start); index < Math.min(chars.length, endExclusive); index += 1) {
    if (chars[index] !== "\n" && chars[index] !== "\r") {
      chars[index] = " ";
    }
  }
}

function balancedGroupEnd(text: string, start: number, opener: string, closer: string): number | undefined {
  if (text[start] !== opener) {
    return undefined;
  }

  let depth = 0;
  for (let index = start; index < text.length; index += 1) {
    if (isEscaped(text, index)) {
      continue;
    }
    if (text[index] === opener) {
      depth += 1;
    } else if (text[index] === closer) {
      depth -= 1;
      if (depth === 0) {
        return index;
      }
    }
  }
  return undefined;
}

function maskedSourceText(
  text: string,
  ignoredArgumentCommands: readonly string[],
  definitionCommands: readonly string[],
): string {
  const chars = [...text];

  for (const match of text.matchAll(VERBATIM_ENVIRONMENT_RE)) {
    if (match.index !== undefined) {
      maskRange(chars, match.index, match.index + match[0].length);
    }
  }

  // Ignore LaTeX comments, but keep escaped percent signs (\%).
  let lineStart = 0;
  while (lineStart < text.length) {
    const newline = text.indexOf("\n", lineStart);
    const lineEnd = newline >= 0 ? newline : text.length;
    for (let index = lineStart; index < lineEnd; index += 1) {
      if (text[index] === "%" && !isEscaped(text, index)) {
        maskRange(chars, index, lineEnd);
        break;
      }
    }
    if (newline < 0) {
      break;
    }
    lineStart = newline + 1;
  }

  const ignored = new Set(
    [...ignoredArgumentCommands, ...definitionCommands].map((value) => value.trim().replace(/^\\+/, "").toLocaleLowerCase()),
  );

  for (const match of text.matchAll(COMMAND_RE)) {
    const command = match[1]?.toLocaleLowerCase();
    if (!command || !ignored.has(command) || match.index === undefined) {
      continue;
    }

    let cursor = match.index + match[0].length;
    while (cursor < text.length) {
      while (cursor < text.length && /\s/.test(text[cursor])) {
        cursor += 1;
      }
      const opener = text[cursor];
      if (opener !== "{" && opener !== "[") {
        break;
      }
      const closer = opener === "{" ? "}" : "]";
      const end = balancedGroupEnd(text, cursor, opener, closer);
      if (end === undefined) {
        break;
      }
      maskRange(chars, cursor, end + 1);
      cursor = end + 1;
    }
  }

  return chars.join("");
}

export function findDocumentAcronymOccurrences(
  text: string,
  candidates: readonly AcronymCandidate[],
  options: DocumentAcronymScanOptions = {},
): DocumentAcronymOccurrence[] {
  if (!text || !candidates.length) {
    return [];
  }

  const forms = buildPlainAcronymCompletionForms(candidates, {
    inferPlurals: options.inferPlurals ?? true,
  });
  const masked = maskedSourceText(
    text,
    options.ignoredArgumentCommands ?? [],
    options.definitionCommands ?? DEFAULT_DEFINITION_COMMANDS,
  );
  const lowerMasked = masked.toLocaleLowerCase();
  const found: DocumentAcronymOccurrence[] = [];

  for (const form of forms) {
    const needle = form.text.trim();
    if (!needle) {
      continue;
    }

    // Acronym short forms are case-sensitive to avoid turning ordinary lower-
    // case words into commands. Long forms are prose and therefore matched
    // case-insensitively (e.g. at the beginning of a sentence).
    const haystack = form.source === "short" ? masked : lowerMasked;
    const searchNeedle = form.source === "short" ? needle : needle.toLocaleLowerCase();
    let from = 0;

    while (from <= haystack.length - searchNeedle.length) {
      const start = haystack.indexOf(searchNeedle, from);
      if (start < 0) {
        break;
      }
      const end = start + searchNeedle.length;
      from = start + Math.max(1, searchNeedle.length);

      if (isWordLike(masked[start - 1]) || isWordLike(masked[end])) {
        continue;
      }
      if (masked[start - 1] === "\\") {
        continue;
      }

      found.push({
        key: form.key,
        text: text.slice(start, end),
        plural: form.plural,
        source: form.source,
        start,
        end,
      });
    }
  }

  // Prefer longer matches that begin at the same position (e.g. an explicit
  // plural or a long form) and suppress overlapping duplicate candidates.
  found.sort((a, b) =>
    a.start - b.start
    || (b.end - b.start) - (a.end - a.start)
    || Number(b.plural) - Number(a.plural)
    || (a.source === b.source ? 0 : a.source === "long" ? -1 : 1)
    || a.key.localeCompare(b.key, undefined, { sensitivity: "base" })
  );

  const result: DocumentAcronymOccurrence[] = [];
  for (const occurrence of found) {
    const previous = result[result.length - 1];
    if (previous && occurrence.start < previous.end) {
      continue;
    }
    result.push(occurrence);
  }
  return result;
}
