import { codeToTokens, isSupportedLanguage } from "@pierre/highlights";

import { cacheCodeHighlight, cachedCodeHighlight, type CodeHighlight } from "./code-highlight-cache";
import { CODE_THEME, codeHighlighterLanguage } from "./code-theme";
import { codeTokenLines, type CodeLine } from "./code-tokens";

type HighlightResult =
  | { state: "ready"; lines: CodeLine[] }
  | { state: "pending"; promise: Promise<void> }
  | { state: "failed"; error: unknown };
let grammars: typeof import("./code-highlighter-grammars") | undefined;

function highlight(source: string, language: string): CodeHighlight {
  const code = source.replace(/\r\n/g, "\n").replace(/\r$/, "");
  let result: HighlightResult;
  if (isSupportedLanguage(language)) {
    result = { state: "ready", lines: codeTokenLines(source, codeToTokens(code, { lang: language, theme: CODE_THEME }).tokens) };
  } else {
    const tokens = grammars ? grammars.highlightGrammar(code, language) : import("./code-highlighter-grammars").then(module => {
      grammars = module;
      return module.highlightGrammar(code, language);
    });
    if (tokens instanceof Promise) {
      const promise = tokens.then(tokens => {
        result = { state: "ready", lines: codeTokenLines(source, tokens) };
      }, error => { result = { state: "failed", error }; });
      result = { state: "pending", promise };
    } else {
      result = { state: "ready", lines: codeTokenLines(source, tokens) };
    }
  }
  return { read() {
    if (result.state === "pending") throw result.promise;
    if (result.state === "failed") throw result.error;
    return result.lines;
  } };
}

export function codeHighlight(source: string, language: string): CodeHighlight {
  const cached = cachedCodeHighlight(source, language);
  if (cached) return cached;
  const resource = highlight(source, codeHighlighterLanguage(language));
  cacheCodeHighlight(source, language, resource);
  return resource;
}
