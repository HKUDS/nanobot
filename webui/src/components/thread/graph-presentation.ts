import { nodeRadius } from "@/lib/context-graph-layout";
import type { ContextGraph, ContextGraphNode } from "@/lib/types";

type PresentedNode = ContextGraphNode & { presence: number; emphasis: number; focus: number; radius: number; loaded: number; labelRemaining: number };
type PresentedEdge = ContextGraph["edges"][number] & { presence: number; emphasis: number };
export type GraphPresentation = { nodes: PresentedNode[]; edges: PresentedEdge[] };
const edgeKey = (edge: ContextGraph["edges"][number]) => JSON.stringify([edge.source, edge.target]);

/** Mutable animation state; request graphs remain immutable. The caller owns its clock. */
export function createGraphPresentation() {
  const nodes = new Map<string, PresentedNode>();
  const edges = new Map<string, PresentedEdge>();
  let wanted = new Set<string>();
  let wantedEdges = new Set<string>();
  let related = new Set<string | null>();
  let highlighted: string | null = null;
  let frame: GraphPresentation = { nodes: [], edges: [] };
  let moving = false;
  return {
    get frame() { return frame; },
    update(graph: ContextGraph, focus: string | null) {
      highlighted = focus;
      const previouslyWanted = wanted;
      wanted = new Set(graph.nodes.map((node) => node.path));
      wantedEdges = new Set(graph.edges.map(edgeKey));
      related = new Set([focus]);
      for (const edge of graph.edges) {
        if (edge.source === focus) related.add(edge.target);
        if (edge.target === focus) related.add(edge.source);
      }
      for (const node of graph.nodes) {
        const previous = nodes.get(node.path);
        if (previous) {
          if (node.state !== "loaded") previous.labelRemaining = 0;
          // A replay can reintroduce a node before its exit animation removes it.
          else if (previous.state !== "loaded" || !previouslyWanted.has(node.path)) previous.labelRemaining = 1600;
          Object.assign(previous, node);
        }
        else nodes.set(node.path, { ...node, presence: 0, emphasis: 1, focus: 0, radius: nodeRadius(node), loaded: Number(node.state === "loaded"), labelRemaining: node.state === "loaded" ? 1600 : 0 });
      }
      for (const edge of graph.edges) if (!edges.has(edgeKey(edge))) edges.set(edgeKey(edge), { ...edge, presence: 0, emphasis: 1 });
      frame = { nodes: [...nodes.values()], edges: [...edges.values()] };
      moving = true;
      return frame;
    },
    advance(elapsed: number, reducedMotion: boolean) {
      if (!moving) return { moving: false, removed: false };
      const amount = reducedMotion ? 1 : 1 - Math.pow(0.9, Math.min(64, Math.max(0, elapsed)) / (1000 / 60));
      moving = false;
      let removed = false;
      const approach = (value: number, target: number) => {
        const next = value + (target - value) * amount;
        if (Math.abs(next - target) < 0.005) return target;
        moving = true;
        return next;
      };
      for (const [path, node] of nodes) {
        // Keep the clock alive after the layout settles so new labels can fade out.
        node.labelRemaining = Math.max(0, node.labelRemaining - Math.max(0, elapsed));
        if (node.labelRemaining > 0) moving = true;
        node.presence = approach(node.presence, wanted.has(path) ? 1 : 0);
        node.emphasis = approach(node.emphasis, highlighted && !related.has(path) ? 0.2 : 1);
        node.focus = approach(node.focus, path === highlighted ? 1 : 0);
        node.radius = approach(node.radius, nodeRadius(node));
        node.loaded = approach(node.loaded, Number(node.state === "loaded"));
        if (!wanted.has(path) && node.presence === 0) { nodes.delete(path); removed = true; }
      }
      for (const [key, edge] of edges) {
        edge.presence = approach(edge.presence, wantedEdges.has(key) ? 1 : 0);
        edge.emphasis = approach(edge.emphasis, highlighted && edge.source !== highlighted && edge.target !== highlighted ? 0.2 : 1);
        if (!wantedEdges.has(key) && edge.presence === 0) { edges.delete(key); removed = true; }
      }
      if (removed) frame = { nodes: [...nodes.values()], edges: [...edges.values()] };
      return { moving, removed };
    },
  };
}
