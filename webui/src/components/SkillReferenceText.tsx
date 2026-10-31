import {
  INLINE_REFERENCE_HIGHLIGHT_COLOR,
  InlineTokenHighlight,
} from "@/components/InlineTokenHighlight";
import type { CapabilityMentionSegment } from "@/lib/composer-mention-text";

export type InlineReferenceSegment =
  | CapabilityMentionSegment
  | { kind: "skill"; text: string; name: string };

export function withSkillReferences(segments: CapabilityMentionSegment[]): InlineReferenceSegment[] {
  const result: InlineReferenceSegment[] = [];
  for (const segment of segments) {
    if (segment.kind !== "text") {
      result.push(segment);
      continue;
    }
    let cursor = 0;
    for (const match of segment.text.matchAll(/\$([A-Za-z0-9_-]+)/g)) {
      if (match.index > cursor) {
        result.push({ kind: "text", text: segment.text.slice(cursor, match.index) });
      }
      result.push({ kind: "skill", text: match[0], name: match[0].slice(1) });
      cursor = match.index + match[0].length;
    }
    if (cursor < segment.text.length) {
      result.push({ kind: "text", text: segment.text.slice(cursor) });
    }
  }
  return result;
}

export function SkillReferenceToken({ name, testId }: { name: string; testId: string }) {
  return (
    <InlineTokenHighlight
      testId={testId}
      className="font-normal"
      color={INLINE_REFERENCE_HIGHLIGHT_COLOR}
    >
      <span className="opacity-90">$</span>{name}
    </InlineTokenHighlight>
  );
}
