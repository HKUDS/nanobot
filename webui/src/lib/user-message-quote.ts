interface ParsedUserMessageQuote {
  quotedContext: string | null;
  content: string;
}

const QUOTED_CONTEXT_MARKER = "> [!QUOTE]";

function normalizeNewlines(value: string): string {
  return value.replace(/\r\n?/g, "\n");
}

export function formatQuotedUserMessage(content: string, quotedContext?: string | null): string {
  const body = content.trim();
  const quote = normalizeNewlines(quotedContext ?? "").trim();
  if (!quote || body.startsWith("/")) return body;

  const blockquote = quote
    .split("\n")
    .map((line) => line ? `> ${line}` : ">")
    .join("\n");
  const quotedMessage = `${QUOTED_CONTEXT_MARKER}\n${blockquote}`;
  return body ? `${quotedMessage}\n\n${body}` : quotedMessage;
}

export function parseQuotedUserMessage(content: string): ParsedUserMessageQuote {
  if (!content.startsWith(QUOTED_CONTEXT_MARKER)) {
    return { quotedContext: null, content };
  }
  const normalized = normalizeNewlines(content);
  const quoteStart = QUOTED_CONTEXT_MARKER.length + 1;
  if (!normalized.startsWith(`${QUOTED_CONTEXT_MARKER}\n`)) {
    return { quotedContext: null, content };
  }
  const separatorIndex = normalized.indexOf("\n\n", quoteStart);
  const quoteBlock =
    separatorIndex === -1
      ? normalized.slice(quoteStart)
      : normalized.slice(quoteStart, separatorIndex);
  const quoteLines = quoteBlock.split("\n");
  if (
    quoteLines.length === 0
    || quoteLines.some((line) => line !== ">" && !line.startsWith("> "))
  ) {
    return { quotedContext: null, content };
  }

  const quotedContext = quoteLines
    .map((line) => line === ">" ? "" : line.slice(2))
    .join("\n")
    .trim();
  if (!quotedContext) {
    return { quotedContext: null, content };
  }
  return {
    quotedContext,
    content: separatorIndex === -1 ? "" : normalized.slice(separatorIndex + 2),
  };
}
