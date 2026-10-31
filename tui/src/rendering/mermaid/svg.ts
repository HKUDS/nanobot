import { DOMParser, XMLSerializer } from "@xmldom/xmldom"
import type { CssNode, ListItem, List } from "css-tree"
// css-tree's split runtime exports avoid its Node-only syntax-data loader in compiled workers.
// @ts-expect-error The package types declare only the barrel entrypoint.
import parseRuntime from "css-tree/parser"
// @ts-expect-error The package types declare only the barrel entrypoint.
import walkRuntime from "css-tree/walker"
// @ts-expect-error The package types declare only the barrel entrypoint.
import generateRuntime from "css-tree/generator"
const parse: typeof import("css-tree").parse = parseRuntime
const walk: typeof import("css-tree").walk = walkRuntime
const generate: typeof import("css-tree").generate = generateRuntime
import type { DiagramInput } from "./types"
import { DIAGRAM_FONT_SIZE, OUTPUT_LIMIT } from "./types"

const elements = new Set([
  "svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
  "text", "tspan", "title", "desc", "defs", "marker", "clipPath",
])

// A closed image document for resvg, never HTML or an executable SVG surface.
export function resolveDiagramSvg(svg: string, input: DiagramInput, family: string, mono: string): string {
  if (Buffer.byteLength(svg) > OUTPUT_LIMIT || /<!DOCTYPE|<!ENTITY|<\?/i.test(svg)) throw new Error("SVG policy")
  const document = new DOMParser({ errorHandler: () => { throw new Error("Invalid SVG") } }).parseFromString(svg, "image/svg+xml")
  const root = document.documentElement
  if (root.tagName !== "svg") throw new Error("Invalid SVG root")
  const colors = input.colors
  for (const color of Object.values(colors)) {
    if (!/^#[\da-f]{6}$/i.test(color)) throw new Error("Invalid diagram color")
  }
  const variables = new Map<string, string>([
    ["--pele-bg", "transparent"], ["--pele-fg", colors.foreground],
    ["--pele-muted", colors.muted], ["--pele-line", colors.foreground],
    ["--pele-surface", colors.surface], ["--pele-surface-alt", colors.surface],
    ["--pele-border", colors.border], ["--pele-accent", colors.accent],
    ["--pele-font", JSON.stringify(family)], ["--pele-font-mono", JSON.stringify(mono)],
  ])
  const rootStyle = parse(root.getAttribute("style") || "", { context: "declarationList", parseCustomProperty: true })
  walk(rootStyle, node => {
    if (node.type === "Declaration" && node.property.startsWith("--_")) variables.set(node.property, generate(node.value))
  })
  const resolve = (value: string, depth = 0): string => {
    if (depth > 16) throw new Error("Cyclic SVG variables")
    const ast = parse(value, { context: "value", parseCustomProperty: true })
    walk(ast, {
      leave(node: CssNode, item: ListItem<CssNode>, list: List<CssNode>) {
        if (node.type === "Raw") throw new Error("Unsupported SVG CSS")
        if (node.type === "Url" && !/^#[\w-]+$/.test(node.value)) throw new Error("External SVG resource")
        if (node.type !== "Function" || node.name.toLowerCase() !== "var") return
        const args = node.children.toArray()
        const name = args[0]
        if (name?.type !== "Identifier") throw new Error("Invalid SVG variable")
        const comma = args.findIndex(arg => arg.type === "Operator" && arg.value === ",")
        const fallback = comma < 0 ? undefined : args.slice(comma + 1).map(node => generate(node)).join(" ")
        const replacement = variables.get(name.name) ?? fallback
        if (replacement === undefined) throw new Error("Unresolved SVG variable")
        const expanded = parse(resolve(replacement, depth + 1), { context: "value" })
        if (expanded.type !== "Value" || !item || !list) throw new Error("Invalid SVG variable")
        list.replace(item, expanded.children)
      },
    })
    return generate(ast)
  }
  const nodes = document.getElementsByTagName("*")
  if (nodes.length > 10_000) throw new Error("SVG element limit")
  for (let i = 0; i < nodes.length; i++) {
    const element = nodes.item(i)!
    if (!elements.has(element.tagName) || element.namespaceURI !== "http://www.w3.org/2000/svg") throw new Error("SVG element policy")
    for (const attribute of Array.from(element.attributes)) {
      const name = attribute.name
      if (/^on|href$/i.test(name) || (name.includes(":") && name !== "xml:space")) throw new Error(`SVG attribute policy: ${name}`)
      if (name === "style") {
        const ast = parse(attribute.value, { context: "declarationList", parseCustomProperty: true })
        if (ast.type !== "DeclarationList") throw new Error("Invalid SVG style")
        ast.children.forEach((node, item, list) => {
          if (node.type !== "Declaration") throw new Error("Invalid SVG declaration")
          if (node.property.startsWith("--")) { list.remove(item); return }
          const value = parse(resolve(generate(node.value)), { context: "value" })
          if (value.type !== "Value") throw new Error("Invalid SVG value")
          node.value = value
        })
        element.setAttribute(name, generate(ast))
      } else if (/\b(?:var|url)\s*\(/i.test(attribute.value)) {
        element.setAttribute(name, resolve(attribute.value))
      }
    }
  }
  root.setAttribute("font-family", family)
  root.setAttribute("font-size", String(DIAGRAM_FONT_SIZE))
  const output = new XMLSerializer().serializeToString(document)
  if (Buffer.byteLength(output) > OUTPUT_LIMIT) throw new Error("SVG output limit")
  return output
}
