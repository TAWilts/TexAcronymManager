export interface CompletionContext {
  command: string;
  query: string;
  startCharacter: number;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function findCompletionContext(linePrefix: string, commands: readonly string[]): CompletionContext | null {
  if (!commands.length) {
    return null;
  }

  const alternatives = [...commands]
    .sort((a, b) => b.length - a.length)
    .map(escapeRegExp)
    .join("|");
  const expression = new RegExp(`\\\\(${alternatives})\\s*\\{([^{}]*)$`);
  const match = expression.exec(linePrefix);
  if (!match || match.index === undefined) {
    return null;
  }

  const query = match[2] ?? "";
  return {
    command: match[1],
    query,
    startCharacter: linePrefix.length - query.length,
  };
}
