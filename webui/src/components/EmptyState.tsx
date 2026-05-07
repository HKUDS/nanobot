import { MessageSquarePlus } from "lucide-react";

import { Button } from "@/components/ui/button";

export function EmptyState({
  onNewChat,
}: {
  onNewChat: () => void;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
      <MessageSquarePlus
        className="h-10 w-10 text-muted-foreground"
        aria-hidden
      />
      <div className="space-y-1">
        <p className="text-lg font-medium">No chats yet</p>
        <p className="max-w-sm text-sm text-muted-foreground">
          Start a conversation — your sessions are stored locally on the nanobot
          workspace and stay available across reloads.
        </p>
      </div>
      <Button onClick={onNewChat}>New chat</Button>
    </div>
  );
}
