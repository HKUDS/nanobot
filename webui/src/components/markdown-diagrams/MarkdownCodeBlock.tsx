import { Component, lazy, Suspense, useContext, type ReactNode } from "react";

import { CodeBlock } from "@/components/CodeBlock";
import { DiagramLoadRetry } from "./DiagramLoadRetry";
import { MarkdownCodeContext } from "./context";

const loadMermaidBlock = () => import("./MermaidBlock");

class DiagramBoundary extends Component<{ code: string; source: ReactNode }> {
  state = { failed: false, Renderer: lazy(loadMermaidBlock) };
  static getDerivedStateFromError() { return { failed: true }; }
  retry = () => this.setState({ failed: false, Renderer: lazy(loadMermaidBlock) });
  render() {
    const { Renderer, failed } = this.state;
    const { source, code } = this.props;
    if (failed) return <><DiagramLoadRetry onRetry={this.retry} />{source}</>;
    return <Suspense fallback={source}><Renderer source={code} /></Suspense>;
  }
}

export function MarkdownCodeBlock({ code, language, closed }: { code: string; language?: string; closed: boolean }) {
  const { streaming, highlight } = useContext(MarkdownCodeContext);
  const source = <CodeBlock language={language || "text"} code={code} className="my-3" highlight={highlight} showLineNumbers={code.includes("\n")} />;
  if (language?.toLowerCase() !== "mermaid") return source;
  if (streaming && !closed) return <div aria-busy>{source}</div>;
  return <DiagramBoundary key={code} code={code} source={source} />;
}
