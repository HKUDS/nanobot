import { describe, expect, it } from "vitest";
import { createGraphSimulation, updateGraphSimulation, advanceGraphSimulation, startGraphSettlement } from "@/lib/context-graph-layout";
import { createGraphPresentation } from "@/components/thread/graph-presentation";
import type { ContextGraph } from "@/lib/types";

const first: ContextGraph = { nodes: [{ path: "a.md", name: "a.md", state: "loaded", tokens: 100 }], edges: [] };
const next: ContextGraph = { nodes: [...first.nodes, { path: "b.md", name: "b.md", state: "discovered", tokens: 0 }],
  edges: [{ source: "a.md", target: "b.md" }] };

describe("context graph continuity", () => {
  it("reintroduces a loaded filename when fast replay reverses its unfinished exit", () => {
    const presentation = createGraphPresentation();
    const loaded: ContextGraph = { nodes: [{ path: "loop.py", name: "loop.py", state: "loaded", tokens: 200 }], edges: [] };
    presentation.update(loaded, null);
    presentation.advance(2000, true);
    presentation.update({ nodes: [], edges: [] }, null);
    presentation.advance(200, false);
    const exiting = presentation.frame.nodes[0];
    expect(exiting.presence).toBeGreaterThan(0);
    expect(exiting.labelRemaining).toBe(0);
    presentation.update(loaded, null);
    expect(presentation.frame.nodes[0]).toBe(exiting);
    expect(exiting.labelRemaining).toBe(1600);
    presentation.advance(300, false);
    presentation.update(loaded, "loop.py");
    expect(exiting.labelRemaining).toBe(1300);
  });

  it("briefly introduces new labels without restarting existing labels on graph or focus updates", () => {
    const presentation = createGraphPresentation();
    presentation.update(first, null);
    presentation.advance(1000, false);
    expect(presentation.frame.nodes[0].labelRemaining).toBe(600);
    presentation.update(next, "a.md");
    presentation.advance(300, false);
    expect(presentation.frame.nodes.map((node) => node.labelRemaining)).toEqual([300, 0]);
    const loaded: ContextGraph = { ...next, nodes: next.nodes.map((node) => ({ ...node, state: "loaded" })) };
    presentation.update(loaded, null);
    presentation.advance(300, false);
    expect(presentation.frame.nodes.map((node) => node.labelRemaining)).toEqual([0, 1300]);
    presentation.update(loaded, "b.md");
    presentation.advance(300, false);
    expect(presentation.frame.nodes[1].labelRemaining).toBe(1000);
    // Replaying an earlier, unloaded state ends the automatic label reveal.
    presentation.update(next, null);
    expect(presentation.advance(0, true).moving).toBe(false);
    expect(presentation.frame.nodes.map((node) => node.labelRemaining)).toEqual([0, 0]);
  });

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

  it("settles reduced motion in slices to the same finite layout", () => {
    const previous = new Map([["a.md", { x: 50, y: 80 }], ["b.md", { x: 150, y: 130 }]]);
    const reference = createGraphSimulation(next, previous, 600, 300).stop();
    const sliced = createGraphSimulation(next, previous, 600, 300).stop();
    reference.alpha(1).alphaTarget(0).tick(300);
    const advance = startGraphSettlement(sliced);
    expect(advance(0)).toBe(false);
    let slices = 1;
    while (!advance(0)) slices++;
    expect(slices).toBe(299);
    expect(sliced.nodes().map(({ x, y }) => ({ x, y }))).toEqual(reference.nodes().map(({ x, y }) => ({ x, y })));
    expect(sliced.nodes().every((node) => node.vx === 0 && node.vy === 0)).toBe(true);
    expect(sliced.alpha()).toBe(0);
  });

  it("reaches the same layout at slow and fast paint rates without stretching physical time", () => {
    const previous = new Map([["a.md", { x: 50, y: 80 }], ["b.md", { x: 150, y: 130 }]]);
    const simulate = (frameMs: number) => {
      const sim = createGraphSimulation(next, previous, 600, 300).stop();
      let elapsed = 0;
      while (sim.alpha() > sim.alphaMin()) {
        advanceGraphSimulation(sim, frameMs, Infinity);
        elapsed += frameMs;
      }
      return { elapsed, positions: sim.nodes().map(({ x, y }) => ({ x, y })) };
    };
    const fast = simulate(1000 / 60), slow = simulate(50);
    expect(slow.positions).toEqual(fast.positions);
    expect(Math.abs(slow.elapsed - fast.elapsed)).toBeLessThan(51);
    // A constrained frame still makes progress, rather than queuing an unbounded catch-up.
    const bounded = createGraphSimulation(next, previous, 600, 300).stop();
    const reference = createGraphSimulation(next, previous, 600, 300).stop().tick();
    advanceGraphSimulation(bounded, 10_000, 0);
    expect(bounded.nodes().map(({ x, y }) => ({ x, y }))).toEqual(reference.nodes().map(({ x, y }) => ({ x, y })));
  });

  it("reverses an in-flight exit from its current opacity when a graph returns", () => {
    const presentation = createGraphPresentation();
    presentation.update(next, null);
    for (let index = 0; index < 20; index++) presentation.advance(1000 / 60, false);
    const node = () => presentation.frame.nodes.find((item) => item.path === "b.md")!;
    expect(node().presence).toBeGreaterThan(0.7);
    presentation.update(first, null);
    for (let index = 0; index < 8; index++) presentation.advance(1000 / 60, false);
    const fading = node().presence;
    expect(fading).toBeGreaterThan(0);
    expect(fading).toBeLessThan(0.5);
    presentation.update(next, null);
    expect(node().presence).toBe(fading);
    for (let index = 0; index < 20; index++) presentation.advance(1000 / 60, false);
    expect(node().presence).toBeGreaterThan(0.9);
    expect(presentation.frame.edges).toHaveLength(1);
  });
});
