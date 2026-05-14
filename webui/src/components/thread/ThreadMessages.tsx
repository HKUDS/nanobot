import { MessageBubble } from "@/components/MessageBubble";
import {
  AgentActivityCluster,
  isAgentActivityMember,
} from "@/components/thread/AgentActivityCluster";
import type { UIMessage } from "@/lib/types";

interface ThreadMessagesProps {
  messages: UIMessage[];
  /** When true, agent turn still in flight — keeps activity cluster expanded. */
  isStreaming?: boolean;
}

type DisplayUnit =
  | { type: "cluster"; messages: UIMessage[] }
  | { type: "single"; message: UIMessage };

function buildDisplayUnits(messages: UIMessage[]): DisplayUnit[] {
  const out: DisplayUnit[] = [];
  let i = 0;
  while (i < messages.length) {
    const m = messages[i];
    if (isAgentActivityMember(m)) {
      const cluster: UIMessage[] = [];
      while (i < messages.length && isAgentActivityMember(messages[i])) {
        cluster.push(messages[i]);
        i += 1;
      }
      out.push({ type: "cluster", messages: cluster });
      continue;
    }
    out.push({ type: "single", message: m });
    i += 1;
  }
  return out;
}

export function ThreadMessages({ messages, isStreaming = false }: ThreadMessagesProps) {
  const units = buildDisplayUnits(messages);

  return (
    <div className="flex w-full flex-col">
      {units.map((unit, index) => {
        const prev = units[index - 1];
        const marginTop =
          index > 0
            ? marginAfterPrevUnit(prev)
            : "";
        const next = units[index + 1];
        const hasBodyBelow =
          unit.type === "cluster"
          && next?.type === "single"
          && next.message.role === "assistant";

        return (
          <div key={unitKey(unit, index)} className={marginTop}>
            {unit.type === "cluster" ? (
              <AgentActivityCluster
                messages={unit.messages}
                isTurnStreaming={isStreaming}
                hasBodyBelow={hasBodyBelow}
              />
            ) : (
              <MessageBubble message={unit.message} />
            )}
          </div>
        );
      })}
    </div>
  );
}

function unitKey(unit: DisplayUnit, index: number): string {
  if (unit.type === "cluster") {
    const anchor = unit.messages[0]?.id;
    return anchor != null ? `cluster-${anchor}` : `cluster-idx-${index}`;
  }
  return unit.message.id;
}

function marginAfterPrevUnit(prev: DisplayUnit): string {
  if (prev.type === "cluster") {
    return "mt-4";
  }
  const p = prev.message;
  const denseP =
    p.kind === "trace"
    || (
      p.role === "assistant"
      && p.content.trim().length === 0
      && (!!p.reasoning || !!p.reasoningStreaming)
    );
  if (denseP) {
    return "mt-2";
  }
  return "mt-5";
}
