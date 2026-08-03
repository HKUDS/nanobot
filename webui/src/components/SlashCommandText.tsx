import {
  INLINE_TOKEN_HIGHLIGHT_COLOR,
  InlineTokenHighlight,
} from "@/components/InlineTokenHighlight";

interface SlashCommandTextProps {
  command: string;
}

export function SlashCommandText({
  command,
}: SlashCommandTextProps) {
  return (
    <InlineTokenHighlight
      testId="message-slash-command"
      color={INLINE_TOKEN_HIGHLIGHT_COLOR}
      className="font-medium"
    >
      {command}
    </InlineTokenHighlight>
  );
}
