import {
  Children,
  isValidElement,
  useMemo,
  type ReactNode,
} from "react";
import type { Components, Options as ReactMarkdownOptions } from "react-markdown";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import { Check, Globe2 } from "lucide-react";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { AttachmentTile } from "@/components/AttachmentTile";
import { CodeBlock } from "@/components/CodeBlock";
import {
  FileReferenceChip,
  isFilePatternReference,
  isLikelyFilePath,
} from "@/components/FileReferenceChip";
import { useLogoFallback } from "@/hooks/useLogoFallback";
import { inferMediaKind } from "@/lib/media";
import { faviconUrls } from "@/lib/provider-brand";
import { remarkTexMath } from "@/lib/remark-tex-math";
import { cn } from "@/lib/utils";

import "katex/dist/katex.min.css";

interface MarkdownTextRendererProps {
  children: string;
  className?: string;
  highlightCode?: boolean;
  onOpenFilePreview?: (path: string) => void;
}

type MarkdownAstNode = {
  type: string;
  value?: string;
  children?: MarkdownAstNode[];
  data?: {
    hName?: string;
  };
};

type InlineLinkPreview = {
  href: string;
  host: string;
  prefix?: string;
  title: string;
};

const SAFE_INLINE_HTML_TAGS = new Set(["mark", "sub", "sup"]);

function extensionOf(value: string): string {
  const clean = value.split(/[?#]/, 1)[0]?.trim() ?? "";
  const slash = clean.lastIndexOf("/");
  const name = slash >= 0 ? clean.slice(slash + 1) : clean;
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot).toLowerCase() : "";
}

function markdownAttachmentKind(source: string, label: string): "image" | "video" | "file" {
  const inferredKind = inferMediaKind({ url: source, name: label });
  if (inferredKind !== "file") return inferredKind;
  return extensionOf(label) || extensionOf(source) ? "file" : "image";
}

function safeHtmlNode(tagName: string, children: MarkdownAstNode[]): MarkdownAstNode {
  return {
    type: `nanobotSafeHtml${tagName}`,
    data: { hName: tagName },
    children,
  };
}

function safeText(value: string): MarkdownAstNode {
  return { type: "text", value };
}

function htmlTag(node: MarkdownAstNode): { tag: string; closing: boolean } | null {
  if (node.type !== "html" || typeof node.value !== "string") return null;
  const match = /^<\s*(\/?)\s*(mark|sub|sup)\s*>$/i.exec(node.value.trim());
  if (!match) return null;
  return { tag: match[2].toLowerCase(), closing: match[1] === "/" };
}

function normalizeSafeInlineHtml(children: MarkdownAstNode[]): MarkdownAstNode[] {
  const next: MarkdownAstNode[] = [];
  for (let index = 0; index < children.length; index += 1) {
    const node = children[index];
    if (node.children) {
      node.children = normalizeSafeInlineHtml(node.children);
    }

    const tag = htmlTag(node);
    if (!tag || tag.closing || !SAFE_INLINE_HTML_TAGS.has(tag.tag)) {
      next.push(node);
      continue;
    }

    let closeIndex = -1;
    for (let cursor = index + 1; cursor < children.length; cursor += 1) {
      const closeTag = htmlTag(children[cursor]);
      if (closeTag?.closing && closeTag.tag === tag.tag) {
        closeIndex = cursor;
        break;
      }
    }

    if (closeIndex === -1) {
      next.push(node);
      continue;
    }

    next.push(
      safeHtmlNode(
        tag.tag,
        normalizeSafeInlineHtml(children.slice(index + 1, closeIndex)),
      ),
    );
    index = closeIndex;
  }
  return next;
}

function detailsOpen(node: MarkdownAstNode): { summary: string } | null {
  if (node.type !== "html" || typeof node.value !== "string") return null;
  const value = node.value.trim();
  const match = /^<\s*details\s*>\s*<\s*summary\s*>([\s\S]*?)<\s*\/\s*summary\s*>$/i.exec(value);
  if (match) return { summary: match[1].trim() };
  if (/^<\s*details\s*>$/i.test(value)) return { summary: "Details" };
  return null;
}

function isDetailsClose(node: MarkdownAstNode): boolean {
  return node.type === "html"
    && typeof node.value === "string"
    && /^<\s*\/\s*details\s*>$/i.test(node.value.trim());
}

function normalizeSafeDetails(children: MarkdownAstNode[]): MarkdownAstNode[] {
  const next: MarkdownAstNode[] = [];
  for (let index = 0; index < children.length; index += 1) {
    const node = children[index];
    const open = detailsOpen(node);
    if (!open) {
      next.push(node);
      continue;
    }

    const closeIndex = children.findIndex(
      (candidate, candidateIndex) => candidateIndex > index && isDetailsClose(candidate),
    );
    if (closeIndex === -1) {
      next.push(node);
      continue;
    }

    const body = normalizeSafeInlineHtml(
      normalizeSafeDetails(children.slice(index + 1, closeIndex)),
    );
    next.push({
      type: "nanobotSafeHtmlDetails",
      data: { hName: "details" },
      children: [
        {
          type: "nanobotSafeHtmlSummary",
          data: { hName: "summary" },
          children: [safeText(open.summary)],
        },
        ...body,
      ],
    });
    index = closeIndex;
  }
  return next;
}

function remarkSafeHtmlSubset() {
  return (tree: MarkdownAstNode) => {
    if (tree.children) {
      tree.children = normalizeSafeInlineHtml(normalizeSafeDetails(tree.children));
    }
  };
}

const remarkPlugins: NonNullable<ReactMarkdownOptions["remarkPlugins"]> = [
  remarkBreaks,
  remarkGfm,
  [remarkMath, { singleDollarTextMath: false }],
  remarkTexMath,
  remarkSafeHtmlSubset,
];
const rehypePlugins: NonNullable<ReactMarkdownOptions["rehypePlugins"]> = [rehypeKatex];

function nodeText(value: ReactNode): string {
  return Children.toArray(value)
    .map((child) => (typeof child === "string" || typeof child === "number" ? String(child) : ""))
    .join("");
}

function cleanFileReferenceTarget(value: string): string {
  let target = value.trim();
  if (!target) return "";
  try {
    if (/^file:\/\//i.test(target)) {
      target = decodeURIComponent(new URL(target).pathname);
    } else {
      target = decodeURIComponent(target);
    }
  } catch {
    // Keep the raw value when URL/path decoding is not possible.
  }
  target = target.split("?", 1)[0]?.split("#", 1)[0]?.trim() ?? "";
  if (!/^[A-Za-z]:[\\/]/.test(target)) {
    target = target.replace(/:\d+(?::\d+)?$/, "");
  }
  return target;
}

function isPreviewableFileTarget(value: string): boolean {
  if (isFilePatternReference(value)) return false;
  if (isLikelyFilePath(value)) return true;
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) return false;
  if (/[\\/]/.test(value)) return false;
  return /^[^?#]+\.[a-z0-9][a-z0-9_-]{0,12}$/i.test(value);
}

function isNonNavigableFilePatternLink(href: string | undefined): boolean {
  if (!href || /^https?:\/\//i.test(href) || href.startsWith("#")) return false;
  const target = cleanFileReferenceTarget(href);
  return Boolean(target && isFilePatternReference(target));
}

function fileReferenceFromLink(href: string | undefined): string | null {
  if (!href || /^https?:\/\//i.test(href) || href.startsWith("#")) return null;
  const target = cleanFileReferenceTarget(href);
  return isPreviewableFileTarget(target) ? target : null;
}

function linkPreviewParts(value: ReactNode): { text: string; href?: string } {
  let text = "";
  let href: string | undefined;
  for (const child of Children.toArray(value)) {
    if (typeof child === "string" || typeof child === "number") {
      text += String(child);
      continue;
    }
    if (!isValidElement(child)) {
      continue;
    }
    const props = child.props as { href?: unknown; children?: ReactNode };
    if (!href && typeof props.href === "string" && /^https?:\/\//i.test(props.href)) {
      href = props.href;
    }
    const nested = linkPreviewParts(props.children);
    text += nested.text;
    href ||= nested.href;
  }
  return { text, href };
}

function cleanLinkPreviewText(value: string): string {
  return value
    .replace(/\s+/g, " ")
    .replace(/^[\s"'“”‘’]+|[\s"'“”‘’]+$/g, "")
    .trim();
}

function inlineLinkPreviewFromChildren(children: ReactNode): InlineLinkPreview | null {
  const { text: rawText, href } = linkPreviewParts(children);
  if (!href) return null;

  let url: URL;
  try {
    url = new URL(href);
  } catch {
    return null;
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return null;

  const strippedUrl = rawText
    .replace(/\s+/g, " ")
    .replace(href, "")
    .replace(url.toString(), "")
    .replace(/https?:\/\/\S+/i, "")
    .trim();
  if (!strippedUrl || strippedUrl.length < 4) return null;

  const sourceMatch = /^(.*?)\s*(?:[—–]| - |:)\s*(.+)$/.exec(strippedUrl);
  const prefix = sourceMatch?.[1] ? cleanLinkPreviewText(sourceMatch[1]) : undefined;
  const title = cleanLinkPreviewText(sourceMatch?.[2] ?? strippedUrl);
  if (!title || /^https?:\/\//i.test(title)) return null;

  return {
    href,
    host: url.hostname,
    prefix,
    title,
  };
}

function InlineLinkPreviewRow({ link }: { link: InlineLinkPreview }) {
  const { favicon, onFaviconError, onFaviconLoad } = useFaviconFallback(link.host);
  const label = link.prefix
    ? `${link.prefix} — ${link.title}`
    : link.title;

  return (
    <a
      href={link.href}
      target="_blank"
      rel="noreferrer noopener"
      aria-label={`Open link: ${label}`}
      className={cn(
        "not-prose inline-flex max-w-full items-center gap-2 align-baseline",
        "text-blue-500 no-underline underline-offset-2 hover:underline dark:text-blue-300",
      )}
    >
      <span
        className={cn(
          "relative grid h-4 w-4 shrink-0 place-items-center overflow-hidden rounded-[4px]",
          "border border-border/65 bg-background text-muted-foreground",
        )}
        aria-hidden
      >
        {favicon ? (
          <img
            src={favicon}
            alt=""
            className="h-3 w-3 rounded-[2px] object-contain"
            decoding="async"
            loading="lazy"
            onLoad={onFaviconLoad}
            onError={onFaviconError}
          />
        ) : (
          <Globe2 className="h-3 w-3" />
        )}
      </span>
      <span className="min-w-0 [overflow-wrap:anywhere] leading-normal sm:truncate">
        {label}
      </span>
    </a>
  );
}

function useFaviconFallback(host: string) {
  const faviconCandidates = useMemo(() => faviconUrls(host), [host]);
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(faviconCandidates);

  return {
    favicon: logoUrl ?? null,
    onFaviconError: onLogoError,
    onFaviconLoad: onLogoLoad,
  };
}

function isRenderedCodeBlock(value: ReactNode): boolean {
  if (!isValidElement(value)) return false;
  const props = value.props as { code?: unknown };
  return value.type === CodeBlock || typeof props.code === "string";
}

function codeFenceFromPreChild(value: ReactNode): { code: string; language?: string } | null {
  if (!isValidElement(value)) return null;
  const props = value.props as { className?: unknown; children?: ReactNode };
  if (!("children" in props)) return null;
  const className = typeof props.className === "string" ? props.className : "";
  const language = /language-([^\s]+)/.exec(className)?.[1];
  return {
    code: nodeText(props.children).replace(/\n$/, ""),
    language,
  };
}

/**
 * Heavy markdown stack (GFM, math, KaTeX, syntax highlighting) kept in a
 * separate chunk so the app shell can paint sooner on refresh.
 */
export default function MarkdownTextRenderer({
  children,
  className,
  highlightCode = true,
  onOpenFilePreview,
}: MarkdownTextRendererProps) {
  const components = useMemo<Components>(
    () => ({
      code({ className: cls, children: kids, ...props }) {
        const match = /language-(\w+)/.exec(cls || "");
        if (match) {
          const code = String(kids).replace(/\n$/, "");
          return (
            <CodeBlock
              language={match[1]}
              code={code}
              className="my-3"
              highlight={highlightCode}
            />
          );
        }
        const raw = String(kids).replace(/\n$/, "");
        if (isLikelyFilePath(raw)) {
          return <FileReferenceChip path={raw} onOpen={onOpenFilePreview} />;
        }
        /** Plain fenced ``` blocks (no language) & wide one-liners: block monospace, not inline pill. */
        const widePlainBlock = raw.includes("\n") || raw.length > 120;
        if (widePlainBlock) {
          return (
            <code
              className={cn(
                "block min-w-0 max-w-full overflow-x-auto whitespace-pre bg-transparent p-0 font-mono text-[0.8125rem]",
                "leading-snug text-inherit",
                cls,
              )}
              {...props}
            >
              {kids}
            </code>
          );
        }
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
      },
      pre({ children: markdownChildren }) {
        const kids = Children.toArray(markdownChildren);
        const lone = kids.length === 1 ? kids[0] : null;
        /** Highlighted fences render ``CodeBlock`` (block shell); skip invalid ``<pre><div>``. */
        if (isRenderedCodeBlock(lone)) {
          return <>{markdownChildren}</>;
        }
        const fence = codeFenceFromPreChild(lone);
        if (fence) {
          return (
            <CodeBlock
              language={fence.language || "text"}
              code={fence.code}
              className="my-3"
              highlight={highlightCode}
            />
          );
        }
        return (
          <pre
            className={cn(
              "my-3 overflow-x-auto rounded-lg border border-border/60 bg-muted/35",
              "p-3 font-mono text-[0.8125rem] leading-snug text-foreground/90",
              "whitespace-pre [overflow-wrap:normal]",
            )}
          >
            {markdownChildren}
          </pre>
        );
      },
      a({ href, children: markdownChildren, ...props }) {
        const filePath = fileReferenceFromLink(href);
        if (filePath) {
          const label = nodeText(markdownChildren).trim();
          return (
            <FileReferenceChip
              path={label || filePath}
              tooltipPath={filePath}
              previewPath={filePath}
              onOpen={onOpenFilePreview}
            />
          );
        }
        if (isNonNavigableFilePatternLink(href)) {
          return <>{markdownChildren}</>;
        }
        return (
          <a
            href={href}
            target="_blank"
            rel="noreferrer noopener"
            className="text-blue-500 underline underline-offset-2 hover:text-blue-600 dark:text-blue-300 dark:hover:text-blue-200"
            {...props}
          >
            {markdownChildren}
          </a>
        );
      },
      table({ children, ...props }) {
        // Wrap wide markdown tables in a horizontal-scroll container (the
        // pattern used by DeepSeek/others) so a 6+ column table scrolls inside
        // the conversation column instead of forcing the page wider than 100vw.
        // min-w-max keeps natural column widths; w-full stretches narrow tables.
        return (
          <div className="w-full overflow-x-auto">
            <table className="w-full min-w-max" {...props}>
              {children}
            </table>
          </div>
        );
      },
      li({ children: markdownChildren, className: itemClassName }) {
        const link = inlineLinkPreviewFromChildren(markdownChildren);
        if (link) {
          return (
            <li className={cn("list-none pl-0", itemClassName)}>
              <InlineLinkPreviewRow link={link} />
            </li>
          );
        }
        return (
          <li className={itemClassName}>
            {markdownChildren}
          </li>
        );
      },
      input({ type, checked }) {
        if (type !== "checkbox") return null;
        return (
          <span
            aria-hidden
            data-testid="markdown-task-checkbox"
            className={cn(
              "mr-2 inline-grid h-4 w-4 translate-y-[2px] place-items-center rounded-[4px]",
              "border border-border/70 bg-muted/55 text-background",
              checked && "border-foreground/55 bg-foreground/65",
            )}
          >
            {checked ? <Check className="h-3 w-3 stroke-[3]" /> : null}
          </span>
        );
      },
      mark({ children: markdownChildren }) {
        return (
          <mark className="rounded-[5px] bg-yellow-200/75 px-1 py-0.5 text-inherit dark:bg-yellow-300/25">
            {markdownChildren}
          </mark>
        );
      },
      sub({ children: markdownChildren }) {
        return <sub className="text-[0.72em] leading-none">{markdownChildren}</sub>;
      },
      sup({ children: markdownChildren }) {
        return <sup className="text-[0.72em] leading-none">{markdownChildren}</sup>;
      },
      details({ children: markdownChildren }) {
        return (
          <details className="my-3 rounded-xl border border-border/65 bg-muted/25 px-4 py-3 open:pb-4">
            {markdownChildren}
          </details>
        );
      },
      summary({ children: markdownChildren }) {
        return (
          <summary className="cursor-pointer select-none text-sm font-medium text-foreground/88 marker:text-muted-foreground">
            {markdownChildren}
          </summary>
        );
      },
      img({ src, alt, node: _node, className: imgClassName, ...props }) {
        void _node;
        void imgClassName;
        void props;
        const source = typeof src === "string" ? src : "";
        if (!source) return null;
        const label = typeof alt === "string" ? alt : "";
        const kind = markdownAttachmentKind(source, label);
        return (
          <AttachmentTile
            attachment={{
              kind,
              url: source,
              name: label,
            }}
            inline
          />
        );
      },
    }),
    [highlightCode, onOpenFilePreview],
  );

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
        "prose-a:text-blue-500 prose-a:underline-offset-2 hover:prose-a:text-blue-600 dark:prose-a:text-blue-300 dark:hover:prose-a:text-blue-200",
        "prose-hr:my-6",
        "prose-pre:my-0 prose-pre:bg-transparent prose-pre:p-0",
        "prose-code:before:content-none prose-code:after:content-none prose-code:font-normal",
        "prose-table:my-3 prose-th:text-left prose-th:font-medium",
        className,
      )}
      style={{ lineHeight: "var(--cjk-line-height)" }}
    >
      <ReactMarkdown
        remarkPlugins={remarkPlugins}
        rehypePlugins={rehypePlugins}
        components={components}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
