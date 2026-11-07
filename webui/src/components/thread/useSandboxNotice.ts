import { useEffect, useMemo, useState } from "react";

import type { NanobotClient } from "@/lib/nanobot-client";
import { normalizeToolProgressEvents } from "@/lib/tool-traces";
import type { SandboxIssue } from "./SandboxNotice";

const issues = new Map<string, SandboxIssue>([
  ["sandbox_launcher_missing", "missing"],
  ["sandbox_path_not_absolute", "path"],
  ["sandbox_not_executable", "path"],
  ["sandbox_path_unavailable", "path"],
  ["sandbox_agent_writable", "permissions"],
  ["sandbox_unprotected_installation", "permissions"],
  ["sandbox_start_failed", "startup"],
]);

/** Observe live execution only; opening history must not replay old warnings. */
export function useSandboxNotice(client: NanobotClient, chatId: string | null, enabled: boolean) {
  const scope = useMemo(() => ({ client, chatId, enabled }), [client, chatId, enabled]);
  const [notice, setNotice] = useState<{
    scope: typeof scope;
    issue: SandboxIssue;
    turnId: string | null;
    dismissed: boolean;
  } | null>(null);
  useEffect(() => {
    setNotice(null);
    if (!enabled || !chatId) return;
    return client.onChat(chatId, (event) => {
      if ((event.event === "message_accepted" || event.event === "user_message") && event.starts_turn) {
        setNotice(null);
        return;
      }
      if (event.event !== "message") return;
      const latestTurn = client.getRunState(chatId).latestTurnId;
      if (event.turn_id && latestTurn && event.turn_id !== latestTurn) return;
      const turnId = event.turn_id ?? latestTurn;
      for (const tool of normalizeToolProgressEvents(event.tool_events)) {
        if (tool.name !== "exec") continue;
        if (tool.phase === "end") {
          setNotice(null);
        } else if (tool.phase === "error" && typeof tool.error_code === "string") {
          const issue = issues.get(tool.error_code);
          if (!issue) continue;
          setNotice((current) => current?.scope === scope && current.issue === issue && current.turnId === turnId
            ? current : { scope, issue, turnId, dismissed: false });
        }
      }
    });
  }, [client, chatId, enabled, scope]);
  return {
    issue: enabled && notice?.scope === scope && !notice.dismissed ? notice.issue : null,
    dismiss: () => setNotice((current) => current?.scope === scope ? { ...current, dismissed: true } : current),
  };
}
