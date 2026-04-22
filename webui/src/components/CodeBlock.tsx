import { useCallback, useEffect, useState } from "react";
import { Check, Copy } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import {
  oneDark,
  oneLight,
} from "react-syntax-highlighter/dist/esm/styles/prism";

import { cn } from "@/lib/utils";

interface CodeBlockProps {
  language?: string;
  code: string;
  className?: string;
}

/** Read dark mode straight from the DOM — stays in sync with Tailwind's `dark:`. */
function useIsDark() {
  const [isDark, setIsDark] = useState(() =>
    typeof document !== "undefined"
      ? document.documentElement.classList.contains("dark")
      : true,
  );

  useEffect(() => {
    const el = document.documentElement;
    const observer = new MutationObserver(() => {
      setIsDark(el.classList.contains("dark"));
    });
    observer.observe(el, { attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);

  return isDark;
}

export function CodeBlock({ language, code, className }: CodeBlockProps) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const isDark = useIsDark();

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
    </div>
  );
}
