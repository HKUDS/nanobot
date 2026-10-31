import type { SyntaxHighlighterProps } from "react-syntax-highlighter";
import createElement from "react-syntax-highlighter/dist/esm/create-element";

type RowsProps = Parameters<NonNullable<SyntaxHighlighterProps["renderer"]>>[0];

export function WrappedCodeRows({ rows, ...props }: RowsProps) {
  return rows.map((row, index) => {
    const [lineNumber, ...content] = row.children!;
    return createElement({
      ...props,
      key: index,
      node: {
        ...row,
        children: [lineNumber, {
          type: "element",
          tagName: "span",
          properties: { className: ["min-w-0", "flex-1"] },
          children: content,
        }],
      },
    });
  });
}
