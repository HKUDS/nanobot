// Worker-only policy for Pele 1.6 image documents. This is NOT an inline-SVG sanitizer.
import { SaxesParser } from "saxes";
import type * as CssTree from "css-tree";
// css-tree publishes these split entry points, but @types/css-tree declares only the barrel.
// @ts-expect-error No declaration for the public parser entry point.
import parse from "css-tree/parser";
// @ts-expect-error No declaration for the public walker entry point.
import walk from "css-tree/walker";
// @ts-expect-error No declaration for the public generator entry point.
import generate from "css-tree/generator";
import {
  MAX_DIMENSION, MAX_PIXELS, OUTPUT_LIMIT,
  type DiagramFailure, type DiagramInput, type DiagramTemplate,
} from "./types";

const parseCss: typeof CssTree.parse = parse;
const walkCss: typeof CssTree.walk = walk;
const generateCss: typeof CssTree.generate = generate;
const SVG_NS = "http://www.w3.org/2000/svg";
const XML_NS = "http://www.w3.org/XML/1998/namespace";
const XMLNS_NS = "http://www.w3.org/2000/xmlns/";
const ELEMENT_LIMIT = 10_000;
const encoder = new TextEncoder();

export class DiagramImageError extends Error {
  constructor(readonly reason: DiagramFailure) {
    super(`Diagram ${reason}`);
  }
}

function fail(reason: DiagramFailure = "policy"): never {
  throw new DiagramImageError(reason);
}

// Reviewed against the published 1.6.0 string renderer, including nested icon geometry.
// Local marker/clip structures are accepted, but never <use>, links, images or paint servers.
const ELEMENTS = new Set([
  "svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
  "text", "tspan", "title", "desc", "defs", "marker", "clipPath",
]);
const ATTRIBUTES = new Set([
  "id", "class", "data-id", "data-icon", "role", "aria-hidden", "aria-roledescription",
  "aria-labelledby", "aria-describedby", "style", "viewBox", "preserveAspectRatio",
  "x", "y", "x1", "x2", "y1", "y2", "cx", "cy", "r", "rx", "ry", "width", "height",
  "dx", "dy", "d", "points", "transform", "pathLength", "markerWidth", "markerHeight",
  "refX", "refY", "orient", "markerUnits", "clipPathUnits",
]);
const NUMERIC_ATTRIBUTES = new Set([
  "x", "y", "x1", "x2", "y1", "y2", "cx", "cy", "r", "rx", "ry", "width", "height",
  "dx", "dy", "pathLength", "markerWidth", "markerHeight", "refX", "refY",
]);
const DRAWING_PROPERTIES = new Set([
  "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-opacity",
  "stroke-dasharray", "stroke-dashoffset", "stroke-linecap", "stroke-linejoin",
  "stroke-miterlimit", "opacity", "color", "rx", "ry", "text-anchor", "text-decoration",
  "dominant-baseline", "alignment-baseline", "visibility", "display", "vector-effect",
  "marker-start", "marker-mid", "marker-end", "clip-path", "clip-rule",
]);
const TYPOGRAPHY_PROPERTIES = new Set([
  "font", "font-family", "font-size", "font-weight", "font-style", "letter-spacing",
  "word-spacing", "text-transform", "direction",
]);
const ROOT_ALIASES: Readonly<Record<string, string>> = {
  "--_bg": "var(--pele-bg,#fff)", "--_fg": "var(--pele-fg,#1f1f1f)",
  "--_m": "var(--pele-muted,#6e6e6e)", "--_l": "var(--pele-line,#1f1f1f)",
  "--_s": "var(--pele-surface,#f3f3f3)", "--_a": "var(--pele-surface-alt,#e6e6e6)",
  "--_b": "var(--pele-border,#8a8a8a)", "--_c": "var(--pele-accent,#5b7bd5)",
  "--_r": "var(--pele-radius,4px)", "--_tw": "var(--pele-title-weight,bold)",
  "--_hw": "var(--pele-heading-weight,bold)", "--_w": "var(--pele-bold-weight,bold)",
};
const VARIABLES = new Set([
  ...Object.keys(ROOT_ALIASES), "--_fm", "--pele-bg", "--pele-fg", "--pele-muted",
  "--pele-line", "--pele-surface", "--pele-surface-alt", "--pele-border", "--pele-accent",
  "--pele-critical", ...Array.from({ length: 8 }, (_, i) => `--pele-series-${i + 1}`),
]);
const FUNCTIONS = new Set([
  "rgb", "rgba", "hsl", "hsla", "hwb", "lab", "lch", "oklab", "oklch", "color",
  "color-mix", "calc", "min", "max", "clamp",
]);
interface Reference { id: string; target: "marker" | "clipPath" }

function css(source: string, context: "value" | "declarationList"): CssTree.CssNode {
  try {
    return parseCss(source, {
      context, parseCustomProperty: true,
      onParseError: () => fail(),
    });
  } catch (error) {
    if (error instanceof DiagramImageError) throw error;
    return fail();
  }
}

function family(source: string): string {
  const ast = css(source, "value");
  if (ast.type !== "Value" || ast.children.isEmpty) fail("capability");
  for (const node of ast.children) {
    if (node.type === "Identifier" && !/^(?:inherit|initial|unset|revert)$/i.test(node.name)) continue;
    if (node.type === "String" && node.value.length > 0) continue;
    if (node.type === "Operator" && node.value === ",") continue;
    fail("capability");
  }
  return generateCss(ast);
}

function fontSize(node: CssTree.CssNode, allowUnitless: boolean): number {
  if (node.type !== "Value" || node.children.size !== 1) return fail("unsupported");
  const size = node.children.first;
  if (size?.type !== "Dimension" && !(allowUnitless && size?.type === "Number")) return fail("unsupported");
  if (size.type === "Dimension" && size.unit !== "px") return fail("unsupported");
  const value = Number(size.value);
  if (!Number.isFinite(value) || value <= 0 || value > 200) return fail("unsupported");
  return value;
}

function typography(
  property: string, value: CssTree.CssNode, root: boolean,
  fonts: DiagramInput["fonts"], attribute: boolean,
): string {
  const text = generateCss(value);
  switch (property) {
    case "font":
      if (!root || text !== `${fonts.size}px sans-serif`) fail("unsupported");
      break;
    case "font-family":
      if (root) {
        const expected = generateCss(css(`var(--pele-font,${fonts.sans})`, "value"));
        if (text !== expected) fail("unsupported");
        return family(fonts.sans);
      }
      // Pele measures its built-in monospace sections with Style.Mono. Author style
      // font-family is NOT measured, even when it happens to name our mono font.
      if (!attribute || text !== "var(--_fm)") fail("unsupported");
      break;
    case "font-size":
      fontSize(value, attribute);
      break;
    case "font-weight":
      if (!["normal", "400", "bold", "700", "var(--_w)", "var(--_hw)", "var(--_tw)"].includes(text)) fail("unsupported");
      break;
    case "font-style":
      if (text !== "normal" && text !== "italic") fail("unsupported");
      break;
    case "letter-spacing":
    case "word-spacing":
      if (text !== "normal") fail("unsupported");
      break;
    case "text-transform":
      if (text !== "none") fail("unsupported");
      break;
    case "direction":
      if (text !== "ltr") fail("unsupported");
  }
  return text;
}

function drawingValue(property: string, value: CssTree.CssNode, refs: Reference[]): string {
  walkCss(value, (node) => {
    if (node.type === "Raw") fail();
    if (node.type === "Url") {
      const target = property === "clip-path" ? "clipPath"
        : property.startsWith("marker-") ? "marker" : fail();
      if (!/^#[A-Za-z0-9_.:-]+$/.test(node.value)) fail();
      refs.push({ id: node.value.slice(1), target });
    }
    if (node.type === "Function") {
      if (node.name === "var") {
        const name = node.children.first;
        if (name?.type !== "Identifier" || !VARIABLES.has(name.name)) fail();
      } else if (!FUNCTIONS.has(node.name.toLowerCase())) fail();
    }
    if ((node.type === "Number" || node.type === "Dimension" || node.type === "Percentage")
      && !Number.isFinite(Number(node.value))) fail("limit");
  });
  return generateCss(value);
}

function style(
  source: string, root: boolean, fonts: DiagramInput["fonts"], refs: Reference[],
): string {
  const ast = css(source, "declarationList");
  if (ast.type !== "DeclarationList") return fail();
  const declarations: string[] = [];
  const properties = new Set<string>();
  for (const declaration of ast.children) {
    if (declaration.type !== "Declaration" || declaration.important) fail();
    const { property, value } = declaration;
    if (root && properties.has(property)) fail();
    properties.add(property);
    let accepted: string;
    if (property === "--_fm") {
      if (!root || generateCss(value) !== generateCss(css(`var(--pele-font-mono,${fonts.mono})`, "value"))) fail("unsupported");
      accepted = family(fonts.mono);
    } else if (Object.hasOwn(ROOT_ALIASES, property)) {
      if (!root || generateCss(value) !== ROOT_ALIASES[property]) fail();
      // Font weights and radius are layout constants, never theme-controlled values.
      accepted = property === "--_r" ? "4px"
        : ["--_tw", "--_hw", "--_w"].includes(property) ? "bold" : generateCss(value);
    } else if (TYPOGRAPHY_PROPERTIES.has(property)) {
      accepted = typography(property, value, root, fonts, false);
    } else if (DRAWING_PROPERTIES.has(property)) {
      accepted = drawingValue(property, value, refs);
    } else if (root && ((property === "max-width" && generateCss(value) === "100%")
      || (property === "height" && generateCss(value) === "auto"))) {
      accepted = generateCss(value);
    } else fail();
    declarations.push(`${property}:${accepted}`);
  }
  if (root) {
    for (const required of [
      "--_bg", "--_fg", "--_m", "--_l", "--_s", "--_a", "--_b", "--_c", "--_fm",
      "font", "font-family", "letter-spacing", "word-spacing", "text-transform", "direction",
    ]) if (!properties.has(required)) fail();
  }
  return declarations.join(";");
}

const NUMBER = /[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?/g;
function numbers(value: string, letters = ""): number[] {
  if (new RegExp(`[^\\s,\\d.eE+\\-${letters}]`).test(value)) fail();
  const values = Array.from(value.matchAll(NUMBER), (match) => Number(match[0]));
  if (values.length === 0 || values.some((value) => !Number.isFinite(value))) fail("limit");
  return values;
}
function dimension(value: string | undefined): number {
  if (!value || !/^(?:\d+(?:\.\d*)?|\.\d+)$/.test(value)) return fail("limit");
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0 || number > MAX_DIMENSION) return fail("limit");
  return number;
}
function geometry(name: string, value: string): void {
  if (NUMERIC_ATTRIBUTES.has(name)) {
    const values = numbers(value);
    if (values.length !== 1) fail();
    if (["r", "rx", "ry", "width", "height", "markerWidth", "markerHeight", "pathLength"].includes(name)
      && values[0] < 0) fail("limit");
  } else if (name === "d") numbers(value, "MmLlHhVvCcSsQqTtAaZz");
  else if (name === "points" || name === "viewBox") numbers(value);
  else if (name === "transform") {
    const rest = value.replace(/(?:matrix|translate|scale|rotate|skewX|skewY)\(([^()]*)\)/g, (_, args: string) => {
      numbers(args);
      return "";
    });
    if (rest.trim() !== "") fail();
  } else if (name === "orient" && value !== "auto" && value !== "auto-start-reverse") numbers(value);
}

function escapeXml(value: string): string {
  return value.replace(/[&<>"\r\n\t]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
    "\r": "&#13;", "\n": "&#10;", "\t": "&#9;",
  })[character]!);
}

export function diagramImageTemplate(svg: string, fonts: DiagramInput["fonts"]): DiagramTemplate {
  if (svg.length > OUTPUT_LIMIT || encoder.encode(svg).byteLength > OUTPUT_LIMIT) fail("limit");
  family(fonts.sans);
  family(fonts.mono);
  if (!Number.isFinite(fonts.size) || fonts.size <= 0 || fonts.size > 200) fail("capability");
  const parser = new SaxesParser({ xmlns: true });
  const content: string[] = [];
  const stack: string[] = [];
  const ids = new Map<string, string>();
  const refs: Reference[] = [];
  let elements = 0;
  let width = 0;
  let height = 0;
  let rootStyle = "";
  let title = "";
  let description = "";
  parser.on("error", () => fail());
  parser.on("doctype", () => fail());
  parser.on("processinginstruction", () => fail());
  parser.on("xmldecl", () => fail());
  parser.on("opentag", (tag) => {
    if (++elements > ELEMENT_LIMIT) fail("limit");
    if (tag.uri !== SVG_NS || tag.prefix !== "" || !ELEMENTS.has(tag.local)) fail();
    const root = stack.length === 0;
    if (root && (elements !== 1 || tag.local !== "svg")) fail();
    if (stack.at(-1) === "title" || stack.at(-1) === "desc") fail();
    const attributes: string[] = [];
    const rootDrawing: string[] = [];
    for (const attribute of Object.values(tag.attributes)) {
      const { name, value, uri } = attribute;
      if (uri === XMLNS_NS) {
        if (name !== "xmlns" || value !== SVG_NS) fail();
        continue;
      }
      if (uri !== "" && !(uri === XML_NS && name === "xml:space")) fail();
      let accepted = value;
      if (name === "xml:space") {
        if (value !== "preserve" && value !== "default") fail();
      } else if (name === "style") accepted = style(value, root, fonts, refs);
      else if (DRAWING_PROPERTIES.has(name)) accepted = drawingValue(name, css(value, "value"), refs);
      else if (TYPOGRAPHY_PROPERTIES.has(name)) accepted = typography(name, css(value, "value"), root, fonts, true);
      else if (!ATTRIBUTES.has(name)) fail();
      else geometry(name, value);
      if (name === "id") {
        if (!/^[A-Za-z0-9_.:-]+$/.test(value) || ids.has(value)) fail();
        ids.set(value, tag.local);
      }
      if (!root) attributes.push(` ${name}="${escapeXml(accepted)}"`);
      else if (name === "style") rootStyle = accepted;
      else if (DRAWING_PROPERTIES.has(name)) rootDrawing.push(`${name}:${accepted}`);
    }
    if (root) {
      if (!rootStyle) fail();
      rootStyle += rootDrawing.length ? `;${rootDrawing.join(";")}` : "";
      width = dimension(tag.attributes.width?.value);
      height = dimension(tag.attributes.height?.value);
      if (width * height > MAX_PIXELS) fail("limit");
      const viewBox = numbers(tag.attributes.viewBox?.value ?? "");
      if (viewBox.length !== 4 || viewBox[0] !== 0 || viewBox[1] !== 0
        || viewBox[2] !== width || viewBox[3] !== height) fail("limit");
      if (!rootStyle) fail();
    } else content.push(`<${tag.local}${attributes.join("")}>`);
    stack.push(tag.local);
  });
  const text = (value: string) => {
    const element = stack.at(-1);
    if (element === "title") title += value.slice(0, Math.max(0, 1000 - title.length));
    if (element === "desc") description += value.slice(0, Math.max(0, 1000 - description.length));
    if (stack.length > 1) {
      if (value.trim() && !["title", "desc", "text", "tspan"].includes(element ?? "")) fail();
      content.push(escapeXml(value));
    } else if (value.trim()) fail();
  };
  parser.on("text", text);
  parser.on("cdata", text);
  parser.on("closetag", (tag) => {
    if (stack.length > 1) content.push(`</${tag.local}>`);
    stack.pop();
  });
  parser.write(svg).close();
  for (const ref of refs) if (ids.get(ref.id) !== ref.target) fail();
  const body = content.join("");
  if (encoder.encode(body + rootStyle).byteLength > OUTPUT_LIMIT) fail("limit");
  return {
    content: body, style: rootStyle, width, height,
    label: [title, description].filter(Boolean).join(". ").replace(/\s+/g, " ").trim().slice(0, 1000),
  };
}
