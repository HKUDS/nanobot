import type { GraphPosition } from "@/lib/context-graph-layout";
import type { GraphPresentation } from "./graph-presentation";

type RGB = readonly [number, number, number];
export interface GraphPalette { background: RGB; foreground: string; muted: RGB; font: string; labels: Map<string, string> }
interface GraphCamera { x: number; y: number; k: number }
const orange: RGB = [249, 115, 22];
const blend = (a: RGB, b: RGB, amount: number): RGB => [a[0] + (b[0] - a[0]) * amount, a[1] + (b[1] - a[1]) * amount, a[2] + (b[2] - a[2]) * amount];
const rgb = (value: RGB) => `rgb(${value.map(Math.round).join(" ")})`;
export function readGraphPalette(element: HTMLElement): GraphPalette {
  const style = getComputedStyle(element);
  const parse = (color: string): RGB => {
    const values = color.match(/[\d.]+/g)?.map(Number) ?? [];
    return [values[0] ?? 0, values[1] ?? 0, values[2] ?? 0];
  };
  return { background: parse(style.backgroundColor), muted: parse(style.color), foreground: getComputedStyle(element.parentElement!).color, font: `10px ${style.fontFamily}`, labels: new Map() };
}

export function fitGraphLabel(name: string, measure: (text: string) => number, maxWidth = 128): string {
  if (measure(name) <= maxWidth) return name;
  const characters = Array.from(name);
  let start = 0, end = characters.length;
  while (start < end) {
    const middle = Math.ceil((start + end) / 2);
    if (measure(`${characters.slice(0, middle).join("")}…`) <= maxWidth) start = middle;
    else end = middle - 1;
  }
  return `${characters.slice(0, start).join("")}…`;
}

/** One bitmap paint; neither force ticks nor camera movement mutate per-node DOM. */
export function paintGraph(context: CanvasRenderingContext2D, frame: GraphPresentation, positions: ReadonlyMap<string, GraphPosition>,
  view: GraphCamera, palette: GraphPalette, highlighted: string | null, focused: string | null,
  width: number, height: number, pixelRatio: number, discovered: ReadonlySet<string>) {
  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  context.clearRect(0, 0, width, height);
  const groups = new Map<string, { opacity: number; dashed: boolean; edges: GraphPresentation["edges"] }>();
  for (const edge of frame.edges) {
    const opacity = edge.presence * edge.emphasis * 0.7;
    const dashed = discovered.has(edge.target);
    const key = `${opacity}:${dashed}`;
    let group = groups.get(key);
    if (!group) { group = { opacity, dashed, edges: [] }; groups.set(key, group); }
    group.edges.push(edge);
  }
  context.strokeStyle = "#f97316";
  context.lineWidth = 1;
  for (const group of groups.values()) {
    context.globalAlpha = group.opacity;
    context.setLineDash(group.dashed ? [3, 5] : []);
    context.beginPath();
    for (const edge of group.edges) {
      const a = positions.get(edge.source), b = positions.get(edge.target);
      if (!a || !b) continue;
      context.moveTo(a.x * view.k + view.x, a.y * view.k + view.y);
      context.lineTo(b.x * view.k + view.x, b.y * view.k + view.y);
    }
    context.stroke();
  }
  context.setLineDash([]);
  context.font = palette.font;
  context.textAlign = "center";
  context.textBaseline = "middle";
  for (const node of frame.nodes) {
    const point = positions.get(node.path);
    if (!point) continue;
    const x = point.x * view.k + view.x, y = point.y * view.k + view.y;
    const alpha = node.presence * node.emphasis;
    const color = blend(palette.muted, orange, node.focus);
    context.globalAlpha = alpha;
    context.strokeStyle = rgb(color);
    context.fillStyle = rgb(blend(palette.background, color, node.loaded));
    context.beginPath(); context.arc(x, y, node.radius - 0.5, 0, Math.PI * 2); context.fill(); context.stroke();
    if (node.path === focused) {
      context.strokeStyle = palette.foreground;
      context.lineWidth = 2;
      context.beginPath(); context.roundRect(x - 22, y - 22, 44, 44, 4); context.stroke();
      context.lineWidth = 1;
    }
    // Introduce newly loaded files for one second, then fade to the usual zoom visibility.
    const labelOpacity = node.path === highlighted ? 1 : Math.max(0, Math.min(1, (view.k - 1) / 3.75), Math.min(1, node.labelRemaining / 600));
    if (labelOpacity > 0) {
      context.globalAlpha = alpha * labelOpacity;
      context.fillStyle = palette.foreground;
      let label = palette.labels.get(node.name);
      if (label === undefined) {
        label = fitGraphLabel(node.name, (text) => context.measureText(text).width);
        palette.labels.set(node.name, label);
      }
      context.fillText(label, x, y + 24);
    }
  }
  context.globalAlpha = 1;
}
