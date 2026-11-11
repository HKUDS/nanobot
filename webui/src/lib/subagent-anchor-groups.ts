import type { TurnUnit } from "@/lib/activity-timeline";
import { subagentCreateCallId } from "@/lib/subagent-create-activity";
import { canonicalToolTrace, formatToolCallTrace } from "@/lib/tool-traces";
import type { UIMessage } from "@/lib/types";

export type SubagentAnchor = NonNullable<UIMessage["subagentAnchor"]>;

/** Only the structured traces of the grouped create calls may sit between anchors. */
function interveningCreateCalls(unit: TurnUnit, turnId: string | undefined): string[] | null {
  if (unit.type !== "activity") return null;
  const calls: string[] = [];
  for (const message of unit.messages) {
    if (message.turnId !== turnId || message.kind !== "trace" || message.traceDetail
      || message.fileEdits?.length || message.reasoning || message.reasoningStreaming) return null;
    const events = message.toolEvents;
    if (!events?.length) return null;
    const lines = new Set(events.map(formatToolCallTrace).filter((line): line is string => line !== null).map(canonicalToolTrace));
    const traces = message.traces?.length ? message.traces : message.content ? [message.content] : [];
    if (traces.some((line) => !lines.has(canonicalToolTrace(line)))) return null;
    for (const event of events) {
      const callId = subagentCreateCallId(event);
      if (!callId) return null;
      calls.push(callId);
    }
  }
  return calls.length ? calls : null;
}

/** Map the first anchor of each run to its group and the remaining anchors to null. */
export function groupSubagentAnchors(units: readonly TurnUnit[]): Map<string, SubagentAnchor[] | null> {
  const result = new Map<string, SubagentAnchor[] | null>();
  const anchorAt = (index: number) => units[index]?.type === "message"
    ? (units[index] as Extract<TurnUnit, { type: "message" }>).message.subagentAnchor : undefined;
  for (let i = 0; i < units.length; i++) {
    const first = anchorAt(i);
    if (!first) continue;
    const firstUnit = units[i] as Extract<TurnUnit, { type: "message" }>;
    const turnId = firstUnit.message.turnId;
    const anchors = [first];
    const gaps: string[][] = [];
    let pending: string[] = [];
    let lastAnchorIndex = i;
    for (let j = i + 1; j < units.length; j++) {
      const next = anchorAt(j);
      if (next) {
        const nextUnit = units[j] as Extract<TurnUnit, { type: "message" }>;
        if (!turnId || nextUnit.message.turnId !== turnId) break;
        anchors.push(next);
        gaps.push(pending);
        pending = [];
        lastAnchorIndex = j;
        continue;
      }
      const calls = interveningCreateCalls(units[j], turnId);
      if (calls === null) break;
      pending.push(...calls);
    }
    const validCalls = new Set(anchors.map((anchor) => anchor.callId));
    let group: SubagentAnchor[] = [anchors[0]];
    const save = () => {
      result.set(group[0].taskId, group);
      for (const anchor of group.slice(1)) result.set(anchor.taskId, null);
    };
    for (let j = 1; j < anchors.length; j++) {
      if (gaps[j - 1].some((call) => !validCalls.has(call))) {
        save();
        group = [];
      }
      group.push(anchors[j]);
    }
    save();
    i = lastAnchorIndex;
  }
  return result;
}
