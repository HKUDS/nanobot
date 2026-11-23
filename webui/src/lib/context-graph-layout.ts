import type { ContextGraph, ContextGraphNode } from "@/lib/types";
import { forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY, type SimulationNodeDatum } from "d3-force";

export interface GraphPosition { x: number; y: number }

export interface GraphParticle extends SimulationNodeDatum { path: string; radius: number; x: number; y: number }

// Obsidian display settings: center 0.52, repel 10, link strength 1, distance 250.
// Use 0.36 world units per reference unit to fit the compact panel.
const GRAPH_SCALE = 0.36;
const CENTER_STRENGTH = (Math.pow(0.01, 1 - 0.52) - 0.01) / 0.99;

/** Keep mutable simulation particles separate from immutable request snapshots. */
export function createGraphSimulation(graph: ContextGraph, previous: ReadonlyMap<string, GraphPosition>, width: number, height: number) {
  const simulation = forceSimulation<GraphParticle>()
    .alphaDecay(1 - Math.pow(0.001, 1 / 300)).velocityDecay(0.4)
    // Force order matters: each force reads velocities written by the previous one.
    .force("x", forceX<GraphParticle>(width / 2).strength(CENTER_STRENGTH))
    .force("y", forceY<GraphParticle>(height / 2).strength(CENTER_STRENGTH))
    .force("link", forceLink<GraphParticle, { source: string; target: string }>().id((node) => node.path).distance(250 * GRAPH_SCALE))
    .force("charge", forceManyBody<GraphParticle>().strength(-Math.pow(10, 3) * GRAPH_SCALE ** 2))
    .force("collision", forceCollide<GraphParticle>().radius(60 * GRAPH_SCALE).strength(0.5));
  updateGraphSimulation(simulation, graph, previous, width, height);
  return simulation;
}

export function updateGraphSimulation(simulation: ReturnType<typeof forceSimulation<GraphParticle>>, graph: ContextGraph,
  previous: ReadonlyMap<string, GraphPosition>, width: number, height: number) {
  const existing = new Map(simulation.nodes().map((node) => [node.path, node]));
  const placed = new Map<string, GraphPosition>(existing);
  const addedCount = graph.nodes.filter((node) => !existing.has(node.path)).length;
  const area = (60 * GRAPH_SCALE) ** 2 * addedCount;
  const outerRadius = Math.max(0, ...[...existing.values()].map((node) => Math.hypot(node.x - width / 2, node.y - height / 2)));
  const ringWidth = Math.sqrt(area / Math.PI + outerRadius ** 2) - outerRadius;
  const spread = Math.sqrt(area);
  const adjacent = new Map<string, string[]>();
  for (const edge of graph.edges) {
    const sources = adjacent.get(edge.source) ?? [];
    sources.push(edge.target); adjacent.set(edge.source, sources);
    const targets = adjacent.get(edge.target) ?? [];
    targets.push(edge.source); adjacent.set(edge.target, targets);
  }
  const nodes = graph.nodes.map((node): GraphParticle => {
    const retained = existing.get(node.path);
    if (retained) return retained;
    const neighbours = (adjacent.get(node.path) ?? [])
      .map((path) => placed.get(path)).filter((point): point is GraphPosition => !!point);
    let position = previous.get(node.path);
    if (!position && neighbours.length) position = {
      x: neighbours.reduce((sum, point) => sum + point.x, 0) / neighbours.length + (Math.random() - 0.5) * spread,
      y: neighbours.reduce((sum, point) => sum + point.y, 0) / neighbours.length + (Math.random() - 0.5) * spread,
    };
    if (!position) {
      const angle = Math.random() * Math.PI * 2;
      const radius = outerRadius + Math.sqrt(Math.random()) * ringWidth;
      position = { x: width / 2 + Math.cos(angle) * radius, y: height / 2 + Math.sin(angle) * radius };
    }
    placed.set(node.path, position);
    return { path: node.path, radius: 60 * GRAPH_SCALE, ...position };
  });
  const link = simulation.force<ReturnType<typeof forceLink<GraphParticle, { source: string; target: string }>>>("link")!;
  // Clear old links before removing particles; D3 initializes forces inside nodes().
  link.links([]);
  simulation.nodes(nodes);
  link.links(graph.edges.map((edge) => ({ ...edge })));
  simulation.force<ReturnType<typeof forceCollide<GraphParticle>>>("collision")!.radius((node) => node.radius);
  simulation.force<ReturnType<typeof forceX<GraphParticle>>>("x")!.x(width / 2);
  simulation.force<ReturnType<typeof forceY<GraphParticle>>>("y")!.y(height / 2);
}

/** Preserve the simulation steps while bounding work per animated frame. */
export function advanceGraphSimulation(simulation: ReturnType<typeof createGraphSimulation>, elapsedMs: number, budgetMs = 8) {
  // Advance physical time independently of painting cadence, but never spend an
  // unbounded frame catching up after a hidden tab or a busy main thread.
  const steps = Math.max(1, Math.floor(Math.min(elapsedMs, 100) * 240 / 1000));
  const deadline = performance.now() + budgetMs;
  for (let step = 0; step < steps; step++) {
    if (simulation.alpha() <= simulation.alphaMin() && simulation.alphaTarget() === 0) break;
    simulation.tick();
    if (performance.now() >= deadline) break;
  }
}

/** Finish the same finite layout in short slices without painting intermediate positions. */
export function startGraphSettlement(simulation: ReturnType<typeof createGraphSimulation>) {
  simulation.stop().alpha(1).alphaTarget(0);
  let remaining = Math.ceil(Math.log(simulation.alphaMin()) / Math.log(1 - simulation.alphaDecay()));
  return (budgetMs = 4) => {
    const deadline = performance.now() + budgetMs;
    do { simulation.tick(); remaining--; } while (remaining > 0 && performance.now() < deadline);
    if (remaining > 0) return false;
    for (const node of simulation.nodes()) { node.vx = 0; node.vy = 0; }
    simulation.alpha(0);
    return true;
  };
}

export function nodeRadius(node: ContextGraphNode): number {
  return node.state === "discovered" ? 3.5 : Math.max(4, Math.min(12.5, Math.sqrt(node.tokens) * 0.215));
}
