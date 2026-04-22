import { MessageBubble } from "@/components/MessageBubble";
import type { UIMessage } from "@/lib/types";

interface ThreadMessagesProps {
  messages: UIMessage[];
}

export function ThreadMessages({ messages }: ThreadMessagesProps) {
  return (
    <div className="flex w-full flex-col gap-5">
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}
    </div>
  );
}
