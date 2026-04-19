import { useState } from "react";
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

export function CodeBlock({ language, code, className }: CodeBlockProps) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  const onCopy = () => {
    if (!navigator.clipboard) return;
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1_500);
    });
  };

  const isDark =
    typeof window !== "undefined"
      ? document.documentElement.classList.contains("dark")
      : true;

  return (
    <div className={cn("overflow-hidden rounded-lg", className)}>
      <div className="flex items-center justify-between bg-zinc-900 px-4 py-1.5 text-xs font-medium text-zinc-200">
        <span className="lowercase">
          {language || t("code.fallbackLanguage")}
        </span>
        <button
          type="button"
          onClick={onCopy}
          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-zinc-300 transition-colors hover:bg-zinc-800 hover:text-zinc-100"
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
          background: "var(--tw-prose-pre-bg, #0a0a0a)",
          fontSize: "0.8125rem",
          lineHeight: 1.55,
        }}
        PreTag="pre"
        wrapLongLines
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
}
