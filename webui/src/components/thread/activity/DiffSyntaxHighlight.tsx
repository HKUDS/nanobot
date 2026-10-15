import { Suspense, lazy, type ReactNode } from "react";
import type { SyntaxHighlighterProps } from "react-syntax-highlighter";

import type { RenderableFileDiffLine } from "@/lib/file-diff";
import { cn } from "@/lib/utils";

interface DiffSyntaxHighlightProps {
  language: string;
  lines: RenderableFileDiffLine[];
}

type RendererArgs = Parameters<NonNullable<SyntaxHighlighterProps["renderer"]>>[0];
type SyntaxNode = RendererArgs["rows"][number];

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

const LazyDiffSyntaxHighlight = lazy(async () => {
  const [
    { default: SyntaxHighlighter },
    { default: createSyntaxElement },
  ] = await Promise.all([
    import("react-syntax-highlighter/dist/esm/prism-async-light"),
    import("react-syntax-highlighter/dist/esm/create-element"),
  ]);
  return {
    default: function LoadedDiffSyntaxHighlight({
      language,
      lines,
    }: DiffSyntaxHighlightProps) {
      const code = lines.map((line) => line.content || " ").join("\n");
      return (
        <SyntaxHighlighter
          language={language}
          useInlineStyles={false}
          style={{}}
          PreTag="div"
          CodeTag="div"
          customStyle={{
            background: "transparent",
            margin: 0,
            padding: 0,
            overflow: "visible",
            fontFamily: CODE_FONT_STACK,
            fontSize: "11px",
            lineHeight: "1.25rem",
          }}
          codeTagProps={{
            style: {
              background: "transparent",
              fontFamily: CODE_FONT_STACK,
            },
          }}
          data-language={language}
          className="code-content"
          data-testid="syntax-highlighted-diff-hunk"
          renderer={({ rows, stylesheet, useInlineStyles }) => (
            <DiffLineTable
              lines={lines}
              renderCode={(line, index) => {
                const node = rows[index];
                if (!node) return line.content || " ";
                return createSyntaxElement({
                  node: stripConflictingTableClass(trimTrailingLineBreak(node)),
                  stylesheet,
                  useInlineStyles,
                  key: `diff-code-${index}`,
                });
              }}
            />
          )}
        >
          {code}
        </SyntaxHighlighter>
      );
    },
  };
});

export function DiffSyntaxHighlight({ language, lines }: DiffSyntaxHighlightProps) {
  return (
    <Suspense fallback={<PlainDiffLines lines={lines} />}>
      <LazyDiffSyntaxHighlight language={language} lines={lines} />
    </Suspense>
  );
}

function PlainDiffLines({ lines }: { lines: RenderableFileDiffLine[] }) {
  return (
    <div data-testid="plain-diff-hunk">
      <DiffLineTable lines={lines} renderCode={(line) => line.content || " "} />
    </div>
  );
}

function DiffLineTable({
  lines,
  renderCode,
}: {
  lines: RenderableFileDiffLine[];
  renderCode: (line: RenderableFileDiffLine, index: number) => ReactNode;
}) {
  return (
    <table className="w-full border-collapse font-mono text-[11px] leading-5">
      <tbody>
        {lines.map((line, index) => (
          <DiffLineRow
            key={`${line.old_lineno ?? ""}:${line.new_lineno ?? ""}:${index}`}
            line={line}
          >
            {renderCode(line, index)}
          </DiffLineRow>
        ))}
      </tbody>
    </table>
  );
}

function DiffLineRow({
  line,
  children,
}: {
  line: RenderableFileDiffLine;
  children: ReactNode;
}) {
  const kind = line.kind === "add" || line.kind === "delete" ? line.kind : "context";
  const marker = kind === "add" ? "+" : kind === "delete" ? "-" : " ";
  return (
    <tr
      className={cn(
        "border-0",
        kind === "add" && "bg-diff-added",
        kind === "delete" && "bg-diff-deleted",
      )}
    >
      <td className="w-10 select-none border-r border-border/35 px-1.5 text-right text-muted-foreground">
        {line.old_lineno ?? ""}
      </td>
      <td className="w-10 select-none border-r border-border/35 px-1.5 text-right text-muted-foreground">
        {line.new_lineno ?? ""}
      </td>
      <td
        className={cn(
          "w-5 select-none px-1 text-center",
          kind === "add" && "text-diff-added-foreground",
          kind === "delete" && "text-diff-deleted-foreground",
          kind === "context" && "text-muted-foreground",
        )}
      >
        {marker}
      </td>
      <td className="min-w-[16rem] px-1.5 text-foreground/86">
        <span className="whitespace-pre">{children}</span>
      </td>
    </tr>
  );
}

function trimTrailingLineBreak(node: SyntaxNode): SyntaxNode {
  if (node.type === "text" && typeof node.value === "string") {
    return { ...node, value: node.value.replace(/\n$/, "") };
  }
  if (!node.children?.length) return node;
  const children = [...node.children];
  children[children.length - 1] = trimTrailingLineBreak(children[children.length - 1]!);
  return { ...node, children };
}

function stripConflictingTableClass(node: SyntaxNode): SyntaxNode {
  const className = node.properties?.className;
  const children = node.children?.map(stripConflictingTableClass);
  const hasTableClass = Array.isArray(className) && className.includes("table");

  if (!hasTableClass && !children) return node;

  return {
    ...node,
    ...(hasTableClass
      ? {
          properties: {
            ...node.properties,
            // Tailwind's global `.table` utility changes Prism's inline Markdown
            // table tokens into CSS tables, splitting a single diff line vertically.
            className: className.filter((name) => name !== "table"),
          },
        }
      : {}),
    ...(children ? { children } : {}),
  };
}
