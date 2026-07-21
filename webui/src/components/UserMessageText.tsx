import { CliAppMentionText } from "@/components/CliAppMentionText";
import {
  INLINE_TOKEN_HIGHLIGHT_COLOR,
  InlineTokenHighlight,
} from "@/components/InlineTokenHighlight";
import type { CliAppInfo, McpPresetInfo, SkillSummary } from "@/lib/types";

type SkillReferenceSegment =
  | { kind: "text"; text: string }
  | { kind: "skill"; text: string; skill: SkillSummary };

function splitSkillReferenceSegments(
  value: string,
  skills: SkillSummary[],
): SkillReferenceSegment[] {
  if (!value || skills.length === 0) {
    return value ? [{ kind: "text", text: value }] : [];
  }

  const skillsByName = new Map(
    skills
      .filter((skill) => skill.available)
      .map((skill) => [skill.name.toLowerCase(), skill]),
  );
  if (skillsByName.size === 0) return [{ kind: "text", text: value }];

  const segments: SkillReferenceSegment[] = [];
  const referenceRe = /\$([A-Za-z0-9_-]+)/g;
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = referenceRe.exec(value)) !== null) {
    const name = match[1] ?? "";
    const skill = skillsByName.get(name.toLowerCase());
    if (!skill) continue;

    if (match.index > cursor) {
      segments.push({ kind: "text", text: value.slice(cursor, match.index) });
    }
    segments.push({
      kind: "skill",
      text: value.slice(match.index, referenceRe.lastIndex),
      skill,
    });
    cursor = referenceRe.lastIndex;
  }
  if (cursor < value.length) {
    segments.push({ kind: "text", text: value.slice(cursor) });
  }
  return segments.length ? segments : [{ kind: "text", text: value }];
}

export function UserMessageText({
  text,
  skills,
  cliApps,
  mcpPresets,
}: {
  text: string;
  skills: SkillSummary[];
  cliApps: CliAppInfo[];
  mcpPresets: McpPresetInfo[];
}) {
  const segments = splitSkillReferenceSegments(text, skills);
  return (
    <>
      {segments.map((segment, index) => {
        if (segment.kind === "text") {
          return (
            <CliAppMentionText
              key={`text-${index}`}
              text={segment.text}
              cliApps={cliApps}
              mcpPresets={mcpPresets}
            />
          );
        }
        return (
          <InlineTokenHighlight
            key={`skill-${segment.skill.name}-${index}`}
            testId={`message-skill-reference-${segment.skill.name}`}
            title={`Skill: ${segment.skill.name}`}
            color={INLINE_TOKEN_HIGHLIGHT_COLOR}
            className="font-medium"
          >
            {segment.text}
          </InlineTokenHighlight>
        );
      })}
    </>
  );
}
