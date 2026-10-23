import { useMemo } from "react";

import { codeHighlight } from "@/lib/code-highlighter";
import { CodeTokens } from "./CodeTokens";
import { ViewportCodeRows } from "./ViewportCodeRows";

export interface HighlightedCodeProps {
  language?: string;
  code: string;
  chrome: "default" | "none";
  showLineNumbers: boolean;
  wrapLongLines: boolean;
  viewportHighlight: boolean;
}

export function HighlightedCode({ language = "text", code, chrome, showLineNumbers, wrapLongLines, viewportHighlight }: HighlightedCodeProps) {
  const resource = useMemo(() => codeHighlight(code, language), [code, language]);
  const lines = resource.read();
  return <pre data-testid="highlighted-code" data-language={language} style={{
    background: "transparent", margin: 0,
    padding: chrome === "none" ? "0.75rem 1rem" : "1rem 3.5rem 1rem 1.25rem",
    fontFamily: "inherit", fontSize: "inherit", lineHeight: "inherit", tabSize: 2,
    whiteSpace: wrapLongLines ? "pre-wrap" : "pre", overflow: viewportHighlight ? "visible" : "auto",
    overflowWrap: wrapLongLines ? "anywhere" : undefined,
  }}><code className="text-inherit">
    {viewportHighlight ? <ViewportCodeRows lines={lines} /> : showLineNumbers ? lines.map((line, index) => (
      <span key={index} className="flex">
        <span aria-hidden className="shrink-0 select-none pr-[1.15rem] text-right text-muted-foreground" style={{ minWidth: "2.6em" }}>{index + 1}</span>
        <span data-code-text="" className="min-w-0"><CodeTokens lines={[line]} /></span>
      </span>
    )) : <span data-code-text=""><CodeTokens lines={lines} /></span>}
  </code></pre>;
}
