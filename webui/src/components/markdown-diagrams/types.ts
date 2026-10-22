// Private feature contracts. Only the Worker imports Pele and the XML/CSS parsers.
export interface DiagramInput {
  source: string;
  width: number;
  fonts: { sans: string; mono: string; size: number };
}

export type DiagramFailure = "syntax" | "unsupported" | "policy" | "limit"
  | "load" | "deadline" | "worker" | "image" | "capability";

// Image-context only; never insert this content into the page DOM.
export interface DiagramTemplate {
  content: string;
  style: string;
  width: number;
  height: number;
  label: string;
}

export type DiagramReply = { kind: "started" }
  | { kind: "image"; template: DiagramTemplate }
  | { kind: "failed"; reason: DiagramFailure };

export const SOURCE_LIMIT = 50_000;
export const OUTPUT_LIMIT = 1_048_576;
export const MAX_DIMENSION = 8192;
export const MAX_PIXELS = 8_000_000;
