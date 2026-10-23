import { codeToTokens, isSupportedLanguage } from "@pierre/highlights";

import { CODE_THEME, codeHighlighterLanguage } from "./code-theme";
import { codeTokenLines, type CodeLine } from "./code-tokens";

const MAX_CACHED_SOURCE_BYTES = 2 * 1024 * 1024;
const MAX_CACHE_ENTRIES = 16;
type HighlightResult =
  | { state: "ready"; lines: CodeLine[] }
  | { state: "pending"; promise: Promise<void> }
  | { state: "failed"; error: unknown };
export interface CodeHighlight {
  read(): CodeLine[];
}
const cache = new Map<string, CodeHighlight>();
let sourceBytes = 0;
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
  const lang = codeHighlighterLanguage(language);
  const key = `${lang}\0${source}`;
  const cached = cache.get(key);
  if (cached) {
    cache.delete(key);
    cache.set(key, cached);
    return cached;
  }
  const resource = highlight(source, lang);
  const bytes = key.length * 2;
  if (bytes <= MAX_CACHED_SOURCE_BYTES) {
    while (cache.size >= MAX_CACHE_ENTRIES || sourceBytes + bytes > MAX_CACHED_SOURCE_BYTES) {
      const oldest = cache.keys().next().value!;
      cache.delete(oldest);
      sourceBytes -= oldest.length * 2;
    }
    cache.set(key, resource);
    sourceBytes += bytes;
  }
  return resource;
}
