import { useState } from "react";
import { ChevronRight, Layers } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ReasoningBubble, StreamingLabelSheen, TraceGroup } from "@/components/MessageBubble";
import { cn } from "@/lib/utils";
import type { UIMessage } from "@/lib/types";

/** Scrollport height for the Cursor-style “live trace” strip (tailwind spacing). */
const CLUSTER_SCROLL_MAX_CLASS = "max-h-52";

export function isReasoningOnlyAssistant(m: UIMessage): boolean {
  if (m.role !== "assistant" || m.kind === "trace") return false;
  if (m.content.trim().length > 0) return false;
  return !!(m.reasoning?.length || m.reasoningStreaming || m.isStreaming);
}

export function isAgentActivityMember(m: UIMessage): boolean {
  return isReasoningOnlyAssistant(m) || m.kind === "trace";
}

function countToolCalls(messages: UIMessage[]): number {
  let n = 0;
  for (const m of messages) {
    if (m.kind !== "trace") continue;
    const lines = m.traces?.length ?? (m.content.trim() ? 1 : 0);
    n += Math.max(lines, 1);
  }
  return n;
}

interface AgentActivityClusterProps {
  messages: UIMessage[];
  /** True while the session turn is still running (drives “Working…” copy + header sheen). */
  isTurnStreaming: boolean;
  hasBodyBelow: boolean;
}

/**
 * Outer fold wrapping interleaved reasoning-only assistant rows and tool-trace rows.
 * Fixed max height with inner scroll; each block keeps its own small collapsible (reasoning / tools).
 */
export function AgentActivityCluster({
  messages,
  isTurnStreaming,
  hasBodyBelow,
}: AgentActivityClusterProps) {
  const { t } = useTranslation();
  const reasoningSteps = messages.filter(isReasoningOnlyAssistant).length;
  const toolCalls = countToolCalls(messages);

  const [userToggledOuter, setUserToggledOuter] = useState(false);
  const [outerOpenLocal, setOuterOpenLocal] = useState(false);
  /** Collapsed by default during “Working…” and after the turn; user expands to inspect traces. */
  const outerExpanded = userToggledOuter ? outerOpenLocal : false;

  const headerBusy = isTurnStreaming;

  const summary =
    isTurnStreaming
      ? reasoningSteps > 0
        ? t("message.agentActivityLiveSummary", {
            reasoning: reasoningSteps,
            tools: toolCalls,
            defaultValue: "Working… · {{reasoning}} steps · {{tools}} tool calls",
          })
        : t("message.agentActivityLiveToolsOnly", {
            tools: toolCalls,
            defaultValue: "Working… · {{tools}} tool calls",
          })
      : reasoningSteps > 0
        ? t("message.agentActivitySummary", {
            reasoning: reasoningSteps,
            tools: toolCalls,
            defaultValue: "{{reasoning}} steps · {{tools}} tool calls",
          })
        : t("message.agentActivityToolsOnly", {
            tools: toolCalls,
            defaultValue: "{{tools}} tool calls",
          });

  const toggleOuter = () => {
    setUserToggledOuter(true);
    setOuterOpenLocal((v) => (userToggledOuter ? !v : !outerExpanded));
  };

  return (
    <div className={cn("w-full", hasBodyBelow && "mb-2")}>
      <button
        type="button"
        onClick={toggleOuter}
        className={cn(
          "group flex w-full items-center gap-2 rounded-md px-2 py-1.5",
          "text-xs text-muted-foreground transition-colors hover:bg-muted/45",
        )}
        aria-expanded={outerExpanded}
      >
        <Layers className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <StreamingLabelSheen
          active={headerBusy}
          className="min-w-0 flex-1 text-left"
        >
          {summary}
        </StreamingLabelSheen>
        <ChevronRight
          aria-hidden
          className={cn(
            "h-3.5 w-3.5 shrink-0 transition-transform duration-200",
            outerExpanded && "rotate-90",
          )}
        />
      </button>

      {outerExpanded && (
        <div
          className={cn(
            "mt-1 overflow-hidden rounded-md border border-border/50 bg-muted/25",
          )}
        >
          <div
            className={cn(
              CLUSTER_SCROLL_MAX_CLASS,
              "overflow-y-auto px-2 py-1.5 scrollbar-thin scrollbar-track-transparent",
            )}
          >
            <div className="flex flex-col gap-2">
              {messages.map((m) => {
                if (isReasoningOnlyAssistant(m)) {
                  return (
                    <ReasoningBubble
                      key={m.id}
                      text={m.reasoning ?? ""}
                      streaming={!!m.reasoningStreaming}
                      hasBodyBelow={false}
                      embeddedInCluster
                    />
                  );
                }
                if (m.kind === "trace") {
                  return <TraceGroup key={m.id} message={m} animClass="" />;
                }
                return null;
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
