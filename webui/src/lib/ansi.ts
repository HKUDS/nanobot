export type AnsiSegment = {
  text: string;
  style?: AnsiStyle;
};

export type AnsiStyle = {
  backgroundColor?: string;
  color?: string;
  fontStyle?: "italic";
  fontWeight?: number;
  opacity?: number;
  textDecorationLine?: "underline";
};

type AnsiState = {
  backgroundColor?: string;
  bold: boolean;
  color?: string;
  dim: boolean;
  inverse: boolean;
  italic: boolean;
  underline: boolean;
};

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
    bold: false,
    dim: false,
    inverse: false,
    italic: false,
    underline: false,
  };
}

function colorFrom256(value: number): string | undefined {
  if (value < 0 || value > 255) return undefined;
  if (value < 8) return ANSI_COLORS[value];
  if (value < 16) return ANSI_BRIGHT_COLORS[value - 8];
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
    if (color) state[key] = color;
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
      state.color = ANSI_COLORS[code - 30];
    } else if (code >= 40 && code <= 47) {
      state.backgroundColor = ANSI_COLORS[code - 40];
    } else if (code >= 90 && code <= 97) {
      state.color = ANSI_BRIGHT_COLORS[code - 90];
    } else if (code >= 100 && code <= 107) {
      state.backgroundColor = ANSI_BRIGHT_COLORS[code - 100];
    } else if (code === 38) {
      index = applyExtendedColor(state, params, index, "color");
    } else if (code === 48) {
      index = applyExtendedColor(state, params, index, "backgroundColor");
    }
  }
}

function styleFromState(state: AnsiState): AnsiStyle | undefined {
  const foreground = state.inverse ? state.backgroundColor : state.color;
  const background = state.inverse ? state.color : state.backgroundColor;
  const style: AnsiStyle = {};
  if (foreground) style.color = foreground;
  if (background) style.backgroundColor = background;
  if (state.bold) style.fontWeight = 700;
  if (state.dim) style.opacity = 0.72;
  if (state.italic) style.fontStyle = "italic";
  if (state.underline) style.textDecorationLine = "underline";
  return Object.keys(style).length ? style : undefined;
}

export function parseAnsiSegments(value: string): AnsiSegment[] {
  const segments: AnsiSegment[] = [];
  const state = initialState();
  let cursor = 0;
  ANSI_PATTERN.lastIndex = 0;

  for (const match of value.matchAll(ANSI_PATTERN)) {
    const index = match.index ?? 0;
    if (index > cursor) {
      segments.push({
        text: value.slice(cursor, index),
        style: styleFromState(state),
      });
    }
    const params = normalizedSgrParams(match[0]);
    if (params) applySgrParams(state, params);
    cursor = index + match[0].length;
  }

  if (cursor < value.length) {
    segments.push({
      text: value.slice(cursor),
      style: styleFromState(state),
    });
  }

  return segments.filter((segment) => segment.text.length > 0);
}
