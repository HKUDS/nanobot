import { MarkdownText } from "@/components/MarkdownText";
import {
  CliAppMentionToken,
  McpPresetMentionToken,
  splitCapabilityMentionSegments,
  type CapabilityMentionSegment,
} from "@/components/CliAppMentionText";
import {
  INLINE_TOKEN_HIGHLIGHT_COLOR,
  InlineTokenHighlight,
} from "@/components/InlineTokenHighlight";
import type { CliAppInfo, McpPresetInfo } from "@/lib/types";

type SkillReferenceSegment =
  | { kind: "text"; text: string }
  | { kind: "skill"; text: string; name: string };

type UserMessageSegment =
  | CapabilityMentionSegment
  | { kind: "skill"; text: string; name: string };

function splitSkillReferenceSegments(value: string): SkillReferenceSegment[] {
  if (!value) return [];
  const segments: SkillReferenceSegment[] = [];
  const referenceRe = /\$([A-Za-z0-9_-]+)/g;
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = referenceRe.exec(value)) !== null) {
    const name = match[1] ?? "";
    if (match.index > cursor) {
      segments.push({ kind: "text", text: value.slice(cursor, match.index) });
    }
    segments.push({
      kind: "skill",
      text: value.slice(match.index, referenceRe.lastIndex),
      name,
    });
    cursor = referenceRe.lastIndex;
  }
  if (cursor < value.length) {
    segments.push({ kind: "text", text: value.slice(cursor) });
  }
  return segments.length ? segments : [{ kind: "text", text: value }];
}

function splitUserMessageSegments(
  value: string,
  cliApps: CliAppInfo[],
  mcpPresets: McpPresetInfo[],
): UserMessageSegment[] {
  const segments: UserMessageSegment[] = [];
  for (const segment of splitCapabilityMentionSegments(value, cliApps, mcpPresets)) {
    if (segment.kind === "text") {
      segments.push(...splitSkillReferenceSegments(segment.text));
    } else {
      segments.push(segment);
    }
  }
  return segments;
}

function MarkdownUserTextSegment({ text }: { text: string }) {
  const match = /^(\s*)([\s\S]*?\S)?(\s*)$/.exec(text);
  const leading = match?.[1] ?? "";
  const content = match?.[2] ?? "";
  const trailing = match?.[3] ?? "";
  if (!content) return <>{text}</>;
  return (
    <>
      {leading ? <span>{leading}</span> : null}
      <MarkdownText
        className="prose-p:my-0 prose-headings:my-1 prose-ul:my-1 prose-ol:my-1"
      >
        {content}
      </MarkdownText>
      {trailing ? <span>{trailing}</span> : null}
    </>
  );
}

export function UserMessageText({
  text,
  cliApps,
  mcpPresets,
}: {
  text: string;
  cliApps: CliAppInfo[];
  mcpPresets: McpPresetInfo[];
}) {
  const segments = splitUserMessageSegments(text, cliApps, mcpPresets);
  return (
    <>
      {segments.map((segment, index) => {
        if (segment.kind === "text") {
          return <MarkdownUserTextSegment key={`text-${index}`} text={segment.text} />;
        }
        if (segment.kind === "skill") return (
          <InlineTokenHighlight
            key={`skill-${segment.name}-${index}`}
            testId={`message-skill-reference-${segment.name.toLowerCase()}`}
            title={`Skill: ${segment.name}`}
            color={INLINE_TOKEN_HIGHLIGHT_COLOR}
            className="font-medium"
          >
            {segment.text}
          </InlineTokenHighlight>
        );
        if (segment.kind === "cli") return (
          <CliAppMentionToken
            key={`cli-${segment.app.name}-${index}`}
            app={segment.app}
            label={segment.text}
            variant="message"
          />
        );
        return (
          <McpPresetMentionToken
            key={`mcp-${segment.preset.name}-${index}`}
            preset={segment.preset}
            label={segment.text}
            variant="message"
          />
        );
      })}
    </>
  );
}
