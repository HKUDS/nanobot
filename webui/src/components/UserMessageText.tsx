import { Fragment } from "react";

import {
  CapabilityMentionToken,
  splitCapabilityMentionSegments,
} from "@/components/CliAppMentionText";
import { InlineTokenHighlight } from "@/components/InlineTokenHighlight";
import type { CliAppInfo, McpPresetInfo, SessionMention } from "@/lib/types";
import type { CapabilityMentionSegment } from "@/lib/composer-mention-text";

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
  sessionMentions: SessionMention[],
): UserMessageSegment[] {
  const segments: UserMessageSegment[] = [];
  for (const segment of splitCapabilityMentionSegments(
    value,
    cliApps,
    mcpPresets,
    sessionMentions,
  )) {
    if (segment.kind === "text") {
      segments.push(...splitSkillReferenceSegments(segment.text));
    } else {
      segments.push(segment);
    }
  }
  return segments;
}

export function UserMessageText({
  text,
  cliApps,
  mcpPresets,
  sessionMentions = [],
}: {
  text: string;
  cliApps: CliAppInfo[];
  mcpPresets: McpPresetInfo[];
  sessionMentions?: SessionMention[];
}) {
  const segments = splitUserMessageSegments(text, cliApps, mcpPresets, sessionMentions);
  return (
    <>
      {segments.map((segment, index) => {
        if (segment.kind === "text") {
          return <Fragment key={`text-${index}`}>{segment.text}</Fragment>;
        }
        if (segment.kind === "skill") return (
          <InlineTokenHighlight
            key={`skill-${segment.name}-${index}`}
            testId={`message-skill-reference-${segment.name.toLowerCase()}`}
            className="font-normal"
            color="var(--skill-reference-foreground)"
          >
            <span className="opacity-90">$</span>{segment.name}
          </InlineTokenHighlight>
        );
        return (
          <CapabilityMentionToken
            key={`${segment.kind}-${index}`}
            segment={segment}
            variant="message"
          />
        );
      })}
    </>
  );
}
