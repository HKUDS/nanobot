import { Fragment } from "react";

import {
  CapabilityMentionToken,
  splitCapabilityMentionSegments,
} from "@/components/CliAppMentionText";
import { SkillReferenceToken, withSkillReferences } from "@/components/SkillReferenceText";
import type { CliAppInfo, McpPresetInfo, SessionMention } from "@/lib/types";

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
  const segments = withSkillReferences(
    splitCapabilityMentionSegments(text, cliApps, mcpPresets, sessionMentions),
  );
  return (
    <>
      {segments.map((segment, index) => {
        if (segment.kind === "text") {
          return <Fragment key={`text-${index}`}>{segment.text}</Fragment>;
        }
        if (segment.kind === "skill") return (
          <SkillReferenceToken
            key={`skill-${segment.name}-${index}`}
            name={segment.name}
            testId={`message-skill-reference-${segment.name.toLowerCase()}`}
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
