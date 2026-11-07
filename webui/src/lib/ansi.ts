export type AnsiSegment = {
  text: string;
  style?: AnsiStyle;
};

type AnsiStyle = {
  backgroundColor?: string;
  color?: string;
  fontStyle?: "italic";
  fontWeight?: number;
  opacity?: number;
  textDecorationLine?: "underline";
};

type AnsiState = {
  backgroundColor?: AnsiColor;
  bold: boolean;
  color?: AnsiColor;
  dim: boolean;
  inverse: boolean;
  italic: boolean;
  underline: boolean;
};

type AnsiColor = number | string;
type AnsiTheme = "light" | "dark";

const ESC = String.fromCharCode(27);
const ANSI_PATTERN = new RegExp(`${ESC}\\[[0-?]*[ -/]*[@-~]`, "g");

const ANSI_COLORS = [
  "#000000",
  "#cd3131",
  "#0dbc79",
  "#e5e510",
  "#2472c8",
  "#bc3fbc",
  "#11a8cd",
  "#e5e5e5",
];

const ANSI_BRIGHT_COLORS = [
  "#666666",
  "#f14c4c",
  "#23d18b",
  "#f5f543",
  "#3b8eea",
  "#d670d6",
  "#29b8db",
  "#ffffff",
];

const ANSI_PALETTE = [...ANSI_COLORS, ...ANSI_BRIGHT_COLORS];
const ANSI_FOREGROUNDS: Record<AnsiTheme, string[]> = {
  light: [
    "#18181b", "#b91c1c", "#166534", "#854d0e",
    "#1d4ed8", "#7e22ce", "#0e7490", "#52525b",
    "#62626b", "#b91c1c", "#166534", "#854d0e",
    "#1d4ed8", "#86198f", "#155e75", "#3f3f46",
  ],
  dark: [
    "#a1a1aa", "#fca5a5", "#86efac", "#fde047",
    "#93c5fd", "#d8b4fe", "#67e8f9", "#e5e7eb",
    "#a1a1aa", "#fca5a5", "#86efac", "#fef08a",
    "#93c5fd", "#e9d5ff", "#a5f3fc", "#ffffff",
  ],
};

const RGB_STEPS = [0, 95, 135, 175, 215, 255];

export function hasAnsi(value: string): boolean {
  ANSI_PATTERN.lastIndex = 0;
  return ANSI_PATTERN.test(value);
}

export function stripAnsi(value: string): string {
  ANSI_PATTERN.lastIndex = 0;
  return value.replace(ANSI_PATTERN, "");
}

function initialState(): AnsiState {
  return {
    backgroundColor: undefined,
    color: undefined,
    bold: false,
    dim: false,
    inverse: false,
    italic: false,
    underline: false,
  };
}

function colorFrom256(value: number): AnsiColor | undefined {
  if (value < 0 || value > 255) return undefined;
  if (value < 16) return value;
  if (value < 232) {
    const offset = value - 16;
    const red = RGB_STEPS[Math.floor(offset / 36)];
    const green = RGB_STEPS[Math.floor((offset % 36) / 6)];
    const blue = RGB_STEPS[offset % 6];
    return `rgb(${red}, ${green}, ${blue})`;
  }
  const gray = 8 + ((value - 232) * 10);
  return `rgb(${gray}, ${gray}, ${gray})`;
}

function colorFromRgb(red: number, green: number, blue: number): string | undefined {
  if ([red, green, blue].some((value) => !Number.isFinite(value) || value < 0 || value > 255)) {
    return undefined;
  }
  return `rgb(${red}, ${green}, ${blue})`;
}

function normalizedSgrParams(sequence: string): number[] | null {
  if (!sequence.endsWith("m")) return null;
  const body = sequence.slice(2, -1).trim();
  if (!body) return [0];
  return body.split(/[;:]/).map((part) => {
    const value = Number.parseInt(part || "0", 10);
    return Number.isFinite(value) ? value : 0;
  });
}

function applyExtendedColor(
  state: AnsiState,
  params: number[],
  index: number,
  key: "color" | "backgroundColor",
): number {
  const mode = params[index + 1];
  if (mode === 5) {
    const color = colorFrom256(params[index + 2]);
    if (color !== undefined) state[key] = color;
    return index + 2;
  }
  if (mode === 2) {
    const color = colorFromRgb(params[index + 2], params[index + 3], params[index + 4]);
    if (color) state[key] = color;
    return index + 4;
  }
  return index;
}

function applySgrParams(state: AnsiState, params: number[]): void {
  for (let index = 0; index < params.length; index += 1) {
    const code = params[index];
    if (code === 0) {
      Object.assign(state, initialState());
    } else if (code === 1) {
      state.bold = true;
      state.dim = false;
    } else if (code === 2) {
      state.dim = true;
      state.bold = false;
    } else if (code === 3) {
      state.italic = true;
    } else if (code === 4) {
      state.underline = true;
    } else if (code === 7) {
      state.inverse = true;
    } else if (code === 22) {
      state.bold = false;
      state.dim = false;
    } else if (code === 23) {
      state.italic = false;
    } else if (code === 24) {
      state.underline = false;
    } else if (code === 27) {
      state.inverse = false;
    } else if (code === 39) {
      delete state.color;
    } else if (code === 49) {
      delete state.backgroundColor;
    } else if (code >= 30 && code <= 37) {
      state.color = code - 30;
    } else if (code >= 40 && code <= 47) {
      state.backgroundColor = code - 40;
    } else if (code >= 90 && code <= 97) {
      state.color = code - 90 + 8;
    } else if (code >= 100 && code <= 107) {
      state.backgroundColor = code - 100 + 8;
    } else if (code === 38) {
      index = applyExtendedColor(state, params, index, "color");
    } else if (code === 48) {
      index = applyExtendedColor(state, params, index, "backgroundColor");
    }
  }
}

function styleFromState(state: AnsiState, theme: AnsiTheme): AnsiStyle | undefined {
  // Explicit color pairs retain the output's palette; standalone foregrounds
  // use colors selected for the UI surface. RGB and extended colors stay literal.
  const palette = state.backgroundColor === undefined ? ANSI_FOREGROUNDS[theme] : ANSI_PALETTE;
  const foreground = typeof state.color === "number" ? palette[state.color] : state.color;
  const background = typeof state.backgroundColor === "number"
    ? ANSI_PALETTE[state.backgroundColor] : state.backgroundColor;
  const style: AnsiStyle = {};
  if (state.inverse) {
    style.color = background ?? "hsl(var(--background))";
    style.backgroundColor = foreground ?? "hsl(var(--foreground))";
  } else {
    if (foreground) style.color = foreground;
    if (background) style.backgroundColor = background;
  }
  if (state.bold) style.fontWeight = 700;
  if (state.dim) style.opacity = 0.72;
  if (state.italic) style.fontStyle = "italic";
  if (state.underline) style.textDecorationLine = "underline";
  return Object.keys(style).length ? style : undefined;
}

export function parseAnsiSegments(value: string, theme: AnsiTheme): AnsiSegment[] {
  const segments: AnsiSegment[] = [];
  const state = initialState();
  let cursor = 0;
  ANSI_PATTERN.lastIndex = 0;

  for (const match of value.matchAll(ANSI_PATTERN)) {
    const index = match.index ?? 0;
    if (index > cursor) {
      segments.push({
        text: value.slice(cursor, index),
        style: styleFromState(state, theme),
      });
    }
    const params = normalizedSgrParams(match[0]);
    if (params) applySgrParams(state, params);
    cursor = index + match[0].length;
  }

  if (cursor < value.length) {
    segments.push({
      text: value.slice(cursor),
      style: styleFromState(state, theme),
    });
  }

  return segments.filter((segment) => segment.text.length > 0);
}
