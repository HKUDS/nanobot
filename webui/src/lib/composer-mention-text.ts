import type { CapabilityMentionSegment } from "@/components/CliAppMentionText";

export function composerMentionLabel(segment: CapabilityMentionSegment): string {
  const app = segment.kind === "cli" ? segment.app : segment.kind === "mcp" ? segment.preset : null;
  if (!app) return segment.text;
  // A no-break space gives logos breathing room without separating them from the name.
  // Keep it in both the textarea and overlay, including while a logo is loading or unavailable.
  const gap = app.logo_url ? "\u00a0" : "";
  return `@${gap}${app.display_name?.trim().replace(/[\r\n\t]/g, " ") || app.name}`;
}

type MentionRange = { start: number; end: number; displayStart: number; displayEnd: number };
export interface ComposerMentionText {
  raw: string;
  display: string;
  mentions: MentionRange[];
}

/** The textarea and its overlay share display text; only the draft uses invocation identifiers. */
export function composerMentionText(segments: CapabilityMentionSegment[]): ComposerMentionText {
  let raw = "";
  let display = "";
  const mentions: MentionRange[] = [];
  for (const segment of segments) {
    const label = composerMentionLabel(segment);
    if (segment.kind === "cli" || segment.kind === "mcp") {
      mentions.push({
        start: raw.length,
        end: raw.length + segment.text.length,
        displayStart: display.length,
        displayEnd: display.length + label.length,
      });
    }
    raw += segment.text;
    display += label;
  }
  return { raw, display, mentions };
}

/** Decorate only untouched mentions while mirroring the IME's exact, uncommitted text. */
export function composerCompositionSegments(
  segments: CapabilityMentionSegment[],
  display: string,
  selection?: { start: number; end: number },
): CapabilityMentionSegment[] {
  const previous = segments.map(composerMentionLabel).join("");
  if (previous === display) return segments;
  let start = 0;
  while (start < Math.min(previous.length, display.length, selection?.start ?? Infinity)
    && previous[start] === display[start]) start++;
  let end = previous.length;
  let nextEnd = display.length;
  while (end > Math.max(start, selection?.end ?? 0) && nextEnd > start
    && previous[end - 1] === display[nextEnd - 1]) {
    end--;
    nextEnd--;
  }

  const result: CapabilityMentionSegment[] = [];
  let offset = 0;
  let cursor = 0;
  for (const segment of segments) {
    const label = composerMentionLabel(segment);
    const segmentStart = offset;
    offset += label.length;
    if (segment.kind === "text" || (offset > start && segmentStart < end)) continue;
    const shiftedStart = segmentStart >= end ? segmentStart + nextEnd - end : segmentStart;
    if (shiftedStart > cursor) result.push({ kind: "text", text: display.slice(cursor, shiftedStart) });
    result.push(segment);
    cursor = shiftedStart + label.length;
  }
  if (cursor < display.length) result.push({ kind: "text", text: display.slice(cursor) });
  return result;
}

export function mentionTextOffset(
  text: ComposerMentionText,
  offset: number,
  direction: "toRaw" | "toDisplay",
  bias: "start" | "end" | "nearest" = "nearest",
): number {
  offset = Math.max(0, Math.min(offset, direction === "toRaw" ? text.display.length : text.raw.length));
  let delta = 0;
  for (const mention of text.mentions) {
    const [start, end, targetStart, targetEnd] = direction === "toRaw"
      ? [mention.displayStart, mention.displayEnd, mention.start, mention.end]
      : [mention.start, mention.end, mention.displayStart, mention.displayEnd];
    if (offset <= start) break;
    if (offset < end) {
      return bias === "start" || (bias === "nearest" && offset - start < end - offset)
        ? targetStart : targetEnd;
    }
    delta = targetEnd - end;
  }
  return offset + delta;
}

/** Apply a native textarea edit, retaining the identities of untouched mentions. */
export function editComposerMentionText(
  text: ComposerMentionText,
  nextDisplay: string,
  caret: number,
  selection?: { start: number; end: number },
): { value: string; cursor: number } {
  let start = 0;
  // The caret disambiguates repeated text (e.g. inserting a space before an existing space).
  while (start < Math.min(text.display.length, nextDisplay.length, caret, selection?.start ?? Infinity)
    && text.display[start] === nextDisplay[start]) start++;
  let end = text.display.length;
  let nextEnd = nextDisplay.length;
  while (end > Math.max(start, selection?.end ?? 0) && nextEnd > Math.max(start, caret)
    && text.display[end - 1] === nextDisplay[nextEnd - 1]) {
    end--;
    nextEnd--;
  }
  // A partial deletion/replacement removes the mention as a unit, never a broken identifier.
  const rawStart = mentionTextOffset(text, start, "toRaw", "start");
  const rawEnd = mentionTextOffset(text, end, "toRaw", "end");
  const inserted = nextDisplay.slice(start, nextEnd);
  const value = text.raw.slice(0, rawStart) + inserted + text.raw.slice(rawEnd);
  return { value, cursor: Math.min(value.length, rawStart + Math.max(0, caret - start)) };
}
