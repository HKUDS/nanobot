import { useState } from "react";

import { ModelFallbackNotice } from "@/components/thread/ModelFallbackNotice";
import { RecoveryNotice } from "@/components/thread/RecoveryNotice";
import { SandboxNotice } from "@/components/thread/SandboxNotice";
import { StreamErrorNotice } from "@/components/thread/StreamErrorNotice";
import { ThreadComposer } from "@/components/thread/ThreadComposer";
import { ThreadMessages } from "@/components/thread/ThreadMessages";
import { ThreadToastViewport } from "@/components/ui/toast";
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
  const gateway = parameters.get("gateway") ?? "bwrap";
  const backend = gateway === "bwrap" || gateway === "seatbelt" ? gateway : null;
  const failureKind = parameters.get("reason") ?? "authentication";
  const threadMessages: UIMessage[] = failureKind.startsWith("empty_final_response")
    ? [{ id: "question", role: "user", content: "请总结刚才的工具结果。", createdAt: 1_700_000_000_000 }] : messages;
  const notice = parameters.get("notice") ?? "recovery";
  return <main className="relative min-h-screen bg-background p-4 text-foreground">
    {visible && notice === "recovery" && <ThreadToastViewport><RecoveryNotice
      state={{ recovery_id: "fixture-recovery", status: "awaiting_user", reason: "model_request_failed", failure_error_kind: failureKind }}
      onContinue={async () => { setVisible(false); setAction("continued"); }}
      onDismiss={async () => dismiss()}
      onOpenSettings={settings}
    /></ThreadToastViewport>}
    <section className="mx-auto max-w-3xl py-8">
      <ThreadMessages messages={threadMessages} isStreaming={false} />
    </section>
    <div className={variant === "hero" ? "thread-composer-stack is-hero" : "thread-composer-stack"}>
      {visible && (notice === "stream"
        ? <StreamErrorNotice error={{ kind: "model_request_failed", chatId: "fixture", errorKind: "authentication" }} onDismiss={dismiss} onOpenSettings={settings} />
        : notice === "fallback"
        ? <ModelFallbackNotice model="Fallback model" onDismiss={dismiss} onOpenSettings={settings} />
        : notice === "sandbox"
        ? <SandboxNotice issue="missing" backend={backend} onDismiss={dismiss} onOpenSettings={settings} />
        : null)}
      <ThreadComposer variant={variant} onSend={() => {}} workspaceControlsHidden />
    </div>
    <output aria-label="Fixture action">{action}</output>
  </main>;
}
