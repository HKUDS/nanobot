import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { CodeBlock } from "@/components/CodeBlock";
import { cn } from "@/lib/utils";

import "katex/dist/katex.min.css";

interface MarkdownTextRendererProps {
  children: string;
  className?: string;
}

/**
 * Heavy markdown stack (GFM, math, KaTeX, syntax highlighting) kept in a
 * separate chunk so the app shell can paint sooner on refresh.
 */
export default function MarkdownTextRenderer({
  children,
  className,
}: MarkdownTextRendererProps) {
  return (
    <div
      className={cn(
        "markdown-content prose max-w-none dark:prose-invert",
        "prose-headings:mt-4 prose-headings:mb-2 prose-headings:font-semibold prose-headings:tracking-tight",
        "prose-h1:text-lg prose-h2:text-base prose-h3:text-sm prose-h4:text-[13px]",
        "prose-p:my-2",
        "prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5",
        "prose-blockquote:my-3 prose-blockquote:border-l-2 prose-blockquote:font-normal",
        "prose-blockquote:not-italic prose-blockquote:text-foreground/80",
        "prose-a:text-primary prose-a:underline-offset-2 hover:prose-a:opacity-80",
        "prose-hr:my-6",
        "prose-pre:my-0 prose-pre:bg-transparent prose-pre:p-0",
        "prose-code:before:content-none prose-code:after:content-none prose-code:font-normal",
        "prose-table:my-3 prose-th:text-left prose-th:font-medium",
        className,
      )}
      style={{ lineHeight: "var(--cjk-line-height)" }}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          code({ className: cls, children: kids, ...props }) {
            const match = /language-(\w+)/.exec(cls || "");
            if (!match) {
              return (
                <code
                  className={cn(
                    "rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]",
                    cls,
                  )}
                  {...props}
                >
                  {kids}
                </code>
              );
            }
            const code = String(kids).replace(/\n$/, "");
            return <CodeBlock language={match[1]} code={code} className="my-3" />;
          },
          pre({ children: markdownChildren }) {
            return <>{markdownChildren}</>;
          },
          a({ href, children: markdownChildren, ...props }) {
            return (
              <a
                href={href}
                target="_blank"
                rel="noreferrer noopener"
                className="text-primary underline underline-offset-2 hover:opacity-80"
                {...props}
              >
                {markdownChildren}
              </a>
            );
          },
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
