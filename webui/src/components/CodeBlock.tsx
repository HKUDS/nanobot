import { Suspense, lazy, memo, startTransition, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
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
  viewportHighlight?: boolean;
}

interface HighlightedCodeProps {
  language?: string;
  code: string;
  isDark: boolean;
  chrome: "default" | "none";
  showLineNumbers: boolean;
  wrapLongLines: boolean;
  viewportHighlight: boolean;
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

const LazyHighlightedCode = lazy(async () => {
  const [
    { default: SyntaxHighlighter },
    { default: oneDark },
    { default: oneLight },
    { ViewportCodeRows },
  ] = await Promise.all([
    import("react-syntax-highlighter/dist/esm/prism-async-light"),
    import("react-syntax-highlighter/dist/esm/styles/prism/one-dark"),
    import("react-syntax-highlighter/dist/esm/styles/prism/one-light"),
    import("@/components/ViewportCodeRows"),
  ]);

  return {
    default({
      language,
      code,
      isDark,
      chrome,
      showLineNumbers,
      wrapLongLines,
      viewportHighlight,
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
            background: "transparent",
            margin: 0,
            padding: chrome === "none" ? "0.75rem 1rem" : "1rem 3.5rem 1rem 1.25rem",
            fontFamily: CODE_FONT_STACK,
            fontSize: "13px",
            lineHeight: chrome === "none" ? 1.55 : 1.6,
            tabSize: 2,
          }}
          codeTagProps={{
            style: {
              background: "transparent",
              fontFamily: CODE_FONT_STACK,
              ...(viewportHighlight ? { lineHeight: "inherit" } : {}),
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
          showLineNumbers={showLineNumbers && !viewportHighlight}
          wrapLongLines={wrapLongLines}
          renderer={viewportHighlight ? props => <ViewportCodeRows {...props} /> : undefined}
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
  compact = false,
}: {
  code: string;
  chrome: "default" | "none";
  showLineNumbers: boolean;
  testId: string;
  className?: string;
  renderText?: (value: string) => ReactNode;
  compact?: boolean;
}) {
  const lines = showLineNumbers ? code.split("\n") : [];
  return (
    <pre
      className={cn(
        "m-0 overflow-x-auto bg-transparent font-mono text-[13px] text-foreground/90",
        showLineNumbers ? "whitespace-pre" : "whitespace-pre-wrap",
        chrome === "default"
          ? "py-4 pl-5 pr-14 leading-[1.6]"
          : compact ? "px-4 py-3 leading-[1.55]" : "p-3 leading-[1.55]",
        className,
      )}
      data-testid={testId}
      style={compact ? { fontFamily: CODE_FONT_STACK } : undefined}
    >
      <code className="text-inherit">
        {showLineNumbers && compact ? (
          <span className="flex min-w-max">
            <span aria-hidden className="shrink-0 select-none pr-[1.15rem] text-right text-muted-foreground/60"
              style={{ minWidth: "4.25em" }}>{lines.map((_, index) => index + 1).join("\n")}</span>
            <span>{renderText(code)}</span>
          </span>
        ) : showLineNumbers ? (
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

export const CodeBlock = memo(function CodeBlock({
  language,
  code,
  className,
  chrome = "default",
  highlight = true,
  showLineNumbers = false,
  wrapLongLines = true,
  viewportHighlight = false,
}: CodeBlockProps) {
  const { t } = useTranslation();
  const rootRef = useRef<HTMLDivElement>(null);
  const [copied, setCopied] = useState(false);
  const [highlightedSource, setHighlightedSource] = useState<string | null>(null);
  const renderAnsi = useMemo(() => shouldRenderAnsi(language, code), [language, code]);
  const plainCode = useMemo(() => renderAnsi ? stripAnsi(code) : code, [renderAnsi, code]);
  const isDark = useThemeValue() === "dark";
  const hasChrome = chrome === "default";
  const syntaxLanguage = normalizeCodeLanguage(language);
  const useViewportHighlight = viewportHighlight && showLineNumbers && !wrapLongLines;
  // Minified/very large previews must not monopolize the main thread in Prism.
  // Plain text still contains the entire preview, with normal selection and find.
  const withinHighlightBudget = useMemo(() => {
    if (!useViewportHighlight) return true;
    if (code.length > 100_000) return false;
    const lines = code.split("\n");
    return lines.length <= 2_000 && !lines.some(line => line.length > 2_000);
  }, [code, useViewportHighlight]);
  const deferHighlight = highlight && !renderAnsi && useViewportHighlight
    && withinHighlightBudget && code.length > 8_000;
  useEffect(() => {
    if (!deferHighlight) return;
    // Paint the tab and full plain source first. Color is a progressive enhancement,
    // not a reason to hold up switching tabs (including an already cached file).
    let frame = requestAnimationFrame(() => {
      frame = requestAnimationFrame(enhance);
    });
    function enhance() {
      const selection = document.getSelection();
      if (rootRef.current && selection && !selection.isCollapsed && selection.rangeCount
        && selection.getRangeAt(0).intersectsNode(rootRef.current)) return;
      document.removeEventListener("selectionchange", enhance);
      startTransition(() => setHighlightedSource(code));
    }
    document.addEventListener("selectionchange", enhance);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("selectionchange", enhance);
    };
  }, [code, deferHighlight]);
  const copyLabel = copied ? t("code.copied") : t("code.copyAria");

  const onCopy = useCallback(() => {
    void copyTextToClipboard(plainCode).then((ok) => {
      if (!ok) return;
      setCopied(true);
      setTimeout(() => setCopied(false), 1_500);
    });
  }, [plainCode]);

  return (
    <div
      ref={rootRef}
      className={cn(
        "not-prose relative overflow-hidden",
        hasChrome && "rounded-floating bg-secondary/70",
        className,
      )}
      data-language={language || t("code.fallbackLanguage")}
    >
      {renderAnsi ? (
        <CodeTextBlock
          code={code}
          chrome={chrome}
          showLineNumbers={showLineNumbers}
          testId="ansi-code"
          renderText={renderAnsiText}
          compact={useViewportHighlight}
        />
      ) : highlight && withinHighlightBudget && (!deferHighlight || highlightedSource === code) ? (
        <Suspense
          fallback={
            <CodeTextBlock
              code={code}
              chrome={chrome}
              showLineNumbers={showLineNumbers}
              testId="plain-code-fallback"
              compact={useViewportHighlight}
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
            viewportHighlight={useViewportHighlight}
          />
        </Suspense>
      ) : (
        <CodeTextBlock
          code={code}
          chrome={chrome}
          showLineNumbers={showLineNumbers}
          testId="plain-code-fallback"
          compact={useViewportHighlight}
        />
      )}
      {hasChrome ? (
        <button
          type="button"
          onClick={onCopy}
          className={cn(
            "absolute right-2.5 top-2.5 z-10 inline-flex h-8 w-8 items-center justify-center rounded-full",
            "text-muted-foreground/75 transition-colors hover:bg-background/70 hover:text-foreground",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
          )}
          aria-label={copyLabel}
          title={copyLabel}
        >
          {copied ? (
            <Check className="h-4 w-4" aria-hidden />
          ) : (
            <Copy className="h-4 w-4" aria-hidden />
          )}
        </button>
      ) : null}
    </div>
  );
});
