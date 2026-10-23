import type { Theme } from "@pierre/highlights";
import type { ThemeRegistration } from "shiki";

export const CODE_THEME_NAME = "nanobot-code";
export const CODE_THEME: Theme = {
  name: CODE_THEME_NAME, appearance: "dark", cssVariables: { prefix: "--code-" },
  style: {
    "editor.foreground": "foreground", "editor.background": "background",
    syntax: {
      comment: { color: "comment", font_style: "italic" },
      string: "string", "text.literal": "string",
      keyword: "keyword", preproc: "keyword",
      operator: "function", function: "function", constructor: "function",
      type: "property", attribute: "property", tag: "property",
      property: "property", number: "property", boolean: "property", constant: "property",
      title: { color: "keyword", font_weight: 700 }, emphasis: { font_style: "italic" }, "emphasis.strong": { font_weight: 700 },
    },
  },
};

export const CODE_TEXTMATE_THEME: ThemeRegistration = {
  name: CODE_THEME_NAME, type: "dark", fg: "var(--code-foreground)", bg: "var(--code-background)",
  tokenColors: [
    { scope: "comment", settings: { foreground: "var(--code-comment)", fontStyle: "italic" } },
    { scope: ["string", "markup.raw"], settings: { foreground: "var(--code-string)" } },
    { scope: ["keyword", "storage"], settings: { foreground: "var(--code-keyword)" } },
    { scope: ["entity.name.function", "support.function", "variable.function", "keyword.operator"], settings: { foreground: "var(--code-function)" } },
    { scope: ["constant", "support.type", "entity.name.type", "entity.name.tag", "entity.other.attribute-name", "entity.name.section"], settings: { foreground: "var(--code-property)" } },
    { scope: ["keyword.operator.new", "keyword.operator.expression"], settings: { foreground: "var(--code-keyword)" } },
    { scope: "markup.heading", settings: { foreground: "var(--code-keyword)", fontStyle: "bold" } },
    { scope: "markup.italic", settings: { fontStyle: "italic" } },
    { scope: "markup.bold", settings: { fontStyle: "bold" } },
  ],
};

export function codeHighlighterLanguage(language: string): string {
  return language === "markup" ? "html" : language === "docker" ? "dockerfile" : language;
}
