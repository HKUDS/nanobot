import {
  projectThreadEvent,
  type ThreadProjectionEffects,
  type ThreadProjectionState,
} from "./thread-event-projection";
import { persistedCanonicalRunState } from "./canonical-run-snapshot";
import { copyThreadCheckpoint, createThreadCheckpoint, type ThreadCheckpoint } from "./thread-checkpoint";
import { hasPendingAgentActivity } from "./activity-timeline";
import { reconcileModelRequest } from "./model-request";
import { joinThreadFragments } from "./thread-page-fragments";
import type { ThreadProjectionEvent, UIMessage, WebuiThreadPersistedPayload } from "./types";

type Ranges = Array<[number, number]>;
type Members = Map<string, Ranges>;
interface TextSource {
  turn: string;
  phase: "answer" | "reasoning";
  stream: string;
  after: number | null;
  through: number;
  end: number | null;
  snapshot: boolean;
  members: Ranges;
}
interface LiveContribution {
  event: ThreadProjectionEvent;
  now: number;
  revision: number;
  startSeq?: number;
  sideChannel?: boolean;
}
interface PendingFragmentGap {
  turn: number;
  oldEnd: number;
  front: number;
}
interface Unit {
  rows: Set<string>;
  sources: Set<string>;
  members: Members;
  text: TextSource[];
  introduced: number;
  order: number;
  received: number;
}
export interface ThreadPaging {
  loading: boolean;
  loadingOlder: boolean;
  error: string | null;
  olderError: string | null;
  beforeCursor: string | null;
  /** Null until a history read establishes the oldest loaded boundary. */
  hasMoreBefore: boolean | null;
  userMessageOffset: number;
  forkBoundaryMessageCount: number | null;
  truncated: boolean;
  version: number;
  lineage: number;
  hasPendingToolCalls: boolean;
  completedTurnIds: string[];
  completionIdsProvided: boolean;
  activeTurnId: string | null;
}
export interface ThreadRead {
  kind: "initial" | "latest" | "older";
  revision: number;
  lineage: number;
  before: string | null;
  empty: boolean;
}
export interface ThreadTranscriptSnapshot extends ThreadCheckpoint {
  units: Unit[];
  installed: Members;
  textCoverage: TextSource[];
  boundaries: Map<string, number>;
  knownTurns: Set<string>;
  paging: ThreadPaging;
  revision: number;
  fragments: WebuiThreadPersistedPayload[];
  live: LiveContribution[];
  historyGeneration: string | null;
  pendingFragmentGap: PendingFragmentGap | null;
}

function addRange(ranges: Ranges, first: number, last = first): void {
  let start = first;
  let end = last;
  let index = 0;
  while (index < ranges.length && ranges[index][1] + 1 < start) index++;
  const from = index;
  while (index < ranges.length && ranges[index][0] <= end + 1) {
    start = Math.min(start, ranges[index][0]);
    end = Math.max(end, ranges[index][1]);
    index++;
  }
  ranges.splice(from, index - from, [start, end]);
}
function contains(ranges: Ranges | undefined, seq: number): boolean {
  return ranges?.some(([first, last]) => first <= seq && seq <= last) === true;
}
function mergeMembers(target: Members, source: Members): void {
  for (const [turn, ranges] of source) {
    const existing = target.get(turn) ?? [];
    for (const [first, last] of ranges) addRange(existing, first, last);
    target.set(turn, existing);
  }
}
function copyMembers(value: Members): Members {
  return new Map(Array.from(value, ([key, ranges]) => [key, ranges.map(([a, b]) => [a, b])]));
}
function mergeCoveredMembers(target: Members, members: Members, coverage: Members): void {
  for (const [turn, ranges] of members) for (const [first, last] of ranges) {
    for (const [a, b] of coverage.get(turn) ?? []) {
      if (first <= b && a <= last) {
        const kept = target.get(turn) ?? [];
        addRange(kept, Math.max(first, a), Math.min(last, b));
        target.set(turn, kept);
      }
    }
  }
}
function copyText(value: TextSource): TextSource {
  return { ...value, members: value.members.map(([a, b]) => [a, b]) };
}
function emptyPaging(): ThreadPaging {
  return { loading: false, loadingOlder: false, error: null, olderError: null,
    beforeCursor: null, hasMoreBefore: null, userMessageOffset: 0,
    forkBoundaryMessageCount: null, truncated: false, version: 0, lineage: 0,
    hasPendingToolCalls: false, completedTurnIds: [], completionIdsProvided: false, activeTurnId: null };
}
function textKey(text: TextSource): string {
  return JSON.stringify([text.turn, text.phase, text.stream,
    text.phase === "answer" && text.stream ? "wire" : text.after]);
}
function sameWire(a: TextSource, b: TextSource): boolean {
  return a.turn === b.turn && a.phase === b.phase && a.stream === b.stream;
}
function coversText(certificate: TextSource, text: TextSource): boolean {
  return certificate.snapshot && certificate.after !== null && sameWire(certificate, text)
    && text.members.every(([first, last]) => first > certificate.after! && last <= certificate.through);
}
function sourcesOverlap(candidate: Unit, retained: Unit): boolean {
  if (Array.from(candidate.sources).some((key) => !key.startsWith("text:") && retained.sources.has(key))) return true;
  return candidate.text.some((left) => retained.text.some((right) => sameWire(left, right)
    && ((left.phase === "answer" && left.stream !== "")
      // Ordered canonical ends identify reset buffers even when attachment missed a prior end.
      || right.members.some(([first, last]) => last > (left.after ?? -1) && first <= (left.end ?? Infinity)))));
}
function unitPosition(unit: Unit | undefined, turn: string): number | null {
  if (!unit) return null;
  const positions = unit.members.get(turn)?.map(([first]) => first) ?? [];
  for (const source of unit.text) if (source.turn === turn) {
    positions.push(...source.members.map(([first]) => first));
  }
  return positions.length ? Math.min(...positions) : null;
}

/** One received projection and accepted history frontier. HTTP replay is scratch only. */
export class ThreadTranscript {
  projection: ThreadProjectionState;
  sideChannelTurnIds = new Set<string>();
  paging = emptyPaging();
  private units = new Set<Unit>();
  private byRow = new Map<string, Unit>();
  private bySource = new Map<string, Unit>();
  private installed: Members = new Map();
  private textCoverage: TextSource[] = [];
  private boundaries = new Map<string, number>();
  private knownTurns = new Set<string>();
  private fragments: WebuiThreadPersistedPayload[] = [];
  private live: LiveContribution[] = [];
  private historyGeneration: string | null = null;
  private pendingFragmentGap: PendingFragmentGap | null = null;
  private lastAdmissionCovered = false;
  private readonly recordLiveContributions: boolean;
  private revision = 0;
  private order = 0;

  constructor(messages: UIMessage[] = [], saved?: ThreadTranscriptSnapshot,
    options: { recordLiveContributions?: boolean } = {}) {
    this.recordLiveContributions = options.recordLiveContributions !== false;
    const checkpoint = saved ? copyThreadCheckpoint(saved) : createThreadCheckpoint(messages);
    this.projection = checkpoint.projection;
    this.sideChannelTurnIds = checkpoint.sideChannelTurnIds;
    if (saved) {
      this.installed = copyMembers(saved.installed);
      this.textCoverage = saved.textCoverage.map(copyText);
      this.boundaries = new Map(saved.boundaries);
      this.knownTurns = new Set(saved.knownTurns);
      this.fragments = [...saved.fragments];
      this.live = this.recordLiveContributions ? [...saved.live] : [];
      this.historyGeneration = saved.historyGeneration;
      this.pendingFragmentGap = saved.pendingFragmentGap ? { ...saved.pendingFragmentGap } : null;
      this.paging = { ...saved.paging, loading: false, loadingOlder: false };
      this.revision = saved.revision;
      for (const unit of saved.units) this.installUnit({ ...unit, rows: new Set(unit.rows),
        sources: new Set(unit.sources), members: copyMembers(unit.members), text: unit.text.map(copyText) });
    } else {
      for (const row of messages) this.registerInput(row, false);
    }
  }

  get messages(): UIMessage[] { return this.projection.messages; }
  get modelRequests() { return this.projection.modelRequests; }
  get hasPendingFragmentGap(): boolean { return this.pendingFragmentGap !== null; }
  get lastAcceptanceCovered(): boolean { return this.lastAdmissionCovered; }

  private installUnit(unit: Unit): void {
    this.order = Math.max(this.order, unit.order + 1);
    this.units.add(unit);
    for (const row of unit.rows) this.byRow.set(row, unit);
    for (const key of unit.sources) this.bySource.set(key, unit);
  }

  rejectTurn(turn: string): void {
    this.live = this.live.filter((entry) => entry.event.turn_id !== turn);
    for (const unit of this.units) if (unit.members.has(turn) || unit.sources.has(`user:${turn}`)) {
      this.units.delete(unit);
      for (const id of unit.rows) this.byRow.delete(id);
      for (const key of unit.sources) this.bySource.delete(key);
    }
    for (const row of this.messages) if (row.role === "user" && row.turnId === turn) this.registerInput(row, false);
  }

  registerInput(row: UIMessage, received = true): void {
    if (row.role === "user" && row.turnId) this.knownTurns.add(row.turnId);
    const identity = row.kind === "compaction" && row.compaction
      ? `compaction:${row.compaction.id}` : row.sessionMessage?.message_id
        ? `input:${row.sessionMessage.message_id}` : row.role === "user" && row.turnId
        ? `user:${row.turnId}` : row.turnId && row.turnSeq !== undefined
          ? `fact:${row.turnId}:${row.turnSeq}` : `replay:${row.id}`;
    if (this.bySource.has(identity)) return;
    const members: Members = new Map();
    if (row.turnId && row.turnSeq !== undefined) members.set(row.turnId, [[row.turnSeq, row.turnSeq]]);
    const revision = received ? ++this.revision : 0;
    this.installUnit({ rows: new Set([row.id]), sources: new Set([identity]), members, text: [],
      introduced: revision, order: this.order++, received: revision });
  }

  private describe(event: ThreadProjectionEvent): { source: string; members: Members; text: TextSource | null } {
    const turn = event.turn_id;
    const seq = event.turn_seq;
    const members: Members = new Map();
    if (turn && seq !== undefined) members.set(turn, [[seq, seq]]);
    for (const receipt of event.projection_receipts ?? []) {
      const ranges = members.get(receipt.turn_id) ?? [];
      for (const [first, last] of receipt.ranges) addRange(ranges, first, last);
      members.set(receipt.turn_id, ranges);
    }
    if (event.event === "context_compaction") {
      return { source: `compaction:${event.compaction_id}`, members, text: null };
    }
    if (event.event === "user_message") {
      return { source: event.provenance?.session_message?.message_id
        ? `input:${event.provenance.session_message.message_id}` : turn ? `user:${turn}` : `replay:${event.projection_id}`,
        members, text: null };
    }
    if (turn && seq !== undefined && (event.event === "delta" || event.event === "stream_end"
      || event.event === "reasoning_delta" || event.event === "reasoning_end")) {
      const phase = event.event.startsWith("reasoning") ? "reasoning" : "answer";
      const stream = event.stream_id ?? "";
      const boundaryKey = JSON.stringify([turn, phase, stream]);
      let after = phase === "answer" && stream ? 0
        : this.boundaries.get(boundaryKey) ?? (this.knownTurns.has(turn) ? 0 : null);
      if (after !== null && after >= seq) {
        after = this.knownTurns.has(turn) ? 0 : null;
        for (const unit of this.units) for (const prior of unit.text) {
          if (prior.turn !== turn || prior.phase !== phase || prior.stream !== stream) continue;
          for (const boundary of [prior.after, prior.end]) {
            if (boundary !== null && boundary < seq) after = Math.max(after ?? 0, boundary);
          }
        }
      }
      const end = event.event === "reasoning_end"
        || (event.event === "stream_end" && !(event.resuming && event.merge_next)) ? seq : null;
      const text: TextSource = { turn, phase, stream, after, through: seq, end,
        snapshot: event.event.endsWith("end") && typeof event.text === "string"
          && (phase === "answer" || event.text.length > 0),
        members: copyMembers(members).get(turn)! };
      return { source: `text:${textKey(text)}`, members, text };
    }
    return { source: turn && seq !== undefined ? `fact:${turn}:${seq}` : `replay:${event.projection_id}`,
      members, text: null };
  }

  represented(event: ThreadProjectionEvent): boolean {
    if (event.turn_id && event.turn_seq !== undefined && contains(this.installed.get(event.turn_id), event.turn_seq)) return true;
    const { text } = this.describe(event);
    return text !== null && this.textCoverage.some((certificate) => coversText(certificate, text));
  }

  project(event: ThreadProjectionEvent, options: {
    createId: () => string; now: number; persisted?: boolean; sideChannel?: boolean; startSeq?: number;
    contributions?: ThreadProjectionEvent[]; sourceRevision?: number;
  }): UIMessage[] {
    if (!options.persisted && event.event === "user_message" && !event.provenance?.session_message) {
      event = { turn_seq: 0, ...event };
    }
    // Telemetry never contributes body sources, memberships, or admission barriers.
    if (event.event === "model_request") {
      this.projection = projectThreadEvent(this.projection, event, options);
      return this.messages;
    }
    const updatesInputMedia = event.event === "user_message" && !event.provenance?.session_message
      && !!event.turn_id && !!event.media_urls?.length
      && this.messages.some((message) => message.role === "user" && message.turnId === event.turn_id);
    if (!options.persisted && !updatesInputMedia && this.represented(event)) return this.messages;
    if (!event.projection_id && (!event.turn_id || event.turn_seq === undefined)) {
      event = { ...event, projection_id: options.createId() };
    }
    const { source, members, text } = this.describe(event);
    const effects: ThreadProjectionEffects = { bodyWrites: new Set(), consumed: new Set() };
    let projection = this.projection;
    const historical = !options.persisted && event.event !== "turn_end" && event.event !== "user_message"
      && event.turn_id && event.turn_seq !== undefined
      && ((this.installed.get(event.turn_id)?.at(-1)?.[1] ?? -1) > event.turn_seq
        || this.textCoverage.some((item) => item.turn === event.turn_id && item.through > event.turn_seq!));
    if (historical) {
      // Replay only the identified historical destination; keep foreground pointers intact.
      const callIds = new Set(event.event === "file_edit"
        ? event.edits.flatMap((edit) => edit.call_id ? [edit.call_id] : [])
        : event.event === "message" ? event.tool_events?.flatMap((tool) => tool.call_id ? [tool.call_id] : []) : []);
      const destinations = new Set<Unit>();
      const existing = this.bySource.get(source);
      if (existing) destinations.add(existing);
      if (callIds.size) for (const row of projection.messages) {
        if (row.turnId !== event.turn_id) continue;
        if (row.fileEdits?.some((edit) => edit.call_id && callIds.has(edit.call_id))
          || row.toolEvents?.some((tool) => tool.call_id && callIds.has(tool.call_id))) {
          destinations.add(this.byRow.get(row.id)!);
        }
      }
      const targets = projection.messages.filter((row) => destinations.has(this.byRow.get(row.id)!));
      const scratchState = { ...copyThreadCheckpoint(this, targets).projection,
        activeAssistantId: null, mergeReasoning: false, activitySegmentId: null, fileEditSegmentId: null };
      const scratch = projectThreadEvent(scratchState, event, { ...options, effects });
      const updates = new Map(scratch.messages.map((row) => [row.id, row]));
      const targetIds = new Set(targets.map((row) => row.id));
      const additions = scratch.messages.filter((row) => !targetIds.has(row.id)).map((row) => ({ ...row,
        ...(row.activitySegmentId ? { activitySegmentId: `history:${event.turn_id}:${event.turn_seq}` } : {}) }));
      const messages = projection.messages.flatMap((row) => targetIds.has(row.id)
        ? updates.has(row.id) ? [updates.get(row.id)!] : [] : [row]);
      const index = messages.findIndex((row) => {
        const position = unitPosition(this.byRow.get(row.id), event.turn_id!);
        return position !== null && position > event.turn_seq!;
      });
      let lastInTurn = messages.length - 1;
      while (lastInTurn >= 0 && unitPosition(this.byRow.get(messages[lastInTurn].id), event.turn_id!) === null) lastInTurn--;
      if (index < 0 && lastInTurn < 0) {
        this.paging = { ...this.paging, error: "Could not place earlier transcript event" };
        return this.messages;
      }
      const before = index < 0 ? lastInTurn + 1 : index;
      projection = { ...projection, messages: [...messages.slice(0, before), ...additions, ...messages.slice(before)],
        closedAssistantIds: scratch.closedAssistantIds, closedAnswerStreamIds: scratch.closedAnswerStreamIds,
        closedTurnIds: scratch.closedTurnIds };
    } else {
      projection = projectThreadEvent(projection, event, { ...options, effects });
    }
    if (event.event === "user_message" && projection.messages === this.messages) return this.messages;
    this.projection = projection;
    const connected = new Set<Unit>();
    const existing = this.bySource.get(source);
    if (existing) connected.add(existing);
    for (const id of [...effects.bodyWrites, ...effects.consumed]) {
      const unit = this.byRow.get(id);
      if (unit) connected.add(unit);
    }
    const revision = options.persisted ? 0 : options.sourceRevision ?? ++this.revision;
    this.revision = Math.max(this.revision, revision);
    const unit: Unit = { rows: new Set(), sources: new Set([source]), members,
      text: text ? [text] : [], introduced: revision, order: this.order++, received: revision };
    for (const previous of connected) {
      this.units.delete(previous);
      for (const id of previous.rows) if (!effects.consumed.has(id)) unit.rows.add(id);
      for (const key of previous.sources) unit.sources.add(key);
      mergeMembers(unit.members, previous.members);
      for (const prior of previous.text) {
        const matching = unit.text.find((item) => textKey(item) === textKey(prior));
        if (matching) {
          if (prior.end !== null) matching.end = Math.max(matching.end ?? 0, prior.end);
          for (const [first, last] of prior.members) addRange(matching.members, first, last);
          if (prior.snapshot) {
            matching.through = matching.snapshot ? Math.max(matching.through, prior.through) : prior.through;
            matching.snapshot = true;
          } else if (!matching.snapshot) matching.through = Math.max(matching.through, prior.through);
        } else unit.text.push(copyText(prior));
      }
      unit.introduced = Math.min(unit.introduced, previous.introduced);
      unit.order = Math.min(unit.order, previous.order);
      unit.received = Math.max(unit.received, previous.received);
    }
    for (const id of effects.consumed) this.byRow.delete(id);
    for (const id of effects.bodyWrites) {
      if (!effects.consumed.has(id) || projection.messages.some((row) => row.id === id)) unit.rows.add(id);
    }
    this.installUnit(unit);
    if (event.event === "user_message" && event.turn_id) this.knownTurns.add(event.turn_id);
    if (text?.end !== null && text?.end !== undefined) {
      const key = JSON.stringify([text.turn, text.phase, text.stream]);
      this.boundaries.set(key, Math.max(text.end, this.boundaries.get(key) ?? 0));
    }
    if (!options.persisted && this.recordLiveContributions) for (const contribution of options.contributions ?? [event]) {
      this.live.push({ event: contribution, now: options.now, revision,
        startSeq: contribution.turn_seq ?? options.startSeq, sideChannel: options.sideChannel });
    }
    return this.messages;
  }

  begin(kind: ThreadRead["kind"]): ThreadRead {
    this.paging = { ...this.paging,
      [kind === "older" ? "loadingOlder" : "loading"]: kind === "older" || this.paging.version === 0,
      [kind === "older" ? "olderError" : "error"]: null };
    return { kind, revision: this.revision, lineage: this.paging.lineage,
      before: this.paging.beforeCursor, empty: this.messages.length === 0 };
  }

  private unitCovered(unit: Unit, candidate: ThreadTranscript): boolean {
    if (unit.text.length === 0 && Array.from(unit.sources).every((source) => candidate.bySource.has(source))) return true;
    if (unit.members.size === 0) return false;
    const represented = copyMembers(candidate.installed);
    for (const text of unit.text) {
      if (Array.from(candidate.units).some((other) => other.text.some((certificate) => coversText(certificate, text)))) {
        mergeMembers(represented, new Map([[text.turn, text.members]]));
      }
    }
    return Array.from(unit.members).every(([turn, ranges]) => ranges.every(([first, last]) =>
      represented.get(turn)?.some(([a, b]) => a <= first && b >= last)));

  }

  accept(body: WebuiThreadPersistedPayload | null, read: ThreadRead): boolean {
    this.lastAdmissionCovered = false;
    if (read.kind === "older" && (read.lineage !== this.paging.lineage || read.before !== this.paging.beforeCursor)) return false;
    // An initial network read may have started just before its cached seed was installed.
    if (read.kind !== "older" && read.lineage !== this.paging.lineage
      && !(read.kind === "initial" && read.lineage === 0 && this.paging.lineage === 1)) return false;
    if (read.kind === "older" && !body?.page) {
      this.finishRead(read, "Earlier history did not include a page cursor");
      return false;
    }
    const generation = body?.page?.history_generation ?? null;
    const replacedHistory = generation !== null && this.historyGeneration !== null
      && generation !== this.historyGeneration;
    if (replacedHistory && (read.kind === "older" || this.live.length > 0 || this.revision > read.revision)) {
      this.finishRead(read, "History changed during loading");
      return false;
    }
    const incoming = body?.page?.record_range;
    const pending = this.pendingFragmentGap;
    if (pending && (!incoming || incoming.turn !== pending.turn
      || (read.kind === "older" && incoming.end !== pending.front))) {
      this.finishRead(read, "Could not bridge the missing history records");
      return false;
    }
    const prior = incoming && !replacedHistory ? this.fragments.filter((page) =>
      (page.page?.history_generation ?? null) === generation && page.page?.record_range?.turn === incoming.turn) : [];
    const priorEnd = prior.length ? Math.max(...prior.map((page) => page.page!.record_range!.end)) : null;
    if (read.kind !== "older" && incoming && priorEnd !== null && incoming.end < priorEnd) {
      this.finishRead(read, "History changed during loading");
      return false;
    }
    const joined = incoming && body ? joinThreadFragments(replacedHistory ? [] : this.fragments, body) : null;
    if (joined) body = joined.body;
    const groupRange = joined?.body.page?.record_range;
    const gap = pending ?? (read.kind !== "older" && incoming && priorEnd !== null && incoming.start > priorEnd
      ? { turn: incoming.turn, oldEnd: priorEnd, front: incoming.start } : null);
    const hasGap = !!gap && !!groupRange && groupRange.start > gap.oldEnd;
    const candidate = new ThreadTranscript();
    let durableMembers: Members | null = null;
    const durableText = new Map<string, TextSource>();
    if (joined && body) {
      const canonical = new ThreadTranscript();
      for (const [index, event] of body.events.entries()) canonical.project(event,
        { createId: () => `canonical-${index}`, now: 0, persisted: true });
      for (const unit of canonical.units) {
        mergeMembers(canonical.installed, unit.members);
        for (const text of unit.text) if (text.snapshot && text.after !== null) {
          const previous = durableText.get(textKey(text));
          if (!previous || text.through > previous.through) durableText.set(textKey(text), copyText(text));
        }
      }
      canonical.textCoverage = Array.from(durableText.values());
      durableMembers = copyMembers(canonical.installed);
      const turns = new Set(body.events.map((event) => event.turn_id).filter((turn): turn is string => !!turn));
      const replay: Array<{ event: ThreadProjectionEvent; live?: LiveContribution }> = body.events.map((event) => ({ event }));
      for (const entry of this.live) {
        const { event } = entry;
        if (!event.turn_id || event.turn_seq === undefined || !turns.has(event.turn_id) || canonical.represented(event)) continue;
        let position = replay.findIndex((item) => item.event.turn_id === event.turn_id
          && item.event.turn_seq !== undefined && item.event.turn_seq > event.turn_seq!);
        if (position < 0) {
          position = replay.length;
          for (let index = replay.length - 1; index >= 0; index--) if (replay[index].event.turn_id === event.turn_id) {
            position = index + 1;
            break;
          }
        }
        replay.splice(position, 0, { event, live: entry });
      }
      for (const [index, item] of replay.entries()) candidate.project(item.event, item.live
        ? { createId: () => `live-${item.live!.revision}-${index}`, now: item.live.now,
            startSeq: item.live.startSeq, sideChannel: item.live.sideChannel, sourceRevision: item.live.revision }
        : { createId: () => `history-${index}`, now: 0, persisted: true });
    } else {
      for (const [index, event] of (body?.events ?? []).entries()) candidate.project(event,
        { createId: () => `history-${index}`, now: 0, persisted: true });
    }
    for (const unit of candidate.units) {
      mergeMembers(candidate.installed, unit.members);
      if (!joined) for (const text of unit.text) if (text.snapshot && text.after !== null) {
        const previous = durableText.get(textKey(text));
        if (!previous || text.through > previous.through) durableText.set(textKey(text), copyText(text));
      }
    }

    // Stream deltas are normally persisted as one end snapshot. Match the
    // whole observed segment, not just a sequence range or a text substring.
    const exactSnapshots = new Map<ThreadProjectionEvent, { turn: string; seq: number }>();
    const anchoredTurns = new Set<string>();
    for (const snapshot of body?.events ?? []) {
      if (snapshot.event === "user_message" && snapshot.starts_turn && snapshot.turn_id) anchoredTurns.add(snapshot.turn_id);
      if ((snapshot.event !== "stream_end" && snapshot.event !== "reasoning_end")
        || !snapshot.turn_id || snapshot.turn_seq === undefined || !snapshot.text
        || (joined ? groupRange?.start !== 0 : body?.page?.truncated_oversized_turn || !anchoredTurns.has(snapshot.turn_id))) continue;
      const phase = snapshot.event === "stream_end" ? "answer" : "reasoning";
      const certificate = Array.from(durableText.values()).find((text) => text.turn === snapshot.turn_id
        && text.phase === phase && text.stream === (snapshot.stream_id ?? "")
        && text.after !== null && text.through === snapshot.turn_seq);
      if (!certificate || certificate.after === null) continue;
      const entries = this.live.filter(({ event, sideChannel }) => !sideChannel && event.turn_id === snapshot.turn_id
        && event.turn_seq !== undefined && event.turn_seq > certificate.after! && event.turn_seq < snapshot.turn_seq!
        && !event.projection_receipts && ((phase === "answer" && event.event === "delta")
          || (phase === "reasoning" && event.event === "reasoning_delta"))
        && event.stream_id === snapshot.stream_id).sort((a, b) => a.event.turn_seq! - b.event.turn_seq!);
      if (!entries.length || new Set(entries.map(({ event }) => event.turn_seq)).size !== entries.length) continue;
      const observed = entries.map(({ event }) => event.event === "delta" || event.event === "reasoning_delta" ? event.text : "").join("");
      let first = entries[0].event.turn_seq!;
      if (observed !== snapshot.text) {
        if (snapshot.event !== "stream_end") continue;
        let previous: Extract<ThreadProjectionEvent, { event: "stream_end" }> | undefined;
        for (const event of body?.events ?? []) if (event.event === "stream_end" && event.turn_id === snapshot.turn_id
          && event.stream_id === snapshot.stream_id && event.turn_seq !== undefined && event.turn_seq < snapshot.turn_seq) previous = event;
        if (!previous?.text || previous.resuming !== true || previous.merge_next !== true || previous.turn_seq === undefined
          || !contains(this.installed.get(snapshot.turn_id), previous.turn_seq) || first <= previous.turn_seq
          || previous.text + observed !== snapshot.text) continue;
        first = previous.turn_seq + 1;
      }
      const intervenes = (event: ThreadProjectionEvent) => event.turn_id === snapshot.turn_id
        && event.turn_seq !== undefined && event.turn_seq >= first && event.turn_seq < snapshot.turn_seq!
        && event.event !== "model_request";
      if (this.live.some(({ event }) => intervenes(event) && !entries.some((entry) => entry.event === event))
        || (body?.events ?? []).some(intervenes)) continue;
      if (snapshot.event === "stream_end" && entries.some(({ event }) => event.event === "delta"
        && (JSON.stringify(event.source ?? null) !== JSON.stringify(snapshot.source ?? null)
          || JSON.stringify(event.response_sources ?? null) !== JSON.stringify(snapshot.response_sources ?? null)))) continue;
      for (const { event } of entries) exactSnapshots.set(event, { turn: snapshot.turn_id, seq: snapshot.turn_seq });
    }

    // A disjoint window can replace the old durable projection only if every
    // received contribution is exactly represented or replayable as a contiguous suffix.
    let rebase = hasGap && !pending;
    if (rebase) {
      const covered = copyMembers(this.installed);
      const ends = new Map<string, number>();
      for (const event of body?.events ?? []) if (event.turn_id) {
        if (event.turn_seq === undefined) { rebase = false; break; }
        ends.set(event.turn_id, Math.max(ends.get(event.turn_id) ?? -1, event.turn_seq));
      }
      const orderedLive = [...this.live].sort((a, b) => (a.event.turn_seq ?? -1) - (b.event.turn_seq ?? -1));
      for (const entry of orderedLive) {
        const { event } = entry;
        if (!event.turn_id || event.turn_seq === undefined) { rebase = false; break; }
        const ranges = covered.get(event.turn_id) ?? [];
        addRange(ranges, event.turn_seq);
        covered.set(event.turn_id, ranges);
        if (contains(durableMembers?.get(event.turn_id), event.turn_seq)) continue;
        const end = ends.get(event.turn_id);
        if (end === undefined || event.turn_seq !== end + 1
          || !candidate.live.some((item) => item.event === event && item.revision === entry.revision)) {
          rebase = false;
          break;
        }
        ends.set(event.turn_id, event.turn_seq);
      }
      if (rebase) for (const unit of this.units) if (unit.received > 0 && !this.unitCovered(unit, candidate)) {
        if (!unit.members.size || Array.from(unit.members).some(([turn, ranges]) => ranges.some(([first, last]) =>
          !covered.get(turn)?.some(([a, b]) => a <= first && b >= last)))) {
          rebase = false;
          break;
        }
      }
    }
    if (hasGap && !rebase && joined && groupRange && gap) {
      const page = body?.page;
      if (!page?.has_more_before || !page.before_cursor
        || (read.kind === "older" && page.before_cursor === read.before)) {
        this.finishRead(read, "Could not bridge the missing history records");
        return false;
      }
      this.fragments = joined.pages;
      this.pendingFragmentGap = { ...gap, front: groupRange.start };
      if (generation !== null) this.historyGeneration = generation;
      this.paging = { ...this.paging, loading: false, loadingOlder: false,
        error: "Newer history is waiting for missing earlier records", olderError: null,
        beforeCursor: page.before_cursor, hasMoreBefore: true, truncated: true,
        version: this.paging.version + (read.kind === "older" ? 0 : 1),
        lineage: this.paging.lineage + (read.kind === "older" ? 0 : 1) };
      return true;
    }
    const overlaps = new Set(Array.from(this.units).filter((old) =>
      Array.from(candidate.units).some((unit) => sourcesOverlap(unit, old))));
    const firstOverlap = this.messages.findIndex((row) => overlaps.has(this.byRow.get(row.id)!));
    const windowRows = new Set(this.messages.slice(Math.max(0, firstOverlap)).map((row) => row.id));
    const received = replacedHistory ? [] : Array.from(this.units).filter((unit) => unit.received > 0
      && Array.from(unit.rows).some((id) => windowRows.has(id)));
    const canonical = body ? persistedCanonicalRunState(body) : null;
    const completed = new Set(canonical?.completedTurnIds);
    const protectedUnits = rebase ? [] : received.filter((unit) => {
      const covered = this.unitCovered(unit, candidate);
      const replayed = !!joined && candidate.live.some(({ event }) => !!event.turn_id && event.turn_seq !== undefined
        && contains(unit.members.get(event.turn_id), event.turn_seq)
        && Array.from(candidate.units).some((next) => sourcesOverlap(next, unit)
          && contains(next.members.get(event.turn_id!), event.turn_seq!)));
      const snapshotReplayed = this.live.some(({ event }) => {
        const snapshot = exactSnapshots.get(event);
        return !!snapshot && event.turn_id !== undefined && event.turn_seq !== undefined
          && contains(unit.members.get(event.turn_id), event.turn_seq)
          && Array.from(candidate.units).some((next) => sourcesOverlap(next, unit)
            && contains(next.members.get(snapshot.turn), snapshot.seq));
      });
      const omittedLive = !!joined && this.live.some(({ event, revision }) => event.turn_id
        && event.turn_seq !== undefined && contains(unit.members.get(event.turn_id), event.turn_seq)
        && !contains(durableMembers?.get(event.turn_id), event.turn_seq) && !exactSnapshots.has(event)
        && !candidate.live.some((item) => item.event === event && item.revision === revision));
      // Replaying is not proof of survival: a later end can overwrite a
      // cumulative buffer, and a final message can consume an active answer.
      const overwrittenLive = !!joined && candidate.live.some(({ event }) => {
        if ((event.event !== "delta" && event.event !== "reasoning_delta") || !event.turn_id
          || event.turn_seq === undefined || !contains(unit.members.get(event.turn_id), event.turn_seq)
          || exactSnapshots.has(event)) return false;
        return (body?.events ?? []).some((end) => {
          if (end.turn_id !== event.turn_id || end.turn_seq === undefined || end.turn_seq <= event.turn_seq!) return false;
          if (event.event === "delta" && end.event === "message" && end.kind === undefined) return true;
          return (end.event === "stream_end" || end.event === "reasoning_end")
            && (end.stream_id ?? "") === (event.stream_id ?? "")
            && ((event.event === "delta" && end.event === "stream_end" && typeof end.text === "string")
              || (event.event === "reasoning_delta" && end.event === "reasoning_end" && !!end.text));
        });
      });
      return omittedLive || overwrittenLive || !covered || (unit.text.length > 0 && !replayed && !snapshotReplayed && (body?.page?.truncated_oversized_turn
        || unit.text.some((text) => !completed.has(text.turn))));
    });
    const newTail = read.empty && protectedUnits.length > 0
      && protectedUnits.every((unit) => unit.received > read.revision);
    const appendedInputs = this.messages.filter((row) => row.role === "user" && row.turnId
      && this.byRow.get(row.id)!.introduced > read.revision);
    const appendedTurns = new Set(appendedInputs.map((row) => row.turnId!));
    const appendedInputUnits = new Set(appendedInputs.map((row) => this.byRow.get(row.id)!));
    const reset = replacedHistory || rebase || (read.kind === "latest" && overlaps.size === 0
      && !body?.page?.truncated_oversized_turn
      && protectedUnits.every((unit) => unit.introduced > read.revision
        && (appendedInputUnits.has(unit) || (unit.members.size > 0
          && Array.from(unit.members.keys()).every((turn) => appendedTurns.has(turn))))));
    if (read.kind !== "older" && this.messages.length > 0 && overlaps.size === 0 && !newTail && !reset) {
      this.finishRead(read);
      return false;
    }
    const held = new Set<Unit>();
    for (const unit of candidate.units) {
      if (protectedUnits.some((old) => sourcesOverlap(unit, old))) held.add(unit);
      for (const old of protectedUnits) for (const turn of old.members.keys()) {
        const at = unitPosition(unit, turn);
        const start = unitPosition(old, turn);
        if (at !== null && start !== null && at >= start) held.add(unit);
      }
    }
    const rows = candidate.messages;
    let cut = rows.findIndex((row) => held.has(candidate.byRow.get(row.id)!));
    if (cut < 0) cut = rows.length;
    // A whole source can straddle several rows: never install only part of it.
    for (let changed = true; changed;) {
      changed = false;
      for (let index = 0; index < cut; index++) {
        const unit = candidate.byRow.get(rows[index].id)!;
        if (rows.slice(cut).some((row) => unit.rows.has(row.id))) { cut = index; changed = true; break; }
      }
    }
    const admittedRows = rows.slice(0, cut);
    const admitted = new Set(admittedRows.map((row) => candidate.byRow.get(row.id)!));
    const cutOrder = cut < rows.length ? candidate.byRow.get(rows[cut].id)!.order : Infinity;
    for (const unit of candidate.units) {
      if (unit.rows.size === 0 && unit.order < cutOrder && !held.has(unit)) admitted.add(unit);
    }
    if (read.kind === "older" && Array.from(candidate.units).some((unit) => {
      if (admitted.has(unit)) return false;
      const matching = Array.from(this.units).filter((old) => sourcesOverlap(unit, old));
      if (!matching.length) return true;
      if (!joined) return false;
      const existing: Members = new Map();
      for (const old of matching) mergeMembers(existing, old.members);
      return Array.from(unit.members).some(([turn, ranges]) => ranges.some(([first, last]) =>
        !existing.get(turn)?.some(([a, b]) => a <= first && b >= last)));
    })) {
      this.finishRead(read, "Could not place earlier history");
      return false;
    }
    if (read.kind === "older" && body?.page?.has_more_before === true
      && (!body.page.before_cursor || body.page.before_cursor === read.before)) {
      this.finishRead(read, "Earlier history cursor did not advance");
      return false;
    }
    const fullyAdopt = protectedUnits.length === 0 && cut === rows.length
      && !body?.page?.truncated_oversized_turn
      && (this.messages.length === 0 || reset || overlaps.size > 0);
    const replaced = new Set<Unit>();
    for (const old of this.units) if ((reset && !protectedUnits.includes(old)) || Array.from(admitted)
      .some((unit) => sourcesOverlap(unit, old) && (old.received === 0 || this.unitCovered(old, candidate)))) replaced.add(old);
    const previousCount = this.messages.length;
    const firstReplaced = this.messages.findIndex((row) => replaced.has(this.byRow.get(row.id)!));
    const prefix = read.kind !== "older" && !reset && firstReplaced > 0
      ? this.messages.slice(0, firstReplaced) : [];
    const keepSuffix = !fullyAdopt || read.kind === "older";
    const anchors = new Map<Unit, number>();
    if (keepSuffix) for (const [index, row] of this.messages.entries()) {
      const old = this.byRow.get(row.id)!;
      if (!replaced.has(old)) continue;
      for (const unit of admitted) {
        if (!anchors.has(unit) && sourcesOverlap(unit, old)) anchors.set(unit, index);
      }
    }
    const segments = new Map<string, string>();
    const mappedRows = admittedRows.map((row) => {
      if (!row.activitySegmentId) return row;
      let segment = segments.get(row.activitySegmentId);
      if (!segment) {
        segment = `history:${Array.from(candidate.byRow.get(row.id)!.sources)[0]}`;
        segments.set(row.activitySegmentId, segment);
      }
      return { ...row, activitySegmentId: segment };
    });
    const nextMessages = [...prefix];
    let previous = prefix.length;
    for (const row of mappedRows) {
      const anchor = anchors.get(candidate.byRow.get(row.id)!);
      while (anchor !== undefined && previous < anchor) {
        const retained = this.messages[previous++];
        if (!replaced.has(this.byRow.get(retained.id)!)) nextMessages.push(retained);
      }
      nextMessages.push(row);
    }
    if (keepSuffix) nextMessages.push(...this.messages.slice(previous)
      .filter((row) => !replaced.has(this.byRow.get(row.id)!)));
    const modelRequests = new Map(this.modelRequests);
    for (const [turn, snapshot] of candidate.modelRequests) {
      modelRequests.set(turn, reconcileModelRequest(modelRequests.get(turn), snapshot));
    }
    const oldActive = this.projection.activeAssistantId;
    const activeReplaced = !!joined && !!oldActive && replaced.has(this.byRow.get(oldActive)!);
    const adoptProjection = (fullyAdopt || replacedHistory) && read.kind !== "older";
    this.projection = adoptProjection
      ? { ...candidate.projection, messages: nextMessages, modelRequests,
          activitySegmentId: candidate.projection.activitySegmentId
            ? segments.get(candidate.projection.activitySegmentId) ?? null : null,
          fileEditSegmentId: candidate.projection.fileEditSegmentId
            ? segments.get(candidate.projection.fileEditSegmentId) ?? null : null,
          closedTurnIds: new Set([...(replacedHistory ? [] : this.projection.closedTurnIds), ...candidate.projection.closedTurnIds]),
          closedAnswerStreamIds: new Set([...(replacedHistory ? [] : this.projection.closedAnswerStreamIds), ...candidate.projection.closedAnswerStreamIds]) }
      : { ...this.projection, messages: nextMessages, modelRequests,
          ...(activeReplaced ? {
            activeAssistantId: candidate.projection.activeAssistantId,
            mergeReasoning: candidate.projection.mergeReasoning,
            activitySegmentId: candidate.projection.activitySegmentId
              ? segments.get(candidate.projection.activitySegmentId) ?? null : null,
            fileEditSegmentId: candidate.projection.fileEditSegmentId
              ? segments.get(candidate.projection.fileEditSegmentId) ?? null : null,
          } : {}) };
    if (fullyAdopt && read.kind !== "older") {
      const retained = new Set(prefix.map((row) => row.id));
      for (const unit of this.units) if (!Array.from(unit.rows).some((id) => retained.has(id))) replaced.add(unit);
    }
    for (const unit of replaced) {
      this.units.delete(unit);
      for (const id of unit.rows) this.byRow.delete(id);
      for (const key of unit.sources) this.bySource.delete(key);
    }
    for (const unit of admitted) this.installUnit(unit);
    const retainedMembers: Members = new Map();
    for (const unit of this.units) mergeMembers(retainedMembers, unit.members);
    const installed: Members = new Map();
    for (const [turn, ranges] of this.installed) {
      const kept: Ranges = [];
      for (const [first, last] of ranges) for (const [a, b] of retainedMembers.get(turn) ?? []) {
        if (first <= b && a <= last) addRange(kept, Math.max(first, a), Math.min(last, b));
      }
      if (kept.length) installed.set(turn, kept);
    }
    const certificates = new Map(this.textCoverage
      .filter((text) => this.bySource.has(`text:${textKey(text)}`))
      .map((text) => [textKey(text), text]));
    for (const unit of admitted) {
      if (durableMembers) mergeCoveredMembers(installed, unit.members, durableMembers);
      else mergeMembers(installed, unit.members);
      for (const text of unit.text) {
        const evidence = durableMembers ? durableText.get(textKey(text)) : text;
        if (!evidence?.snapshot || evidence.after === null) continue;
        const previous = certificates.get(textKey(evidence));
        if (!previous || evidence.through > previous.through) certificates.set(textKey(evidence), copyText(evidence));
      }
    }
    this.installed = installed;
    this.textCoverage = Array.from(certificates.values());
    this.live = this.live.filter(({ event }) => {
      if (event.turn_id && event.turn_seq !== undefined && contains(this.installed.get(event.turn_id), event.turn_seq)) return false;
      const snapshot = exactSnapshots.get(event);
      return !snapshot || !contains(this.installed.get(snapshot.turn), snapshot.seq);
    });
    if (adoptProjection) {
      this.boundaries = new Map(candidate.boundaries);
      this.knownTurns = new Set(candidate.knownTurns);
    }
    for (const row of nextMessages) if (row.role === "user" && row.turnId) this.knownTurns.add(row.turnId);
    for (const unit of admitted) for (const text of unit.text) {
      const key = JSON.stringify([text.turn, text.phase, text.stream]);
      const end = candidate.boundaries.get(key);
      if (end !== undefined && contains(unit.members.get(text.turn), end)) {
        this.boundaries.set(key, Math.max(end, this.boundaries.get(key) ?? 0));
      }
    }
    for (const event of body?.events ?? []) {
      if (event.event === "turn_end" && event.turn_id && event.turn_seq !== undefined
        && contains(this.installed.get(event.turn_id), event.turn_seq)) this.projection.closedTurnIds.add(event.turn_id);
    }
    for (const id of candidate.projection.closedAssistantIds) {
      if (admittedRows.some((row) => row.id === id)) this.projection.closedAssistantIds.add(id);
    }
    const admittedStreams = new Set(admittedRows.filter((row) => row.streamId)
      .map((row) => JSON.stringify([row.turnId ?? "", row.streamId])));
    for (const unit of admitted) for (const text of unit.text) {
      if (text.phase === "answer" && text.stream && text.end !== null) {
        admittedStreams.add(JSON.stringify([text.turn, text.stream]));
      }
    }
    for (const key of candidate.projection.closedAnswerStreamIds) {
      if (admittedStreams.has(key)) this.projection.closedAnswerStreamIds.add(key);
    }
    const retainedStreams = new Set(nextMessages.filter((row) => row.streamId)
      .map((row) => JSON.stringify([row.turnId ?? "", row.streamId])));
    for (const unit of this.units) for (const text of unit.text) {
      if (text.phase === "answer" && text.stream && text.end !== null) {
        retainedStreams.add(JSON.stringify([text.turn, text.stream]));
      }
    }
    this.projection.closedAnswerStreamIds = new Set(Array.from(this.projection.closedAnswerStreamIds)
      .filter((key) => retainedStreams.has(key)));
    const retainedTurns = new Set(Array.from(this.units).flatMap((unit) => Array.from(unit.members.keys())));
    for (const row of nextMessages) if (row.turnId) retainedTurns.add(row.turnId);
    for (const [turn, snapshot] of modelRequests) {
      if (reset && snapshot.ended && !retainedTurns.has(turn) && !candidate.modelRequests.has(turn)) {
        modelRequests.delete(turn);
      } else retainedTurns.add(turn);
    }
    const retainedRows = new Set(nextMessages.map((row) => row.id));
    const retainedBoundaries = new Set(Array.from(this.units).flatMap((unit) => unit.text
      .map((text) => JSON.stringify([text.turn, text.phase, text.stream]))));
    this.knownTurns = new Set(Array.from(this.knownTurns).filter((turn) => retainedTurns.has(turn)));
    this.boundaries = new Map(Array.from(this.boundaries).filter(([key]) => retainedBoundaries.has(key)));
    this.sideChannelTurnIds = new Set(Array.from(this.sideChannelTurnIds).filter((turn) => retainedTurns.has(turn)));
    this.projection.closedTurnIds = new Set(Array.from(this.projection.closedTurnIds).filter((turn) => retainedTurns.has(turn)));
    this.projection.closedAssistantIds = new Set(Array.from(this.projection.closedAssistantIds).filter((id) => retainedRows.has(id)));
    this.projection.turnAliases = new Map(Array.from(this.projection.turnAliases).filter(([turn, alias]) =>
      retainedTurns.has(turn) && retainedTurns.has(alias)));
    const page = body?.page;
    const preserveFrontier = read.kind !== "older" && prefix.length > 0;
    const boundary = body?.fork_boundary_event_index;
    const forkRows = boundary === undefined ? null : new ThreadTranscript();
    if (forkRows && boundary !== undefined) for (const [index, event] of (body?.events ?? []).slice(0, boundary).entries()) {
      forkRows.project(event, { createId: () => `boundary-${index}`, now: 0, persisted: true });
    }
    if (reset) this.fragments = [];
    if (joined) this.fragments = joined.pages;
    if (pending && !hasGap) this.pendingFragmentGap = null;
    if (generation !== null) this.historyGeneration = generation;
    this.paging = { ...this.paging, loading: false, loadingOlder: false, error: null,
      olderError: read.kind !== "older" && !reset
        && (preserveFrontier || this.paging.beforeCursor === page?.before_cursor) ? this.paging.olderError : null,
      beforeCursor: preserveFrontier ? this.paging.beforeCursor : page?.before_cursor ?? null,
      hasMoreBefore: preserveFrontier ? this.paging.hasMoreBefore : page?.has_more_before === true,
      userMessageOffset: preserveFrontier ? this.paging.userMessageOffset : Math.max(0, page?.user_message_offset ?? 0),
      forkBoundaryMessageCount: forkRows ? prefix.length + forkRows.messages.length
        : read.kind === "older" && this.paging.forkBoundaryMessageCount !== null
          ? this.paging.forkBoundaryMessageCount + nextMessages.length - previousCount
          : this.paging.forkBoundaryMessageCount,
      truncated: page?.truncated_oversized_turn === true,
      version: this.paging.version + (read.kind === "older" ? 0 : 1),
      lineage: this.paging.lineage + (reset || this.paging.lineage === 0 ? 1 : 0),
      ...(read.kind === "older" ? {} : {
        hasPendingToolCalls: body?.has_pending_tool_calls ?? hasPendingAgentActivity(nextMessages),
        completedTurnIds: canonical?.completedTurnIds ?? [],
        completionIdsProvided: Array.isArray(body?.completed_turn_ids),
        activeTurnId: body?.active_turn_id ?? null,
      }),
    };
    this.lastAdmissionCovered = admitted.size === candidate.units.size;
    return true;
  }

  finishRead(read: ThreadRead, error: string | null = null): void {
    this.paging = { ...this.paging, [read.kind === "older" ? "loadingOlder" : "loading"]: false,
      [read.kind === "older" ? "olderError" : "error"]: error };
  }

  expandDetail(ref: string, events: ThreadProjectionEvent[]): void {
    const target = this.messages.find((row) => row.traceDetail?.ref === ref);
    if (!target) return;
    const scratch = new ThreadTranscript();
    events.forEach((event, index) => scratch.project(event,
      { createId: () => `detail:${ref}:${index}`, now: 0, persisted: true }));
    const unit = this.byRow.get(target.id)!;
    unit.rows.delete(target.id);
    this.byRow.delete(target.id);
    const replacements = scratch.messages.map((row) => ({ ...row, activitySegmentId: target.activitySegmentId }));
    for (const row of replacements) { unit.rows.add(row.id); this.byRow.set(row.id, unit); }
    this.projection = { ...this.projection, messages: this.messages.flatMap((row) => row === target ? replacements : [row]) };
  }

  save(): ThreadTranscriptSnapshot {
    return { ...copyThreadCheckpoint(this),
      units: Array.from(this.units, (unit) => ({ ...unit, rows: new Set(unit.rows), sources: new Set(unit.sources),
        members: copyMembers(unit.members), text: unit.text.map(copyText) })),
      installed: copyMembers(this.installed), textCoverage: this.textCoverage.map(copyText),
      boundaries: new Map(this.boundaries), knownTurns: new Set(this.knownTurns),
      paging: { ...this.paging }, revision: this.revision, fragments: [...this.fragments], live: [...this.live],
      historyGeneration: this.historyGeneration,
      pendingFragmentGap: this.pendingFragmentGap ? { ...this.pendingFragmentGap } : null };
  }
}
