import { MessageBubble } from "@/components/MessageBubble";
import { cn } from "@/lib/utils";
import type { UIMessage } from "@/lib/types";

interface ThreadMessagesProps {
  messages: UIMessage[];
}

export function ThreadMessages({ messages }: ThreadMessagesProps) {
  return (
    <div className="flex w-full flex-col">
      {messages.map((message, index) => {
        const prev = messages[index - 1];
        const compact = isAuxiliaryRow(message) && prev && isAuxiliaryRow(prev);
        return (
          <div
            key={message.id}
            className={cn(index > 0 && (compact ? "mt-2" : "mt-5"))}
          >
            <MessageBubble message={message} />
          </div>
        );
      })}
    </div>
  );
}

function isAuxiliaryRow(message: UIMessage): boolean {
  return (
    message.kind === "trace"
    || (
      message.role === "assistant"
      && message.content.trim().length === 0
      && (!!message.reasoning || !!message.reasoningStreaming)
    )
  );
}
