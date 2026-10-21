import { Component, lazy, Suspense, useContext, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { CodeBlock } from "@/components/CodeBlock";
import { MarkdownCodeContext } from "./context";

const MermaidBlock = lazy(() => import("./MermaidBlock"));

class DiagramBoundary extends Component<{ children: ReactNode; fallback: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

export function MarkdownCodeBlock({ code, language }: { code: string; language?: string }) {
  const { t } = useTranslation();
  const { streaming, highlight } = useContext(MarkdownCodeContext);
  const source = <CodeBlock language={language || "text"} code={code} className="my-3" highlight={highlight} showLineNumbers={code.includes("\n")} />;
  if (language?.toLowerCase() !== "mermaid") return source;
  const preparing = <div aria-busy={streaming}>
    <p className="my-1 text-xs text-muted-foreground" role="status">{t("diagram.preparing")}</p>{source}
  </div>;
  if (streaming) return preparing;
  return <DiagramBoundary key={code} fallback={<><p className="text-xs text-muted-foreground" role="status">{t("diagram.errors.load")}</p>{source}</>}>
    <Suspense fallback={preparing}><MermaidBlock source={code} /></Suspense>
  </DiagramBoundary>;
}
