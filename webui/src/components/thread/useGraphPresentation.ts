import { useEffect, useRef, useState } from "react";
import { nodeRadius } from "@/lib/context-graph";
import type { ContextGraph, ContextGraphNode } from "@/lib/types";

export type PresentedNode = ContextGraphNode & { presence: number; emphasis: number; focus: number; radius: number; loaded: number };
export type PresentedEdge = ContextGraph["edges"][number] & { presence: number; emphasis: number };
export type GraphPresentation = { nodes: PresentedNode[]; edges: PresentedEdge[] };
const edgeKey = (edge: ContextGraph["edges"][number]) => JSON.stringify([edge.source, edge.target]);

/** Time-corrected exponential convergence, including reversals while scrubbing. */
export function useGraphPresentation(graph: ContextGraph, highlighted: string | null, reducedMotion: boolean, onFrame?: (frame: GraphPresentation) => void) {
  const nodes = useRef(new Map<string, PresentedNode>());
  const edges = useRef(new Map<string, PresentedEdge>());
  const [frame, setFrame] = useState<GraphPresentation>({ nodes: [], edges: [] });
  const callback = useRef(onFrame);
  callback.current = onFrame;
  useEffect(() => {
    const wanted = new Set(graph.nodes.map((node) => node.path));
    const wantedEdges = new Set(graph.edges.map(edgeKey));
    const related = new Set([highlighted]);
    for (const edge of graph.edges) {
      if (edge.source === highlighted) related.add(edge.target);
      if (edge.target === highlighted) related.add(edge.source);
    }
    for (const node of graph.nodes) {
      const previous = nodes.current.get(node.path);
      nodes.current.set(node.path, previous ? { ...previous, ...node } : {
        ...node, presence: 0, emphasis: 1, focus: 0, radius: nodeRadius(node), loaded: Number(node.state === "loaded"),
      });
    }
    for (const edge of graph.edges) {
      const key = edgeKey(edge);
      if (!edges.current.has(key)) edges.current.set(key, { ...edge, presence: 0, emphasis: 1 });
    }
    const snapshot = () => ({ nodes: [...nodes.current.values()], edges: [...edges.current.values()] });
    setFrame(snapshot());
    let request = 0;
    let previousTime = performance.now();
    const draw = (time: number) => {
      const amount = reducedMotion ? 1 : 1 - Math.pow(0.9, Math.min(64, Math.max(0, time - previousTime)) / (1000 / 60));
      previousTime = time;
      let moving = false;
      let removed = false;
      const approach = (value: number, target: number) => {
        const next = value + (target - value) * amount;
        if (Math.abs(next - target) < 0.005) return target;
        moving = true;
        return next;
      };
      for (const [path, node] of nodes.current) {
        node.presence = approach(node.presence, wanted.has(path) ? 1 : 0);
        node.emphasis = approach(node.emphasis, highlighted && !related.has(path) ? 0.2 : 1);
        node.focus = approach(node.focus, path === highlighted ? 1 : 0);
        node.radius = approach(node.radius, nodeRadius(node));
        node.loaded = approach(node.loaded, Number(node.state === "loaded"));
        if (!wanted.has(path) && node.presence === 0) { nodes.current.delete(path); removed = true; }
      }
      for (const [key, edge] of edges.current) {
        edge.presence = approach(edge.presence, wantedEdges.has(key) ? 1 : 0);
        edge.emphasis = approach(edge.emphasis, highlighted && edge.source !== highlighted && edge.target !== highlighted ? 0.2 : 1);
        if (!wantedEdges.has(key) && edge.presence === 0) { edges.current.delete(key); removed = true; }
      }
      const next = snapshot();
      callback.current?.(next);
      if (removed) setFrame(next);
      if (moving) request = requestAnimationFrame(draw);
    };
    draw(previousTime);
    return () => cancelAnimationFrame(request);
  }, [graph, highlighted, reducedMotion]);
  return frame;
}
