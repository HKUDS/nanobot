import type { ContextGraph, ContextGraphNode, ContextInspection, ContextSnapshot, UIMessage, UIModelRequestSnapshot } from "@/lib/types";

export function isContextGraph(value: unknown): value is ContextGraph {
  if (!value || typeof value !== "object") return false;
  const graph = value as Record<string, unknown>;
  if (!Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) return false;
  if (!graph.nodes.every((n: unknown) => {
    if (!n || typeof n !== "object") return false;
    const node = n as Record<string, unknown>;
    return typeof node.path === "string" && typeof node.name === "string"
      && (node.state === "loaded" || node.state === "discovered")
      && typeof node.tokens === "number" && Number.isFinite(node.tokens) && node.tokens >= 0;
  })) return false;
  const paths = new Set(graph.nodes.map((n: ContextGraphNode) => n.path));
  return graph.edges.every((e: unknown) => {
    if (!e || typeof e !== "object") return false;
    const edge = e as Record<string, unknown>;
    return typeof edge.source === "string" && typeof edge.target === "string"
      && paths.has(edge.source) && paths.has(edge.target);
  });
}

export function isContextInspection(value: unknown, validateGraph: typeof isContextGraph = isContextGraph): value is ContextInspection {
  return typeof value === "object" && value !== null
    && "graph" in value && validateGraph(value.graph)
    && "estimated_tokens" in value && typeof value.estimated_tokens === "number"
    && Number.isFinite(value.estimated_tokens) && value.estimated_tokens >= 0
    && "context_window_tokens" in value && typeof value.context_window_tokens === "number"
    && Number.isFinite(value.context_window_tokens) && value.context_window_tokens > 0;
}

export function composerContextSnapshots(
  messages: UIMessage[], requests: ReadonlyMap<string, UIModelRequestSnapshot>,
): ContextSnapshot[] {
  const boundary = messages.filter((message) => message.compaction?.phase === "succeeded").at(-1);
  const baseline = boundary?.compaction?.contextSnapshot;
  const snapshots = Array.from(requests.entries()).sort((a, b) => a[1].createdAt - b[1].createdAt)
    .flatMap(([turnId, request]) => (request.contextSnapshots ?? []).filter((snapshot) => {
      if (!boundary) return true;
      if (turnId === boundary.turnId) {
        return snapshot.turnSeq !== undefined && boundary.compaction?.turnSeq !== undefined
          && snapshot.turnSeq > boundary.compaction.turnSeq;
      }
      return request.createdAt > boundary.createdAt;
    }));
  return [...(baseline ? [baseline] : []), ...snapshots];
}
