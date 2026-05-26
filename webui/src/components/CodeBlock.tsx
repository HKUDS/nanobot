import { Suspense, lazy, useCallback, useState } from "react";
import { Check, Copy } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useThemeValue } from "@/hooks/useTheme";
import { cn } from "@/lib/utils";

interface CodeBlockProps {
  language?: string;
  code: string;
  className?: string;
  highlight?: boolean;
}

interface HighlightedCodeProps {
  language?: string;
  code: string;
  isDark: boolean;
}

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
    default({ language, code, isDark }: HighlightedCodeProps) {
      return (
        <SyntaxHighlighter
          language={language}
          style={isDark ? oneDark : oneLight}
          customStyle={{
            margin: 0,
            padding: "1rem",
            fontSize: "0.875rem",
            lineHeight: 1.6,
          }}
          PreTag="pre"
          wrapLongLines
        >
          {code}
        </SyntaxHighlighter>
      );
    },
  };
});

function PlainCodeFallback({ code }: { code: string }) {
  return (
    <pre
      className="m-0 overflow-x-auto whitespace-pre-wrap p-4 font-mono text-sm leading-[1.6]"
    >
      <code>{code}</code>
    </pre>
  );
}

export function CodeBlock({
  language,
  code,
  className,
  highlight = true,
}: CodeBlockProps) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const isDark = useThemeValue() === "dark";

  const onCopy = useCallback(() => {
    if (!navigator.clipboard) return;
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1_500);
    });
  }, [code]);

  return (
    <div
      className={cn(
        "overflow-hidden rounded-lg border",
        isDark ? "border-white/10" : "border-black/10",
        className,
      )}
    >
      <div
        className={cn(
          "flex items-center justify-between px-4 py-1.5 text-xs font-medium",
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
      {highlight ? (
        <Suspense fallback={<PlainCodeFallback code={code} />}>
          <LazyHighlightedCode language={language} code={code} isDark={isDark} />
        </Suspense>
      ) : (
        <PlainCodeFallback code={code} />
      )}
    </div>
  );
}
