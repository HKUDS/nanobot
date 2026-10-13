import {
  RGBA,
  StyledText,
  SyntaxStyle,
  TextAttributes,
  parseColor,
  type ColorInput,
  type TextChunk,
} from "@opentui/core"

import type { QueuePreviewTheme } from "../composer/queue-preview"
import type { CommandMenuTheme } from "../menus/command-menu"
import type { TranscriptTheme } from "../rendering/transcript"
import type { ContextPanelTheme } from "../views/context-panel"
import type { DiffViewerTheme } from "../views/diff-viewer"
import type { FooterHintTheme } from "../views/footer-hints"
import type { RecoveryNoticeTheme } from "../views/recovery-notice"
import type { UsagePanelTheme } from "../views/usage-panel"

export const IMAGE_PLACEHOLDER_STYLE = "image.placeholder"
export const SHIMMER_INTERVAL_MS = 80
const SHIMMER_PAUSE = 16
const SHIMMER_BAND = 4
const TERMINAL_SHIMMER_BAND = 1

export interface Palette {
  referenceBackground: string
  text: ColorInput
  muted: ColorInput
  faint: ColorInput
  border: ColorInput
  accent: ColorInput
  link: ColorInput
  success: ColorInput
  warning: ColorInput
  error: ColorInput
  user: ColorInput
  userBackground: ColorInput
  warm: ColorInput
  cool: ColorInput
}

export const DARK: Palette = {
  referenceBackground: "#0E0F11",
  text: "#ECEDEE",
  muted: "#A1A1AA",
  faint: "#71717A",
  border: "#3F3F46",
  accent: "#EF8E30",
  link: "#60A5FA",
  success: "#5CC489",
  warning: "#F5C451",
  error: "#F87171",
  user: "#EF8E30",
  // Codex-style turn anchor: 12% white over the reference dark background.
  userBackground: "#2B2C2E",
  warm: "#C26A25",
  cool: "#1795A2",
}

export const LIGHT: Palette = {
  referenceBackground: "#FAFAFA",
  text: "#18181B",
  muted: "#6F6F78",
  faint: "#8A8A94",
  border: "#D4D4D8",
  accent: "#B94D0B",
  link: "#1D4ED8",
  success: "#166534",
  warning: "#A16207",
  error: "#B91C1C",
  user: "#B94D0B",
  // Codex-style turn anchor: 4% black over the reference light background.
  userBackground: "#F0F0F0",
  warm: "#C2410C",
  cool: "#0F766E",
}

// Until the terminal answers OSC 10/11, its default foreground is the only
// text color known to match its default background.
export const TERMINAL: Palette = {
  ...DARK,
  text: RGBA.defaultForeground(),
  muted: RGBA.defaultForeground(),
  faint: RGBA.defaultForeground(),
  border: RGBA.defaultForeground(),
  accent: RGBA.defaultForeground(),
  link: RGBA.defaultForeground(),
  success: RGBA.defaultForeground(),
  warning: RGBA.defaultForeground(),
  error: RGBA.defaultForeground(),
  user: RGBA.defaultForeground(),
  userBackground: RGBA.defaultBackground(),
  warm: RGBA.defaultForeground(),
  cool: RGBA.defaultForeground(),
}


export function syntaxStyle(palette: Palette): SyntaxStyle {
  const color = (value: ColorInput) => {
    const parsed = parseColor(value)
    return { fg: parsed }
  }
  return SyntaxStyle.fromStyles({
    default: color(palette.text),
    keyword: { ...color(palette.accent), bold: true },
    string: color(palette.success),
    comment: { ...color(palette.muted), italic: true },
    number: color(palette.link),
    function: color(palette.warm),
    type: color(palette.cool),
    variable: color(palette.text),
    property: color(palette.link),
    "markup.heading": { ...color(palette.accent), bold: true },
    "markup.strong": { ...color(palette.text), bold: true },
    "markup.italic": { ...color(palette.muted), italic: true },
    "markup.link": { ...color(palette.link), underline: true },
    "markup.link.label": { ...color(palette.link), underline: true },
    "markup.link.url": { ...color(palette.link), underline: true },
    "markup.raw": color(palette.warm),
    conceal: color(palette.faint),
  })
}

export function composerSyntaxStyle(palette: Palette): SyntaxStyle {
  return SyntaxStyle.fromStyles({
    [IMAGE_PLACEHOLDER_STYLE]: { fg: parseColor(palette.accent), bold: true },
  })
}

export function transcriptTheme(palette: Palette, backgroundKnown: boolean): TranscriptTheme {
  return {
    text: palette.text,
    muted: palette.muted,
    error: palette.error,
    user: palette.user,
    userBackground: backgroundKnown ? palette.userBackground : null,
    border: palette.border,
    syntax: syntaxStyle(palette),
  }
}

export function commandMenuTheme(palette: Palette): CommandMenuTheme {
  return {
    text: palette.text,
    muted: palette.muted,
    border: palette.border,
    accent: palette.accent,
    warning: palette.warning,
    selectedBackground: palette.userBackground,
  }
}

export function runtimeControlsTheme(palette: Palette) {
  return {
    ...commandMenuTheme(palette),
    accent: palette.accent,
    faint: palette.faint,
  }
}

export function contextPanelTheme(palette: Palette): ContextPanelTheme {
  return {
    text: palette.text,
    border: palette.border,
    accent: palette.accent,
  }
}

export function usagePanelTheme(palette: Palette): UsagePanelTheme {
  return { ...palette, cached: palette.cool }
}

export function diffViewerTheme(palette: Palette, backgroundKnown: boolean): DiffViewerTheme {
  const light = palette === LIGHT
  return {
    text: palette.text,
    muted: palette.muted,
    border: palette.border,
    accent: palette.accent,
    success: palette.success,
    error: palette.error,
    addedBackground: backgroundKnown ? light ? "#E7F6EC" : "#142D22" : null,
    removedBackground: backgroundKnown ? light ? "#FCE8EA" : "#352024" : null,
    syntax: syntaxStyle(palette),
  }
}

export function queuePreviewTheme(palette: Palette): QueuePreviewTheme {
  return {
    accent: palette.accent,
    muted: palette.muted,
    faint: palette.faint,
  }
}

export function recoveryNoticeTheme(palette: Palette): RecoveryNoticeTheme {
  return {
    text: palette.text,
    muted: palette.muted,
    border: palette.border,
    accent: palette.accent,
    warning: palette.warning,
    error: palette.error,
  }
}

export function footerHintTheme(palette: Palette): FooterHintTheme {
  return {
    accent: palette.accent,
    danger: palette.error,
    muted: palette.muted,
    separator: palette.faint,
  }
}

export function shimmerStatus(
  label: string,
  suffix: string,
  frame: number,
  palette: Palette,
): StyledText {
  const chars = Array.from(label)
  // Sweep immediately, then leave a quiet pause before repeating. The text
  // keeps a constant width throughout, so the footer never jitters.
  const position = frame % (chars.length + SHIMMER_PAUSE)
  if (palette === TERMINAL) {
    // Terminal-default colors cannot be interpolated without guessing the
    // terminal theme, so move a bold band while preserving native color intent.
    const foreground = parseColor(palette.text)
    const chunks: TextChunk[] = chars.map((text, index) => ({
      __isChunk: true,
      text,
      fg: foreground,
      attributes: Math.abs(index - position) <= TERMINAL_SHIMMER_BAND
        ? TextAttributes.BOLD
        : 0,
    }))
    chunks.push({ __isChunk: true, text: suffix, fg: foreground })
    return new StyledText(chunks)
  }
  const base = parseColor(palette.muted).toInts()
  const highlight = parseColor(palette.accent).toInts()
  const chunks: TextChunk[] = chars.map((text, index) => {
    const distance = Math.abs(index - position)
    const intensity = distance > SHIMMER_BAND
      ? 0
      : (1 + Math.cos(Math.PI * distance / SHIMMER_BAND)) / 2
    return {
      __isChunk: true,
      text,
      fg: RGBA.fromInts(
        Math.round(base[0] + (highlight[0] - base[0]) * intensity),
        Math.round(base[1] + (highlight[1] - base[1]) * intensity),
        Math.round(base[2] + (highlight[2] - base[2]) * intensity),
      ),
    }
  })
  chunks.push({ __isChunk: true, text: suffix, fg: parseColor(palette.muted) })
  return new StyledText(chunks)
}
