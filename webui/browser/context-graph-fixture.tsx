import { useState } from "react";
import { createRoot } from "react-dom/client";
import { ContextInspector } from "@/components/thread/ContextInspector";
import { ComposerUsagePopover } from "@/components/thread/ComposerUsagePopover";
import { TooltipProvider } from "@/components/ui/tooltip";
import { initializeI18n } from "@/i18n";
import type { ContextSnapshot } from "@/lib/types";
import "../src/globals.css";

const snapshots: ContextSnapshot[] = [
  { id: "first", contextWindowTokens: 10000, usage: { prompt_tokens: 1000 }, graph: {
    nodes: [{ path: "/a.md", name: "a.md", state: "loaded", tokens: 100 }], edges: [],
  } },
  { id: "second", contextWindowTokens: 10000, usage: { prompt_tokens: 2000 }, graph: {
    nodes: [{ path: "/a.md", name: "a.md", state: "loaded", tokens: 100 }, { path: "/b.md", name: "b.md", state: "discovered", tokens: 0 }],
    edges: [{ source: "/a.md", target: "/b.md" }],
  } },
];
const largeNodes = Array.from({ length: 500 }, (_, index) => ({ path: `/file-${index}.md`, name: `file-${index}.md`, state: "loaded" as const, tokens: 100 }));
const large: ContextSnapshot[] = [{ id: "large", contextWindowTokens: 100000, usage: { prompt_tokens: 50000 }, graph: {
  nodes: largeNodes, edges: largeNodes.slice(1).map((node, index) => ({ source: largeNodes[Math.floor(index / 2)].path, target: node.path })),
} }];
function Fixture() {
  const [showLarge, setShowLarge] = useState(false);
  const [pythonLoaded, setPythonLoaded] = useState(false);
  const frames = new URLSearchParams(location.search).has("single") ? snapshots.map((snapshot) => ({ ...snapshot, graph: snapshots[0].graph })) : snapshots;
  const inspectedFrames = pythonLoaded ? [...frames, { ...frames[1], id: "python", graph: {
    nodes: [...frames[1].graph.nodes, { path: "/worker.py", name: "worker.py", state: "loaded" as const, tokens: 200 }], edges: frames[1].graph.edges,
  } }] : frames;
  const [opened, setOpened] = useState("");
  const [sidebarHost, setSidebarHost] = useState<HTMLElement | null>(null);
  if (new URLSearchParams(location.search).has("drawer")) return <main ref={setSidebarHost} className="relative" style={{ height: "100dvh" }}>
    <ComposerUsagePopover sidebarHost={sidebarHost} context={null} rounds={[]} snapshots={frames} onOpenFile={setOpened} />
    <output>{opened}</output>
  </main>;
  return <main className="mx-auto max-w-2xl p-4"><ContextInspector context={null} rounds={[]} snapshots={showLarge ? large : inspectedFrames} onOpenFile={setOpened} /><output>{opened}</output>{new URLSearchParams(location.search).has("pair") && <section aria-label="Second graph"><ContextInspector context={null} rounds={[]} snapshots={frames} /></section>}<button onClick={() => setShowLarge(true)}>Load 500 nodes</button><button onClick={() => setPythonLoaded(true)}>Read Python file</button></main>;
}
await initializeI18n();
createRoot(document.getElementById("root")!).render(<TooltipProvider><Fixture /></TooltipProvider>);
