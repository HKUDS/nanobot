const MATH_SYMBOLS: Readonly<Record<string, string>> = {
  alpha: "α",
  beta: "β",
  gamma: "γ",
  delta: "δ",
  epsilon: "ε",
  varepsilon: "ϵ",
  zeta: "ζ",
  eta: "η",
  theta: "θ",
  vartheta: "ϑ",
  iota: "ι",
  kappa: "κ",
  lambda: "λ",
  mu: "μ",
  nu: "ν",
  xi: "ξ",
  omicron: "ο",
  pi: "π",
  varpi: "ϖ",
  rho: "ρ",
  varrho: "ϱ",
  sigma: "σ",
  varsigma: "ς",
  tau: "τ",
  upsilon: "υ",
  phi: "φ",
  varphi: "ϕ",
  chi: "χ",
  psi: "ψ",
  omega: "ω",
  Gamma: "Γ",
  Delta: "Δ",
  Theta: "Θ",
  Lambda: "Λ",
  Xi: "Ξ",
  Pi: "Π",
  Sigma: "Σ",
  Upsilon: "Υ",
  Phi: "Φ",
  Psi: "Ψ",
  Omega: "Ω",
  times: " × ",
  div: " ÷ ",
  cdot: " · ",
  ast: " ∗ ",
  pm: " ± ",
  mp: " ∓ ",
  approx: " ≈ ",
  sim: " ∼ ",
  simeq: " ≃ ",
  cong: " ≅ ",
  equiv: " ≡ ",
  ne: " ≠ ",
  neq: " ≠ ",
  le: " ≤ ",
  leq: " ≤ ",
  ge: " ≥ ",
  geq: " ≥ ",
  ll: " ≪ ",
  gg: " ≫ ",
  propto: " ∝ ",
  to: " → ",
  gets: " ← ",
  rightarrow: " → ",
  leftarrow: " ← ",
  leftrightarrow: " ↔ ",
  Rightarrow: " ⇒ ",
  Leftarrow: " ⇐ ",
  Leftrightarrow: " ⇔ ",
  mapsto: " ↦ ",
  in: " ∈ ",
  ni: " ∋ ",
  notin: " ∉ ",
  subset: " ⊂ ",
  supset: " ⊃ ",
  subseteq: " ⊆ ",
  supseteq: " ⊇ ",
  cup: " ∪ ",
  cap: " ∩ ",
  setminus: " ∖ ",
  emptyset: "∅",
  varnothing: "∅",
  forall: "∀",
  exists: "∃",
  neg: "¬",
  land: " ∧ ",
  lor: " ∨ ",
  wedge: " ∧ ",
  vee: " ∨ ",
  sum: "∑",
  prod: "∏",
  coprod: "∐",
  int: "∫",
  iint: "∬",
  iiint: "∭",
  oint: "∮",
  partial: "∂",
  nabla: "∇",
  infty: "∞",
  ell: "ℓ",
  hbar: "ℏ",
  Re: "ℜ",
  Im: "ℑ",
  angle: "∠",
  degree: "°",
  prime: "′",
  ldots: "…",
  cdots: "⋯",
  vdots: "⋮",
  ddots: "⋱",
  langle: "⟨",
  rangle: "⟩",
  lceil: "⌈",
  rceil: "⌉",
  lfloor: "⌊",
  rfloor: "⌋",
  vert: "|",
  Vert: "‖",
}

const NAMED_FUNCTIONS = new Set([
  "arccos",
  "arcsin",
  "arctan",
  "cos",
  "cosh",
  "cot",
  "coth",
  "csc",
  "deg",
  "det",
  "dim",
  "exp",
  "gcd",
  "hom",
  "inf",
  "ker",
  "lg",
  "lim",
  "liminf",
  "limsup",
  "ln",
  "log",
  "max",
  "min",
  "Pr",
  "sec",
  "sin",
  "sinh",
  "sup",
  "tan",
  "tanh",
])

const STYLE_COMMANDS = new Set([
  "mathbf",
  "mathbb",
  "mathcal",
  "mathfrak",
  "mathit",
  "mathrm",
  "mathsf",
  "mathtt",
  "boldsymbol",
  "bm",
])

const ACCENTS: Readonly<Record<string, string>> = {
  acute: "\u0301",
  bar: "\u0304",
  breve: "\u0306",
  check: "\u030c",
  ddot: "\u0308",
  dot: "\u0307",
  grave: "\u0300",
  hat: "\u0302",
  overline: "\u0305",
  tilde: "\u0303",
  vec: "\u20d7",
}

const SUPER: Readonly<Record<string, string>> = {
  "0": "⁰",
  "1": "¹",
  "2": "²",
  "3": "³",
  "4": "⁴",
  "5": "⁵",
  "6": "⁶",
  "7": "⁷",
  "8": "⁸",
  "9": "⁹",
  "+": "⁺",
  "-": "⁻",
  "=": "⁼",
  "(": "⁽",
  ")": "⁾",
  a: "ᵃ",
  b: "ᵇ",
  c: "ᶜ",
  d: "ᵈ",
  e: "ᵉ",
  f: "ᶠ",
  g: "ᵍ",
  h: "ʰ",
  i: "ⁱ",
  j: "ʲ",
  k: "ᵏ",
  l: "ˡ",
  m: "ᵐ",
  n: "ⁿ",
  o: "ᵒ",
  p: "ᵖ",
  r: "ʳ",
  s: "ˢ",
  t: "ᵗ",
  u: "ᵘ",
  v: "ᵛ",
  w: "ʷ",
  x: "ˣ",
  y: "ʸ",
  z: "ᶻ",
}

const SUB: Readonly<Record<string, string>> = {
  "0": "₀",
  "1": "₁",
  "2": "₂",
  "3": "₃",
  "4": "₄",
  "5": "₅",
  "6": "₆",
  "7": "₇",
  "8": "₈",
  "9": "₉",
  "+": "₊",
  "-": "₋",
  "=": "₌",
  "(": "₍",
  ")": "₎",
  a: "ₐ",
  e: "ₑ",
  h: "ₕ",
  i: "ᵢ",
  j: "ⱼ",
  k: "ₖ",
  l: "ₗ",
  m: "ₘ",
  n: "ₙ",
  o: "ₒ",
  p: "ₚ",
  r: "ᵣ",
  s: "ₛ",
  t: "ₜ",
  u: "ᵤ",
  v: "ᵥ",
  x: "ₓ",
}

const MAX_MATH_LENGTH = 20_000
const MAX_GROUP_DEPTH = 64

/** Converts supported LaTeX math spans without changing the stored Markdown source. */
export function renderLatexAsUnicode(markdown: string): string {
  if (!markdown.includes("$") && !markdown.includes("\\(") && !markdown.includes("\\[")) {
    return markdown
  }
  let rendered = ""
  let cursor = 0
  const missingClosers = new Set<string>()
  const inlineCodeEnds = markdown.includes("`") ? markdownInlineCodeEnds(markdown) : null
  const linkDestinationEnds = markdown.includes("](")
    ? markdownLinkDestinationEnds(markdown)
    : null

  while (cursor < markdown.length) {
    const fencedEnd = fencedCodeEnd(markdown, cursor)
    if (fencedEnd !== null) {
      rendered += markdown.slice(cursor, fencedEnd)
      cursor = fencedEnd
      continue
    }

    if (markdown[cursor] === "`") {
      const delimiterLength = repeatedCharacterCount(markdown, cursor, "`")
      const inlineEnd = inlineCodeEnds?.get(cursor)
      if (inlineEnd !== undefined) {
        rendered += markdown.slice(cursor, inlineEnd)
        cursor = inlineEnd
        continue
      }
      rendered += markdown.slice(cursor, cursor + delimiterLength)
      cursor += delimiterLength
      continue
    }

    const destinationEnd = markdownDestinationEnd(markdown, cursor, linkDestinationEnds)
    if (destinationEnd !== null) {
      rendered += markdown.slice(cursor, destinationEnd)
      cursor = destinationEnd
      continue
    }

    const explicitOpening = explicitMathOpeningAt(markdown, cursor)
    const math = mathSpanAt(markdown, cursor, explicitOpening, missingClosers)
    if (math) {
      if (math.literal) {
        rendered += markdown.slice(cursor, math.end)
        cursor = math.end
        continue
      }
      const converted = convertMath(math.content)
      if (converted !== null) {
        rendered += escapeMarkdown(converted)
        cursor = math.end
        continue
      }
      rendered += markdown.slice(cursor, math.end)
      cursor = math.end
      continue
    }
    if (explicitOpening) {
      rendered += explicitOpening
      cursor += explicitOpening.length
      continue
    }

    rendered += markdown[cursor]
    cursor += 1
  }

  return rendered
}

interface MathSpan {
  content: string
  end: number
  literal?: boolean
}

interface ParseState {
  valid: boolean
}

function convertMath(source: string): string | null {
  if (!validMathStructure(source)) return null
  const state: ParseState = { valid: true }
  const converted = normalizeMath(new LatexParser(source, state).parse())
  return state.valid && converted ? converted : null
}

function validMathStructure(source: string): boolean {
  if (source.length > MAX_MATH_LENGTH) return false
  let depth = 0
  for (let cursor = 0; cursor < source.length; cursor += 1) {
    const value = source[cursor]
    if (value !== "{" && value !== "}") continue
    if (isEscaped(source, cursor)) continue
    if (value === "{") {
      depth += 1
      if (depth > MAX_GROUP_DEPTH) return false
    } else if (source[cursor] === "}") {
      depth -= 1
      if (depth < 0) return false
    }
  }
  return depth === 0
}

function explicitMathOpeningAt(markdown: string, start: number): string | null {
  const opening = markdown.startsWith("\\[", start)
    ? "\\["
    : markdown.startsWith("\\(", start)
      ? "\\("
      : markdown.startsWith("$$", start)
        ? "$$"
        : null
  return opening && !isEscaped(markdown, start) ? opening : null
}

function mathSpanAt(
  markdown: string,
  start: number,
  explicitOpening: string | null,
  missingClosers: Set<string>,
): MathSpan | null {
  if (explicitOpening === "\\[") {
    return delimitedMath(markdown, start, "\\[", "\\]", false, missingClosers)
  }
  if (explicitOpening === "\\(") {
    return delimitedMath(markdown, start, "\\(", "\\)", true, missingClosers)
  }
  if (explicitOpening === "$$") {
    return delimitedMath(markdown, start, "$$", "$$", false, missingClosers)
  }
  if (
    markdown[start] !== "$"
    || markdown[start + 1] === "$"
    || isWhitespace(markdown[start + 1])
    || isEscaped(markdown, start)
  ) {
    return null
  }

  const span = delimitedMath(markdown, start, "$", "$", true, missingClosers)
  if (!span || isWhitespace(span.content.at(-1))) return null
  const first = span.content[0]
  if (first && /[0-9]/u.test(first)) {
    const following = markdown[span.end] ?? ""
    if (!isWhitespace(following) && /[+\-*/]\s*$/u.test(span.content)) {
      const adjacent = delimitedMath(
        markdown,
        span.end - 1,
        "$",
        "$",
        true,
        missingClosers,
      )
      if (adjacent && !isWhitespace(adjacent.content.at(-1))) {
        return { content: "", end: adjacent.end, literal: true }
      }
    }
    if (/[0-9]/u.test(following)) return null
  }
  if (first && /[0-9]/u.test(first) && !/[\\^_={}|+<>]/u.test(span.content)) return null
  if (
    /^[A-Z_][A-Z0-9_]*(?:\/|\s.*)$/u.test(span.content)
    && /[A-Z_]/u.test(markdown[span.end] ?? "")
    && !/[\\^_={}|+<>]/u.test(span.content)
  ) {
    return null
  }
  return span
}

function delimitedMath(
  source: string,
  start: number,
  opening: string,
  closing: string,
  singleLine: boolean,
  missingClosers: Set<string>,
): MathSpan | null {
  const contentStart = start + opening.length
  const lineEnd = singleLine ? source.indexOf("\n", contentStart) : -1
  const boundary = lineEnd < 0 ? source.length : lineEnd
  const cacheKey = `${closing}:${boundary}`
  if (missingClosers.has(cacheKey)) return null

  for (let close = contentStart; close + closing.length <= boundary; close += 1) {
    if (!source.startsWith(closing, close) || isEscaped(source, close)) continue
    if (closing === "$" && (source[close - 1] === "$" || source[close + 1] === "$")) continue
    const content = source.slice(start + opening.length, close)
    return content ? { content, end: close + closing.length } : null
  }
  missingClosers.add(cacheKey)
  return null
}

function fencedCodeEnd(source: string, start: number): number | null {
  const marker = source[start]
  if (marker !== "`" && marker !== "~") return null
  const lineStart = source.lastIndexOf("\n", start - 1) + 1
  const context = fenceContext(source.slice(lineStart, start))
  if (!context) return null

  const count = repeatedCharacterCount(source, start, marker)
  if (count < 3) return null
  const openingLineEnd = source.indexOf("\n", start + count)
  if (openingLineEnd < 0) return source.length

  let candidateStart = openingLineEnd + 1
  while (candidateStart <= source.length) {
    const candidateEnd = source.indexOf("\n", candidateStart)
    const lineEnd = candidateEnd < 0 ? source.length : candidateEnd
    const line = source.slice(candidateStart, lineEnd)
    const markerOffset = closingFenceOffset(line, context)
    if (markerOffset === null) {
      if (candidateEnd < 0) break
      candidateStart = candidateEnd + 1
      continue
    }
    const markerStart = candidateStart + markerOffset
    const closingCount = repeatedCharacterCount(source, markerStart, marker)
    if (closingCount >= count && source.slice(markerStart + closingCount, lineEnd).trim() === "") {
      return candidateEnd < 0 ? source.length : candidateEnd + 1
    }
    if (candidateEnd < 0) break
    candidateStart = candidateEnd + 1
  }
  return source.length
}

interface FenceContext {
  quoteDepth: number
  maxIndent: number
}

function fenceContext(prefix: string): FenceContext | null {
  let rest = prefix
  let quoteDepth = 0
  while (true) {
    const quote = rest.match(/^[ \t]{0,3}>[ \t]?/u)?.[0]
    if (!quote) break
    quoteDepth += 1
    rest = rest.slice(quote.length)
  }

  const list = rest.match(/^[ \t]*(?:[-+*]|[0-9]{1,9}[.)])[ \t]+/u)?.[0]
  if (list) rest = rest.slice(list.length)
  if (!/^[ \t]*$/u.test(rest)) return null
  return { quoteDepth, maxIndent: Math.max(3, list?.length ?? 0, rest.length) }
}

function closingFenceOffset(line: string, context: FenceContext): number | null {
  let offset = 0
  for (let depth = 0; depth < context.quoteDepth; depth += 1) {
    const quote = line.slice(offset).match(/^[ \t]{0,3}>[ \t]?/u)?.[0]
    if (!quote) return null
    offset += quote.length
  }
  const indent = line.slice(offset).match(new RegExp(`^[ \\t]{0,${context.maxIndent}}`, "u"))?.[0]
  return indent === undefined ? null : offset + indent.length
}

function markdownInlineCodeEnds(source: string): ReadonlyMap<number, number> {
  const ends = new Map<number, number>()
  const previousRun = new Map<number, number>()
  let cursor = 0
  while (cursor < source.length) {
    if (source[cursor] !== "`") {
      cursor += 1
      continue
    }
    const count = repeatedCharacterCount(source, cursor, "`")
    const previous = previousRun.get(count)
    if (previous !== undefined) ends.set(previous, cursor + count)
    previousRun.set(count, cursor)
    cursor += count
  }
  return ends
}

function markdownLinkDestinationEnds(source: string): ReadonlyMap<number, number> {
  const ends = new Map<number, number>()
  const openParentheses: number[] = []
  let cursor = 0
  while (cursor < source.length) {
    const value = source[cursor]
    if (value === "\\") {
      cursor += Math.min(2, source.length - cursor)
      continue
    }
    if (value === "\n") {
      openParentheses.length = 0
    } else if (value === "(") {
      openParentheses.push(cursor)
    } else if (value === ")") {
      const opening = openParentheses.pop()
      if (opening !== undefined && source[opening - 1] === "]" && !isEscaped(source, opening - 1)) {
        ends.set(opening, cursor + 1)
      }
    }
    cursor += 1
  }
  return ends
}

function markdownDestinationEnd(
  source: string,
  start: number,
  linkDestinationEnds: ReadonlyMap<number, number> | null,
): number | null {
  if (source[start] === "(" && source[start - 1] === "]" && !isEscaped(source, start - 1)) {
    return linkDestinationEnds?.get(start) ?? null
  }

  if (source[start] === "<") {
    const angle = source.slice(start).match(
      /^<(?:[A-Za-z][A-Za-z0-9+.-]{1,31}:[^<>\s]*|[^<>\s@]+@[^<>\s@]+|\/?[A-Za-z][^<>\n]*)>/u,
    )?.[0]
    if (angle) return start + angle.length
  }

  if (
    source.startsWith("http://", start)
    || source.startsWith("https://", start)
    || source.startsWith("mailto:", start)
  ) {
    let end = start
    while (end < source.length && !/[\s<>]/u.test(source[end] ?? "")) end += 1
    return end
  }
  return null
}

function repeatedCharacterCount(source: string, start: number, value: string): number {
  let end = start
  while (source[end] === value) end += 1
  return end - start
}

function isEscaped(source: string, index: number): boolean {
  let backslashes = 0
  for (let cursor = index - 1; cursor >= 0 && source[cursor] === "\\"; cursor -= 1) {
    backslashes += 1
  }
  return backslashes % 2 === 1
}

function isWhitespace(value: string | undefined): boolean {
  return value === undefined || /\s/u.test(value)
}

class LatexParser {
  private cursor = 0

  constructor(
    private readonly source: string,
    private readonly state: ParseState,
  ) {}

  parse(): string {
    let result = ""
    while (this.cursor < this.source.length) {
      const value = this.source[this.cursor]
      if (value === undefined) break
      if (/\s/u.test(value)) {
        result += " "
        this.cursor += 1
      } else if (value === "\\") {
        result += this.command()
      } else if (value === "{") {
        const group = this.rawGroup()
        result += group === null ? "{" : new LatexParser(group, this.state).parse()
      } else if (value === "^" || value === "_") {
        this.cursor += 1
        const argument = this.argument()
        result += script(argument ?? "", value === "^" ? SUPER : SUB, value)
      } else if (value === "&" || value === "~") {
        result += " "
        this.cursor += 1
      } else {
        result += value
        this.cursor += 1
      }
    }
    return result
  }

  private command(): string {
    this.cursor += 1
    const first = this.source[this.cursor]
    if (first === undefined) return ""
    if (!/[A-Za-z]/u.test(first)) {
      this.cursor += 1
      if (first === "\\") return "\n"
      if (",:;! ".includes(first)) return " "
      return first
    }

    const start = this.cursor
    while (/[A-Za-z]/u.test(this.source[this.cursor] ?? "")) this.cursor += 1
    const name = this.source.slice(start, this.cursor)
    if (this.source[this.cursor] === "*") this.cursor += 1

    const symbol = MATH_SYMBOLS[name]
    if (symbol !== undefined) return symbol
    if (NAMED_FUNCTIONS.has(name)) return name
    if ([
      "left",
      "right",
      "limits",
      "nolimits",
      "displaystyle",
      "textstyle",
      "scriptstyle",
      "scriptscriptstyle",
    ].includes(name)) return ""
    if (["quad", "qquad", "enspace", "enskip"].includes(name)) return " "
    if (["hspace", "vspace"].includes(name)) {
      this.rawGroup()
      return " "
    }

    if (["frac", "dfrac", "tfrac"].includes(name)) {
      const numerator = this.argument()
      const denominator = this.argument()
      if (numerator !== null && denominator !== null) {
        return `${fractionSide(numerator)} / ${fractionSide(denominator)}`
      }
      return "frac"
    }

    if (name === "sqrt") {
      const root = this.optionalArgument()
      const radicand = this.argument()
      if (radicand === null) return "√"
      const index = root ? script(root, SUPER, "^") : ""
      return `${index}√(${radicand})`
    }

    if (["text", "textrm", "textsf", "texttt", "textnormal", "mbox"].includes(name)) {
      const text = this.rawGroup()
      return text === null ? name : plainText(text, this.state)
    }

    if (STYLE_COMMANDS.has(name)) return this.argument() ?? ""
    if (name === "operatorname") {
      const operator = this.rawGroup()
      return operator === null ? "" : plainText(operator, this.state)
    }

    const accent = ACCENTS[name]
    if (accent !== undefined) {
      const argument = this.argument()
      return argument === null ? "" : `${argument}${accent}`
    }

    if (name === "begin" || name === "end") {
      const environment = this.rawGroup()
      return name === "begin" && environment === "cases" ? "{\n" : ""
    }

    if (name === "not") return this.negatedSymbol()
    if (name === "mod") return "mod"
    if (name === "pmod") {
      const value = this.argument()
      return value === null ? "mod" : `(mod ${value})`
    }

    this.state.valid = false
    return `\\${name}`
  }

  private negatedSymbol(): string {
    while (/\s/u.test(this.source[this.cursor] ?? "")) this.cursor += 1
    if (this.source[this.cursor] === "=") {
      this.cursor += 1
      return " ≠ "
    }
    if (this.source[this.cursor] !== "\\") return "¬"

    const saved = this.cursor
    this.cursor += 1
    const start = this.cursor
    while (/[A-Za-z]/u.test(this.source[this.cursor] ?? "")) this.cursor += 1
    const name = this.source.slice(start, this.cursor)
    const negated: Readonly<Record<string, string>> = {
      in: " ∉ ",
      ni: " ∌ ",
      subset: " ⊄ ",
      supset: " ⊅ ",
      subseteq: " ⊈ ",
      supseteq: " ⊉ ",
    }
    const symbol = negated[name]
    if (symbol !== undefined) return symbol
    this.cursor = saved
    return "¬"
  }

  private argument(): string | null {
    while (/\s/u.test(this.source[this.cursor] ?? "")) this.cursor += 1
    if (this.source[this.cursor] === "{") {
      const group = this.rawGroup()
      return group === null ? null : new LatexParser(group, this.state).parse()
    }
    if (this.source[this.cursor] === "\\") return this.command()
    const value = this.source[this.cursor]
    if (value === undefined) {
      this.state.valid = false
      return null
    }
    this.cursor += 1
    return value
  }

  private optionalArgument(): string | null {
    while (/\s/u.test(this.source[this.cursor] ?? "")) this.cursor += 1
    if (this.source[this.cursor] !== "[") return null
    const start = this.cursor + 1
    let depth = 1
    this.cursor += 1
    while (this.cursor < this.source.length) {
      const value = this.source[this.cursor]
      if (value === "[") depth += 1
      else if (value === "]") {
        depth -= 1
        if (depth === 0) {
          const content = this.source.slice(start, this.cursor)
          this.cursor += 1
          return new LatexParser(content, this.state).parse()
        }
      }
      this.cursor += 1
    }
    this.state.valid = false
    return null
  }

  private rawGroup(): string | null {
    while (/\s/u.test(this.source[this.cursor] ?? "")) this.cursor += 1
    if (this.source[this.cursor] !== "{") {
      this.state.valid = false
      return null
    }
    const start = this.cursor + 1
    let depth = 1
    this.cursor += 1
    while (this.cursor < this.source.length) {
      const value = this.source[this.cursor]
      if (value === "\\") {
        this.cursor += Math.min(2, this.source.length - this.cursor)
        continue
      }
      if (value === "{") depth += 1
      else if (value === "}") {
        depth -= 1
        if (depth === 0) {
          const content = this.source.slice(start, this.cursor)
          this.cursor += 1
          return content
        }
      }
      this.cursor += 1
    }
    this.state.valid = false
    return null
  }
}

function plainText(source: string, state: ParseState): string {
  let text = ""
  let cursor = 0
  while (cursor < source.length) {
    if (source[cursor] !== "\\") {
      text += source[cursor]
      cursor += 1
      continue
    }
    const next = source[cursor + 1]
    if (next === undefined) break
    if (!/[A-Za-z]/u.test(next)) {
      text += ",:;! ".includes(next) ? " " : next
      cursor += 2
      continue
    }
    let end = cursor + 1
    while (/[A-Za-z]/u.test(source[end] ?? "")) end += 1
    const name = source.slice(cursor + 1, end)
    const symbol = MATH_SYMBOLS[name]
    if (symbol !== undefined) text += symbol
    else if (NAMED_FUNCTIONS.has(name)) text += name
    else {
      state.valid = false
      text += `\\${name}`
    }
    cursor = end
  }
  return text.replace(/\s+/gu, " ").trim()
}

function script(value: string, alphabet: Readonly<Record<string, string>>, marker: string): string {
  const normalized = normalizeMath(value).replace(/\s+/gu, "")
  const converted = [...normalized].map((character) => alphabet[character])
  if (converted.every((character) => character !== undefined)) return converted.join("")
  return normalized ? `${marker}(${normalized})` : marker
}

function fractionSide(value: string): string {
  const normalized = normalizeMath(value)
  const compound = /[=+≈≠≤≥≪≫≃≅≡∝×÷·±∓→←↔⇒⇐⇔↦∈∉∋∌⊂⊄⊆⊈⊃⊅⊇⊉∪∩∧∨]/u.test(normalized)
    || /[-−]/u.test(normalized.slice(1))
    || /\s\/\s/u.test(normalized)
  return compound ? `(${normalized})` : normalized
}

function normalizeMath(value: string): string {
  return value
    .split("\n")
    .map((line) => line
      .replace(/[ \t]+/gu, " ")
      .trim()
      .replace(/\s*([=≈≠≤≥≪≫≃≅≡∝×÷±∓→←↔⇒⇐⇔↦∈∉∋∌⊂⊄⊆⊈⊃⊅⊇⊉∪∩∧∨])\s*/gu, " $1 ")
      .replace(/\s*\/\s*/gu, " / ")
      .replace(/\(\s+/gu, "(")
      .replace(/\s+\)/gu, ")")
      .replace(/\s+([,;:%])/gu, "$1")
      .replace(/[ \t]+/gu, " ")
      .trim())
    .filter(Boolean)
    .join("\n")
}

function escapeMarkdown(value: string): string {
  return value
    .replace(/\\/gu, "\\\\")
    .replace(/([`*_{}\[\]<>#|~])/gu, "\\$1")
}
