export interface CodeToken {
  content: string;
  color?: string;
  fontStyle?: number;
}

export interface CodeLine {
  text: string;
  tokens: CodeToken[];
}

export function codeTokenLines(source: string, tokens: CodeToken[][]): CodeLine[] {
  const lines = source.split("\n");
  return lines.map((text, index) => {
    const ending = index < lines.length - 1 ? "\n" : "";
    const cr = text.endsWith("\r") ? "\r" : "";
    return { text: text + ending, tokens: [...tokens[index] ?? [], ...(cr || ending ? [{ content: cr + ending }] : [])] };
  });
}
