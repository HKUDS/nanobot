import type { ThreadProjectionEvent, WebuiThreadPersistedPayload } from "./types";

function isAnswer(event: ThreadProjectionEvent): boolean {
  return event.event === "delta" || event.event === "stream_end"
    || (event.event === "message" && event.kind !== "tool_hint" && event.kind !== "progress" && event.kind !== "reasoning");
}

/** Coalesce continuous raw ranges; canonical recovery replaces stored answers, not other activities. */
export function joinThreadFragments(
  previous: readonly WebuiThreadPersistedPayload[],
  current: WebuiThreadPersistedPayload,
): { pages: WebuiThreadPersistedPayload[]; body: WebuiThreadPersistedPayload; withdrawn: ThreadProjectionEvent[] } {
  const range = current.page?.record_range;
  if (!range) return { pages: [...previous], body: current, withdrawn: [] };
  const same = (page: WebuiThreadPersistedPayload) => page.page?.record_range?.turn === range.turn
    && page.page.history_generation === current.page?.history_generation;
  const ordered = [...previous.filter(same), current].sort((a, b) => {
    const left = a.page!.record_range!;
    const right = b.page!.record_range!;
    return left.start - right.start || right.end - left.end;
  });
  const groups: WebuiThreadPersistedPayload[][] = [];
  for (const page of ordered) {
    const group = groups.at(-1);
    const end = group ? Math.max(...group.map((item) => item.page!.record_range!.end)) : -1;
    if (!group || page.page!.record_range!.start > end) groups.push([page]);
    else group.push(page);
  }

  const recovered = ordered.some((page) => page.page?.recovered_answers === true);
  const withdrawn: ThreadProjectionEvent[] = [];
  const latestEvents = new Map(current.events.map((event) => [event.projection_id, event]));
  let selected: WebuiThreadPersistedPayload | undefined;
  const pages = groups.map((group) => {
    const first = group[0];
    const last = group.reduce((a, b) => a.page!.record_range!.end >= b.page!.record_range!.end ? a : b);
    const events: ThreadProjectionEvent[] = [];
    const seen = new Set<string>();
    const completed = new Set<string>();
    let boundary: number | undefined;
    for (const page of group) {
      for (const turn of page.completed_turn_ids ?? []) completed.add(turn);
      for (const [index, event] of page.events.entries()) {
        if (boundary === undefined && page.fork_boundary_event_index === index) boundary = events.length;
        if (recovered && !page.page?.recovered_answers && isAnswer(event)) {
          if (page !== current) withdrawn.push(event);
          continue;
        }
        if (event.projection_id && seen.has(event.projection_id)) continue;
        if (event.projection_id) seen.add(event.projection_id);
        events.push(event.projection_id ? latestEvents.get(event.projection_id) ?? event : event);
      }
      if (boundary === undefined && page.fork_boundary_event_index === page.events.length) boundary = events.length;
    }
    const start = first.page!.record_range!.start;
    const end = last.page!.record_range!.end;
    const complete = start === 0 && events.some((event) => event.event === "turn_end");
    const merged: WebuiThreadPersistedPayload = {
      ...first,
      events,
      completed_turn_ids: [...completed],
      page: { ...first.page!, after_cursor: last.page!.after_cursor, has_more_after: last.page!.has_more_after,
        record_range: { turn: range.turn, start, end }, truncated_oversized_turn: !complete,
        ...(recovered ? { recovered_answers: true } : {}) },
    };
    if (boundary === undefined) delete merged.fork_boundary_event_index;
    else merged.fork_boundary_event_index = boundary;
    if (group.includes(current)) selected = merged;
    return merged;
  });
  const group = selected!;
  const body = { ...current, events: group.events, completed_turn_ids: group.completed_turn_ids,
    page: { ...current.page!, before_cursor: group.page!.before_cursor, has_more_before: group.page!.has_more_before,
      user_message_offset: group.page!.user_message_offset, after_cursor: group.page!.after_cursor,
      has_more_after: group.page!.has_more_after, record_range: group.page!.record_range,
      truncated_oversized_turn: group.page!.truncated_oversized_turn, recovered_answers: group.page!.recovered_answers } };
  if (group.fork_boundary_event_index === undefined) delete body.fork_boundary_event_index;
  else body.fork_boundary_event_index = group.fork_boundary_event_index;
  return { pages: [...previous.filter((page) => !same(page)), ...pages], body, withdrawn };
}
