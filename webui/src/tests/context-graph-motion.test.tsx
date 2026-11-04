import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { createGraphSimulation, updateGraphSimulation } from "@/lib/context-graph";
import { useGraphPresentation } from "@/components/thread/useGraphPresentation";
import type { ContextGraph } from "@/lib/types";

const first: ContextGraph = { nodes: [{ path: "a.md", name: "a.md", state: "loaded", tokens: 100 }], edges: [] };
const next: ContextGraph = { nodes: [...first.nodes, { path: "b.md", name: "b.md", state: "discovered", tokens: 0 }],
  edges: [{ source: "a.md", target: "b.md" }] };

describe("context graph continuity", () => {
  it("retains existing particles and grows a linked node near its neighbour", () => {
    const sim = createGraphSimulation(first, new Map(), 600, 300).stop();
    const original = sim.nodes()[0];
    original.x = 100; original.y = 100; original.vx = 2;
    updateGraphSimulation(sim, next, new Map(), 600, 300);
    expect(sim.nodes()[0]).toBe(original);
    expect(original.vx).toBe(2);
    expect(Math.hypot(sim.nodes()[1].x - 100, sim.nodes()[1].y - 100)).toBeLessThan(20);
    const cache = new Map(sim.nodes().map((node) => [node.path, { x: node.x, y: node.y }]));
    updateGraphSimulation(sim, first, cache, 600, 300);
    updateGraphSimulation(sim, next, cache, 600, 300);
    expect(sim.nodes()[1].x).toBe(cache.get("b.md")!.x);
    expect(sim.nodes()[1].y).toBe(cache.get("b.md")!.y);
    sim.stop();
  });

  it("reverses an in-flight exit from its current opacity when scrubbing back", async () => {
    const { result, rerender } = renderHook(({ graph }) => useGraphPresentation(graph, null, false), { initialProps: { graph: next } });
    await waitFor(() => expect(result.current.nodes.find((node) => node.path === "b.md")!.presence).toBeGreaterThan(0.7));
    rerender({ graph: first });
    await waitFor(() => expect(result.current.nodes.find((node) => node.path === "b.md")!.presence).toBeLessThan(0.5));
    const fading = result.current.nodes.find((node) => node.path === "b.md")!.presence;
    expect(fading).toBeGreaterThan(0);
    rerender({ graph: next });
    expect(result.current.nodes.find((node) => node.path === "b.md")!.presence).toBeCloseTo(fading);
    await waitFor(() => expect(result.current.nodes.find((node) => node.path === "b.md")!.presence).toBeGreaterThan(0.9));
    expect(result.current.edges).toHaveLength(1);
  });
});
