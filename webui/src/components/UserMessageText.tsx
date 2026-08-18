import { Fragment } from "react";
import { useTranslation } from "react-i18next";

import {
  CapabilityMentionToken,
  SessionReferenceToken,
  splitCapabilityMentionSegments,
  splitSessionReferenceSegments,
  type CapabilityMentionSegment,
  type SessionReferenceSegment,
} from "@/components/CliAppMentionText";
import {
  INLINE_TOKEN_HIGHLIGHT_COLOR,
  InlineTokenHighlight,
} from "@/components/InlineTokenHighlight";
import type {
  CliAppInfo,
  McpPresetInfo,
  SessionHandle,
  SessionMention,
  UICliAppAttachment,
  UIMcpPresetAttachment,
} from "@/lib/types";

type SkillReferenceSegment =
  | { kind: "text"; text: string }
  | { kind: "skill"; text: string; name: string };

type UserMessageSegment =
  | CapabilityMentionSegment
  | SessionReferenceSegment
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
  sessionHandles: SessionHandle[],
  attachedCliApps: UICliAppAttachment[],
  attachedMcpPresets: UIMcpPresetAttachment[],
): UserMessageSegment[] {
  const segments: UserMessageSegment[] = [];
  const structuredAtNamespaces = new Map<string, "handle" | "cli" | "mcp">();
  sessionHandles.forEach((handle) => {
    structuredAtNamespaces.set(handle.name.toLowerCase(), "handle");
  });
  attachedCliApps.forEach((app) => {
    const name = app.name.toLowerCase();
    if (!structuredAtNamespaces.has(name)) structuredAtNamespaces.set(name, "cli");
  });
  attachedMcpPresets.forEach((preset) => {
    const name = preset.name.toLowerCase();
    if (!structuredAtNamespaces.has(name)) structuredAtNamespaces.set(name, "mcp");
  });
  const structuredAtNames = new Set(structuredAtNamespaces.keys());
  const replayCliApps = cliApps.filter((app) => {
    const owner = structuredAtNamespaces.get(app.name.toLowerCase());
    return owner === undefined || owner === "cli";
  });
  const replayMcpPresets = mcpPresets.filter((preset) => {
    const owner = structuredAtNamespaces.get(preset.name.toLowerCase());
    return owner === undefined || owner === "mcp";
  });
  const replaySessionHandles = sessionHandles.filter((handle) => (
    structuredAtNamespaces.get(handle.name.toLowerCase()) === "handle"
  ));
  const hashSegments = splitSessionReferenceSegments(value, sessionMentions);
  const hashSessionKeys = new Set(hashSegments.flatMap((segment) => (
    segment.kind === "session" ? [segment.mention.session_key] : []
  )));
  const legacySessionMentions = sessionMentions.filter((mention) => (
    !hashSessionKeys.has(mention.session_key)
    && !structuredAtNames.has(mention.name.toLowerCase())
  ));

  const appendCapabilitiesAndSkills = (text: string) => {
    for (const capability of splitCapabilityMentionSegments(
      text,
      replayCliApps,
      replayMcpPresets,
      replaySessionHandles,
    )) {
      if (capability.kind === "text") {
        segments.push(...splitSkillReferenceSegments(capability.text));
      } else {
        segments.push(capability);
      }
    }
  };

  for (const hashSegment of hashSegments) {
    if (hashSegment.kind === "session") {
      segments.push(hashSegment);
      continue;
    }
    for (const legacySegment of splitSessionReferenceSegments(
      hashSegment.text,
      legacySessionMentions,
      undefined,
      true,
    )) {
      if (legacySegment.kind === "session") {
        segments.push(legacySegment);
      } else {
        appendCapabilitiesAndSkills(legacySegment.text);
      }
    }
  }
  return segments;
}

export function UserMessageText({
  text,
  cliApps,
  mcpPresets,
  sessionMentions = [],
  sessionHandles = [],
  attachedCliApps = [],
  attachedMcpPresets = [],
}: {
  text: string;
  cliApps: CliAppInfo[];
  mcpPresets: McpPresetInfo[];
  sessionMentions?: SessionMention[];
  sessionHandles?: SessionHandle[];
  attachedCliApps?: UICliAppAttachment[];
  attachedMcpPresets?: UIMcpPresetAttachment[];
}) {
  const { t } = useTranslation();
  const segments = splitUserMessageSegments(
    text,
    cliApps,
    mcpPresets,
    sessionMentions,
    sessionHandles,
    attachedCliApps,
    attachedMcpPresets,
  );
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
            title={t("message.skill", { name: segment.name })}
            color={INLINE_TOKEN_HIGHLIGHT_COLOR}
          >
            {segment.name}
          </InlineTokenHighlight>
        );
        if (segment.kind === "session") return (
          <SessionReferenceToken
            key={`session-${segment.mention.session_key}-${index}`}
            mention={segment.mention}
            label={segment.text}
            variant="message"
          />
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
