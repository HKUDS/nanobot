import { Fragment } from "react";

import type { CodeLine } from "@/lib/code-tokens";

export function CodeTokens({ lines }: { lines: CodeLine[] }) {
  return <>{lines.map((line, lineIndex) => <Fragment key={lineIndex}>
    {line.tokens.map((token, index) => token.color || token.fontStyle ? <span key={index} data-code-token="" style={{
      color: token.color,
      fontStyle: token.fontStyle && token.fontStyle & 1 ? "italic" : undefined,
      fontWeight: token.fontStyle && token.fontStyle & 2 ? 700 : undefined,
      textDecoration: token.fontStyle && token.fontStyle & 4 ? "underline" : undefined,
    }}>{token.content}</span> : token.content)}
  </Fragment>)}</>;
}
