import { Component, lazy, Suspense, useContext, type ReactNode } from "react";

import { CodeBlock } from "@/components/CodeBlock";
import { DiagramLoadRetry } from "./DiagramLoadRetry";
import { MarkdownCodeContext } from "./context";

const loadMermaidBlock = () => import("./MermaidBlock");

class DiagramBoundary extends Component<{ code: string; source: (action?: ReactNode) => ReactNode }> {
  state = { failed: false, Renderer: lazy(loadMermaidBlock) };
  static getDerivedStateFromError() { return { failed: true }; }
  retry = () => this.setState({ failed: false, Renderer: lazy(loadMermaidBlock) });
  render() {
    const { Renderer, failed } = this.state;
    const { source, code } = this.props;
    if (failed) return source(<DiagramLoadRetry onRetry={this.retry} />);
    return <Suspense fallback={source()}><Renderer source={code} /></Suspense>;
  }
}

export function MarkdownCodeBlock({ code, language, closed }: { code: string; language?: string; closed: boolean }) {
  const { streaming, highlight } = useContext(MarkdownCodeContext);
  const source = (action?: ReactNode) => <CodeBlock copyAdjacentAction={action} language={language || "text"} code={code} className="my-3" highlight={highlight} showLineNumbers={code.includes("\n")} />;
  if (language?.toLowerCase() !== "mermaid") return source();
  if (streaming && !closed) return <div aria-busy>{source()}</div>;
  return <DiagramBoundary key={code} code={code} source={source} />;
}
