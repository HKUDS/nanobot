import { Suspense, lazy, useCallback, useState, type ReactNode } from "react";
import { Check, Copy } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useThemeValue } from "@/hooks/useTheme";
import { hasAnsi, parseAnsiSegments, stripAnsi } from "@/lib/ansi";
import { copyTextToClipboard } from "@/lib/clipboard";
import { normalizeCodeLanguage } from "@/lib/code-language";
import { cn } from "@/lib/utils";

interface CodeBlockProps {
  language?: string;
  code: string;
  className?: string;
  chrome?: "default" | "none";
  highlight?: boolean;
  showLineNumbers?: boolean;
  wrapLongLines?: boolean;
}

interface HighlightedCodeProps {
  language?: string;
  code: string;
  isDark: boolean;
  chrome: "default" | "none";
  showLineNumbers: boolean;
  wrapLongLines: boolean;
}

const CODE_FONT_STACK = [
  '"JetBrains Mono"',
  '"SFMono-Regular"',
  '"SF Mono"',
  '"Fira Code"',
  '"Cascadia Code"',
  '"Source Code Pro"',
  "Menlo",
  "Consolas",
  "monospace",
].join(", ");

const ANSI_LANGUAGES = new Set(["ansi", "ansi-output"]);
const CODE_SURFACE_LIGHT = "#f4f4f5";
const CODE_SURFACE_DARK = "#27272a";

const LazyHighlightedCode = lazy(async () => {
  const [
    { default: SyntaxHighlighter },
    { default: oneDark },
    { default: oneLight },
  ] = await Promise.all([
    import("react-syntax-highlighter/dist/esm/prism-async-light"),
    import("react-syntax-highlighter/dist/esm/styles/prism/one-dark"),
    import("react-syntax-highlighter/dist/esm/styles/prism/one-light"),
  ]);

  return {
    default({
      language,
      code,
      isDark,
      chrome,
      showLineNumbers,
      wrapLongLines,
    }: HighlightedCodeProps) {
      const theme = isDark ? oneDark : oneLight;
      const transparentTheme = chrome === "none" ? {
        ...theme,
        'pre[class*="language-"]': {
          ...theme['pre[class*="language-"]'],
          background: "transparent",
        },
        'code[class*="language-"]': {
          ...theme['code[class*="language-"]'],
          background: "transparent",
        },
      } : theme;

      return (
        <SyntaxHighlighter
          language={language || "text"}
          style={transparentTheme}
          customStyle={{
            background: chrome === "none"
              ? "transparent"
              : isDark
                ? CODE_SURFACE_DARK
                : CODE_SURFACE_LIGHT,
            margin: 0,
            padding: chrome === "none" ? "0.75rem 1rem" : "1rem",
            fontFamily: CODE_FONT_STACK,
            fontSize: chrome === "none" ? "13px" : "0.875rem",
            lineHeight: chrome === "none" ? 1.55 : 1.6,
            tabSize: 2,
          }}
          codeTagProps={{
            style: {
              background: "transparent",
              fontFamily: CODE_FONT_STACK,
            },
          }}
          lineNumberStyle={{
            minWidth: "2.6em",
            paddingRight: "1.15rem",
            color: isDark ? "rgba(212, 212, 216, 0.45)" : "rgba(63, 63, 70, 0.68)",
            fontFamily: CODE_FONT_STACK,
            userSelect: "none",
          }}
          PreTag="pre"
          showLineNumbers={showLineNumbers}
          wrapLongLines={wrapLongLines}
        >
          {code}
        </SyntaxHighlighter>
      );
    },
  };
});

function renderPlainText(value: string): ReactNode {
  return value;
}

function renderAnsiText(value: string): ReactNode {
  return parseAnsiSegments(value).map((segment, index) => (
    <span key={index} style={segment.style}>
      {segment.text}
    </span>
  ));
}

function CodeTextBlock({
  code,
  chrome,
  showLineNumbers,
  testId,
  className,
  renderText = renderPlainText,
}: {
  code: string;
  chrome: "default" | "none";
  showLineNumbers: boolean;
  testId: string;
  className?: string;
  renderText?: (value: string) => ReactNode;
}) {
  const lines = code.split("\n");
  return (
    <pre
      className={cn(
        "m-0 overflow-x-auto p-4 font-mono text-sm leading-[1.6] text-foreground/90",
        showLineNumbers ? "whitespace-pre" : "whitespace-pre-wrap",
        chrome === "default" ? "bg-zinc-100 dark:bg-zinc-800" : "bg-transparent",
        chrome === "none" && "p-3 text-[13px] leading-[1.55]",
        className,
      )}
      data-testid={testId}
    >
      <code className="text-inherit">
        {showLineNumbers ? (
          lines.map((line, index) => (
            <span key={index} className="flex min-w-max">
              <span className="w-10 shrink-0 select-none pr-4 text-right text-muted-foreground/60">
                {index + 1}
              </span>
              <span className="whitespace-pre">{renderText(line || " ")}</span>
              {index < lines.length - 1 ? "\n" : null}
            </span>
          ))
        ) : renderText(code)}
      </code>
    </pre>
  );
}

function shouldRenderAnsi(language: string | undefined, code: string): boolean {
  const normalized = language?.trim().toLowerCase();
  return Boolean((normalized && ANSI_LANGUAGES.has(normalized)) || hasAnsi(code));
}

export function CodeBlock({
  language,
  code,
  className,
  chrome = "default",
  highlight = true,
  showLineNumbers = false,
  wrapLongLines = true,
}: CodeBlockProps) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const isDark = useThemeValue() === "dark";
  const hasChrome = chrome === "default";
  const renderAnsi = shouldRenderAnsi(language, code);
  const syntaxLanguage = normalizeCodeLanguage(language);

  const onCopy = useCallback(() => {
    void copyTextToClipboard(renderAnsi ? stripAnsi(code) : code).then((ok) => {
      if (!ok) return;
      setCopied(true);
      setTimeout(() => setCopied(false), 1_500);
    });
  }, [code, renderAnsi]);

  return (
    <div
      className={cn(
        "not-prose overflow-hidden",
        hasChrome && "rounded-lg border",
        hasChrome && (isDark ? "border-white/10" : "border-black/10"),
        className,
      )}
    >
      {hasChrome ? (
        <div
          className={cn(
            "flex items-center justify-between px-4 pb-1.5 pt-2 text-xs font-medium",
            isDark
              ? "bg-zinc-800 text-zinc-300"
              : "bg-zinc-100 text-zinc-600",
          )}
        >
          <span className="lowercase font-mono">
            {language || t("code.fallbackLanguage")}
          </span>
          <button
            type="button"
            onClick={onCopy}
            className={cn(
              "inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono transition-colors",
              isDark
                ? "text-zinc-400 hover:bg-zinc-700 hover:text-zinc-200"
                : "text-zinc-500 hover:bg-zinc-200 hover:text-zinc-700",
            )}
            aria-label={t("code.copyAria")}
          >
            {copied ? (
              <Check className="h-3.5 w-3.5" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
            <span>{copied ? t("code.copied") : t("code.copy")}</span>
          </button>
        </div>
      ) : null}
      {renderAnsi ? (
        <CodeTextBlock
          code={code}
          chrome={chrome}
          showLineNumbers={showLineNumbers}
          testId="ansi-code"
          renderText={renderAnsiText}
        />
      ) : highlight ? (
        <Suspense
          fallback={
            <CodeTextBlock
              code={code}
              chrome={chrome}
              showLineNumbers={showLineNumbers}
              testId="plain-code-fallback"
            />
          }
        >
          <LazyHighlightedCode
            language={syntaxLanguage}
            code={code}
            isDark={isDark}
            chrome={chrome}
            showLineNumbers={showLineNumbers}
            wrapLongLines={wrapLongLines}
          />
        </Suspense>
      ) : (
        <CodeTextBlock
          code={code}
          chrome={chrome}
          showLineNumbers={showLineNumbers}
          testId="plain-code-fallback"
        />
      )}
    </div>
  );
}
