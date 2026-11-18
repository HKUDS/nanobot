import { createHighlighterCore } from "shiki/core";
import { createJavaScriptRegexEngine } from "shiki/engine/javascript";
import { bundledLanguages } from "shiki/langs";

import { CODE_TEXTMATE_THEME, CODE_THEME_NAME } from "./code-theme";
import type { CodeToken } from "./code-tokens";

let loaded: Awaited<ReturnType<typeof createHighlighterCore>> | undefined;
const highlighter = createHighlighterCore({
  engine: createJavaScriptRegexEngine(), langs: [],
  themes: [CODE_TEXTMATE_THEME],
}).then(engine => { loaded = engine; return engine; });

export function highlightGrammar(source: string, language: string): CodeToken[][] | Promise<CodeToken[][]> {
  const loader = Object.hasOwn(bundledLanguages, language) ? bundledLanguages[language as keyof typeof bundledLanguages] : undefined;
  if (!loader) return source.split("\n").map(content => [{ content }]);
  if (loaded?.getLoadedLanguages().includes(language)) return loaded.codeToTokens(source, { lang: language, theme: CODE_THEME_NAME }).tokens;
  return highlighter.then(async engine => {
    await engine.loadLanguage(loader);
    return engine.codeToTokens(source, { lang: language, theme: CODE_THEME_NAME }).tokens;
  });
}
