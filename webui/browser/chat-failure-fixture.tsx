import { useState } from "react";

import { ModelFallbackNotice } from "@/components/thread/ModelFallbackNotice";
import { RecoveryNotice } from "@/components/thread/RecoveryNotice";
import { StreamErrorNotice } from "@/components/thread/StreamErrorNotice";
import { ThreadComposer } from "@/components/thread/ThreadComposer";
import { ThreadMessages } from "@/components/thread/ThreadMessages";
import { useReadingTypography } from "@/hooks/useReadingTypography";
import { formatQuotedUserMessage } from "@/lib/user-message-quote";
import type { UIMessage } from "@/lib/types";

const messages: UIMessage[] = [{
  id: "failed-question",
  role: "user" as const,
  content: formatQuotedUserMessage("Please explain this failure. 请解释这个错误。", "Earlier context / 之前的上下文"),
  images: [{ url: "data:image/svg+xml," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="160" height="120"><rect width="160" height="120" fill="#ddd"/></svg>'), name: "Failure screenshot" }],
  createdAt: 1_700_000_000_000,
}];

export function ChatFailureFixture({ parameters }: { parameters: URLSearchParams }) {
  useReadingTypography();
  const [visible, setVisible] = useState(true);
  const [action, setAction] = useState("");
  const variant = parameters.get("variant") === "hero" ? "hero" : "thread";
  const dismiss = () => { setVisible(false); setAction("dismissed"); };
  const settings = () => setAction("settings");
  return <main className="min-h-screen bg-background p-4 text-foreground">
    <section className="mx-auto max-w-3xl py-8">
      <ThreadMessages messages={messages} isStreaming={false} />
    </section>
    <div className={variant === "hero" ? "thread-composer-stack is-hero" : "thread-composer-stack"}>
      {visible && (parameters.get("notice") === "stream"
        ? <StreamErrorNotice error={{ kind: "model_request_failed", chatId: "fixture", errorKind: "authentication" }} onDismiss={dismiss} onOpenSettings={settings} />
        : parameters.get("notice") === "fallback"
        ? <ModelFallbackNotice model="Fallback model" onDismiss={dismiss} onOpenSettings={settings} />
        : <RecoveryNotice
          state={{ recovery_id: "fixture-recovery", status: "awaiting_user", reason: "model_request_failed", failure_error_kind: "authentication" }}
          onContinue={async () => { setVisible(false); setAction("continued"); }}
          onDismiss={async () => dismiss()}
          onOpenSettings={settings}
        />)}
      <ThreadComposer variant={variant} onSend={() => {}} workspaceControlsHidden />
    </div>
    <output aria-label="Fixture action">{action}</output>
  </main>;
}
