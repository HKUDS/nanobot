import { Suspense, lazy, type ReactNode } from "react";
import type { SyntaxHighlighterProps } from "react-syntax-highlighter";

import { useThemeValue } from "@/hooks/useTheme";
import type { RenderableFileDiffLine } from "@/lib/file-diff";
import { cn } from "@/lib/utils";

interface DiffSyntaxHighlightProps {
  language: string;
  lines: RenderableFileDiffLine[];
}

interface LoadedDiffSyntaxHighlightProps extends DiffSyntaxHighlightProps {
  isDark: boolean;
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
    { default: oneDark },
    { default: oneLight },
  ] = await Promise.all([
    import("react-syntax-highlighter/dist/esm/prism-async-light"),
    import("react-syntax-highlighter/dist/esm/create-element"),
    import("react-syntax-highlighter/dist/esm/styles/prism/one-dark"),
    import("react-syntax-highlighter/dist/esm/styles/prism/one-light"),
  ]);
  return {
    default: function LoadedDiffSyntaxHighlight({
      language,
      lines,
      isDark,
    }: LoadedDiffSyntaxHighlightProps) {
      const theme = isDark ? oneDark : oneLight;
      const code = lines.map((line) => line.content || " ").join("\n");
      return (
        <SyntaxHighlighter
          language={language}
          style={theme}
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
  const isDark = useThemeValue() === "dark";
  return (
    <Suspense fallback={<PlainDiffLines lines={lines} />}>
      <LazyDiffSyntaxHighlight language={language} lines={lines} isDark={isDark} />
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
        kind === "add" && "bg-emerald-500/[0.09] dark:bg-emerald-300/[0.11]",
        kind === "delete" && "bg-rose-500/[0.09] dark:bg-rose-300/[0.11]",
      )}
    >
      <td className="w-10 select-none border-r border-border/35 px-1.5 text-right text-muted-foreground/55">
        {line.old_lineno ?? ""}
      </td>
      <td className="w-10 select-none border-r border-border/35 px-1.5 text-right text-muted-foreground/55">
        {line.new_lineno ?? ""}
      </td>
      <td
        className={cn(
          "w-5 select-none px-1 text-center",
          kind === "add" && "text-emerald-600/80 dark:text-emerald-300/85",
          kind === "delete" && "text-rose-600/80 dark:text-rose-300/85",
          kind === "context" && "text-muted-foreground/45",
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
