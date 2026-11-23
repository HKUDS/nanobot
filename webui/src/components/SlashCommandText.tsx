import {
  INLINE_REFERENCE_HIGHLIGHT_COLOR,
  InlineTokenHighlight,
} from "@/components/InlineTokenHighlight";

interface SlashCommandTextProps {
  command: string;
  testId?: string;
}

export function SlashCommandText({
  command,
  testId = "message-slash-command",
}: SlashCommandTextProps) {
  return (
    <InlineTokenHighlight
      testId={testId}
      className="font-normal"
      color={INLINE_REFERENCE_HIGHLIGHT_COLOR}
    >
      <span className="opacity-90">/</span>{command.slice(1)}
    </InlineTokenHighlight>
  );
}
