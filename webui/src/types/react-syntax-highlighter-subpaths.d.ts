declare module "react-syntax-highlighter/dist/esm/prism-async-light" {
  import * as React from "react";
  import type { SyntaxHighlighterProps } from "react-syntax-highlighter";

  export default class SyntaxHighlighter extends React.Component<SyntaxHighlighterProps> {
    static registerLanguage(name: string, func: unknown): void;
  }
}

declare module "react-syntax-highlighter/dist/esm/styles/prism/one-dark" {
  import type * as React from "react";

  const style: { [key: string]: React.CSSProperties };
  export default style;
}

declare module "react-syntax-highlighter/dist/esm/styles/prism/one-light" {
  import type * as React from "react";

  const style: { [key: string]: React.CSSProperties };
  export default style;
}
