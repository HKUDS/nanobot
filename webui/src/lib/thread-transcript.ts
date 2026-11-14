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
import { ThreadProjectionIndex } from "./thread-projection-index";
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
  certified: boolean;
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
  withdrawnSources: Set<string>;
}

function addRange(ranges: Ranges, first: number, last = first): void {
  let start = first;
  let end = last;
  let index = rangeAt(ranges, start - 1);
  const from = index;
  while (index < ranges.length && ranges[index][0] <= end + 1) {
    start = Math.min(start, ranges[index][0]);
    end = Math.max(end, ranges[index][1]);
    index++;
  }
  ranges.splice(from, index - from, [start, end]);
}
function rangeAt(ranges: Ranges, seq: number): number {
  let low = 0;
  let high = ranges.length;
  while (low < high) {
    const mid = (low + high) >>> 1;
    if (ranges[mid][1] < seq) low = mid + 1;
    else high = mid;
  }
  return low;
}
function contains(ranges: Ranges | undefined, seq: number): boolean {
  if (!ranges) return false;
  const index = rangeAt(ranges, seq);
  return index < ranges.length && ranges[index][0] <= seq;
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
  for (const [turn, ranges] of members) {
    const covered = coverage.get(turn) ?? [];
    for (const [first, last] of ranges) {
      for (let index = rangeAt(covered, first); index < covered.length && covered[index][0] <= last; index++) {
        const [a, b] = covered[index];
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
function matchUnits(candidates: Set<Unit>, retained: Set<Unit>): {
  byOld: Map<Unit, Set<Unit>>; byNew: Map<Unit, Set<Unit>>;
} {
  const sources = new Map<string, Unit>();
  type Interval = { unit: Unit; start: number; end: number; maxEnd: number };
  const wires = new Map<string, Interval[]>();
  const wireKey = (text: TextSource) => JSON.stringify([text.turn, text.phase, text.stream]);
  for (const unit of candidates) {
    for (const source of unit.sources) if (!source.startsWith("text:")) sources.set(source, unit);
    for (const text of unit.text) {
      const key = wireKey(text);
      const intervals = wires.get(key) ?? [];
      const namedAnswer = text.phase === "answer" && text.stream !== "";
      intervals.push({ unit, start: namedAnswer ? -Infinity : text.after ?? -1,
        end: namedAnswer ? Infinity : text.end ?? Infinity, maxEnd: -Infinity });
      wires.set(key, intervals);
    }
  }
  for (const intervals of wires.values()) {
    intervals.sort((a, b) => a.start - b.start);
    let max = -Infinity;
    for (const interval of intervals) interval.maxEnd = max = Math.max(max, interval.end);
  }
  const byOld = new Map<Unit, Set<Unit>>();
  const byNew = new Map<Unit, Set<Unit>>();
  for (const old of retained) {
    const matches = new Set<Unit>();
    for (const source of old.sources) {
      const unit = sources.get(source);
      if (unit) matches.add(unit);
    }
    for (const text of old.text) {
      const intervals = wires.get(wireKey(text));
      if (!intervals) continue;
      for (const [first, last] of text.members) {
        let low = 0;
        let high = intervals.length;
        while (low < high) {
          const mid = (low + high) >>> 1;
          if (intervals[mid].start < last) low = mid + 1;
          else high = mid;
        }
        for (let i = low - 1; i >= 0 && intervals[i].maxEnd >= first; i--) {
          if (intervals[i].end >= first) matches.add(intervals[i].unit);
        }
      }
    }
    if (!matches.size) continue;
    byOld.set(old, matches);
    for (const unit of matches) {
      const previous = byNew.get(unit) ?? new Set<Unit>();
      previous.add(old);
      byNew.set(unit, previous);
    }
  }
  return { byOld, byNew };
}
function unitPosition(unit: Unit | undefined, turn: string): number | null {
  if (!unit) return null;
  const positions = unit.members.get(turn)?.map(([first]) => first) ?? [];
  for (const source of unit.text) if (source.turn === turn) {
    positions.push(...source.members.map(([first]) => first));
  }
  return positions.length ? Math.min(...positions) : null;
}

/** One received projection and accepted history frontier. HTTP replay is scratch only.
 * Record ranges identify stored pages; text_from_seq identifies the live text a
 * stored end replaces, scoped to its turn, phase and stream. Neither range
 * implies that intervening tools or the rest of the turn have been loaded.
 */
export class ThreadTranscript {
  projection: ThreadProjectionState;
  sideChannelTurnIds = new Set<string>();
  paging = emptyPaging();
  private units = new Set<Unit>();
  private byRow = new Map<string, Unit>();
  private bySource = new Map<string, Unit>();
  private projectionIndex = new ThreadProjectionIndex();
  private historyReplay: { events: ThreadProjectionEvent[]; generation: string | null; owner: ThreadTranscript } | null = null;
  private installed: Members = new Map();
  private textCoverage: TextSource[] = [];
  private boundaries = new Map<string, number>();
  private knownTurns = new Set<string>();
  private fragments: WebuiThreadPersistedPayload[] = [];
  private live: LiveContribution[] = [];
  private historyGeneration: string | null = null;
  private pendingFragmentGap: PendingFragmentGap | null = null;
  private withdrawnSources = new Set<string>();
  fragmentCompletedTurnIds: string[] = [];
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
      this.withdrawnSources = new Set(saved.withdrawnSources);
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
      let after = "text_from_seq" in event && event.text_from_seq !== undefined ? event.text_from_seq - 1
        : phase === "answer" && stream ? 0
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
        certified: "text_from_seq" in event && event.text_from_seq !== undefined,
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
    contributions?: ThreadProjectionEvent[]; sourceRevision?: number; mutableCollections?: boolean;
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
      // Sequence ordering proves this belongs before the installed completion,
      // rather than a new execution that happens to reuse its transport id.
      scratchState.closedTurnIds.delete(event.turn_id!);
      scratchState.turnAliases.delete(event.turn_id!);
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
        closedAssistantIds: scratch.closedAssistantIds, closedAnswerStreamIds: scratch.closedAnswerStreamIds };
    } else {
      projection = projectThreadEvent(projection, event, { ...options, effects, index: this.projectionIndex });
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
            if (!matching.snapshot || prior.through > matching.through) {
              matching.through = prior.through;
              matching.after = prior.after;
              matching.certified = prior.certified;
            }
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
    for (const text of unit.text) for (const certificate of candidate.textCoverage) {
      if (certificate.after !== null && sameWire(certificate, text)) {
        mergeCoveredMembers(represented, new Map([[text.turn, text.members]]),
          new Map([[text.turn, [[certificate.after + 1, certificate.through]]]]));
      }
    }
    return Array.from(unit.members).every(([turn, ranges]) => ranges.every(([first, last]) =>
      represented.get(turn)?.some(([a, b]) => a <= first && b >= last)));

  }

  private stageFragment(joined: ReturnType<typeof joinThreadFragments>, read: ThreadRead,
    gap: PendingFragmentGap | null): true {
    const page = joined.body.page!;
    this.fragments = joined.pages;
    // The visible projection is retained until admission, including across cache restore.
    for (const event of joined.withdrawn) this.withdrawnSources.add(this.describe(event).source);
    this.pendingFragmentGap = gap;
    this.historyGeneration = page.history_generation ?? this.historyGeneration;
    this.paging = { ...this.paging, loading: false, loadingOlder: false, error: null, olderError: null,
      beforeCursor: page.before_cursor ?? null, hasMoreBefore: page.has_more_before === true, truncated: true,
      version: this.paging.version + (read.kind === "older" ? 0 : 1),
      lineage: this.paging.lineage + (read.kind === "older" ? 0 : 1) };
    return true;
  }

  private projectHistory(events: ThreadProjectionEvent[], generation: string | null): ThreadTranscript {
    const previous = this.historyReplay;
    const reuse = previous?.generation === generation && events.length >= previous.events.length
      && previous.events.every((event, index) => event === events[index]
        || JSON.stringify(event) === JSON.stringify(events[index]));
    const candidate = new ThreadTranscript([], undefined, { recordLiveContributions: false });
    if (reuse) {
      const owner = previous.owner;
      candidate.projection = copyThreadCheckpoint(owner).projection;
      candidate.units = new Set(owner.units);
      candidate.byRow = new Map(owner.byRow);
      candidate.bySource = new Map(owner.bySource);
      candidate.boundaries = new Map(owner.boundaries);
      candidate.knownTurns = new Set(owner.knownTurns);
      candidate.order = owner.order;
    }
    for (let index = reuse ? previous.events.length : 0; index < events.length; index++) {
      candidate.project(events[index], { createId: () => `history-${index}`, now: 0, persisted: true, mutableCollections: true });
    }
    // Only canonical replay is reusable; live overlays and admission never enter this cache.
    this.historyReplay = { events, generation, owner: candidate };
    return candidate;
  }

  accept(body: WebuiThreadPersistedPayload | null, read: ThreadRead): boolean {
    this.fragmentCompletedTurnIds = [];
    if (read.kind === "older" && (read.lineage !== this.paging.lineage || read.before !== this.paging.beforeCursor)) return false;
    // An initial network read may have started just before its cached seed was installed.
    if (read.kind !== "older" && read.lineage !== this.paging.lineage
      && !(read.kind === "initial" && read.lineage === 0 && this.paging.lineage === 1)) return false;
    if (read.kind === "older" && !body?.page) {
      this.finishRead(read, "Earlier history did not include a page cursor");
      return false;
    }
    if (read.kind === "older" && body?.page?.has_more_before === true
      && (!body.page.before_cursor || body.page.before_cursor === read.before)) {
      this.finishRead(read, "Earlier history cursor did not advance");
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
    const replaceWindow = hasGap && !pending && this.live.length === 0
      && Array.from(this.units).every((unit) => unit.received === 0);
    if (hasGap && !replaceWindow && joined && groupRange && gap) {
      const page = body!.page!;
      if (!page.has_more_before || !page.before_cursor || page.before_cursor === read.before) {
        this.finishRead(read, "Could not bridge the missing history records");
        return false;
      }
      return this.stageFragment(joined, read, { ...gap, front: groupRange.start });
    }
    const canonical = body ? persistedCanonicalRunState(body) : null;
    const completed = new Set(canonical?.completedTurnIds);
    const completeSnapshot = !body?.page?.truncated_oversized_turn && (!joined || groupRange?.start === 0);
    let candidate = this.projectHistory(body?.events ?? [], generation);
    const durableText = new Map<string, TextSource>();
    for (const unit of candidate.units) {
      mergeMembers(candidate.installed, unit.members);
      for (const text of unit.text) if (text.snapshot && text.after !== null
        && (text.certified || (completeSnapshot && completed.has(text.turn)))) {
        const previous = durableText.get(textKey(text));
        if (!previous || text.through > previous.through) durableText.set(textKey(text), copyText(text));
      }
    }
    const durableMembers = joined ? candidate.installed : null;
    candidate.textCoverage = Array.from(durableText.values());
    // Rebuild a fragment only when it has unpersisted contributions. Those
    // events join the same projection as history, rather than a second overlay.
    if (joined && body) {
      const turns = new Set(body.events.map((event) => event.turn_id));
      const remaining = this.live.filter(({ event }) => event.turn_id && event.turn_seq !== undefined
        && turns.has(event.turn_id) && !candidate.represented(event));
      if (remaining.length) {
        const replay: Array<{ event: ThreadProjectionEvent; live?: LiveContribution }> = body.events.map((event) => ({ event }));
        for (const entry of remaining) {
          const { event } = entry;
          let position = replay.findIndex((item) => item.event.turn_id === event.turn_id
            && item.event.turn_seq !== undefined && item.event.turn_seq > event.turn_seq!);
          if (position < 0) {
            position = replay.findIndex((item) => item.event.event === "user_message"
              && (this.bySource.get(this.describe(item.event).source)?.introduced ?? 0) > entry.revision);
            if (position < 0) position = replay.length;
          }
          replay.splice(position, 0, { event, live: entry });
        }
        candidate = new ThreadTranscript();
        for (const [index, item] of replay.entries()) candidate.project(item.event, item.live
          ? { createId: () => `live-${item.live!.revision}-${index}`, now: item.live.now,
              startSeq: item.live.startSeq, sideChannel: item.live.sideChannel, sourceRevision: item.live.revision }
          : { createId: () => `history-${index}`, now: 0, persisted: true });
        for (const unit of candidate.units) mergeMembers(candidate.installed, unit.members);
        candidate.textCoverage = Array.from(durableText.values());
      }
    }
    // Canonical recovery may replace an unfinished stream with a final message.
    if (durableMembers && completeSnapshot) for (const event of body?.events ?? []) {
      if (event.event !== "message" || event.kind !== undefined || !event.turn_id || !completed.has(event.turn_id)) continue;
      const unit = candidate.bySource.get(this.describe(event).source);
      if (unit) mergeMembers(durableMembers, unit.members);
    }
    // An unknown-left end may overwrite an unpersisted live buffer. Stage the
    // fragment before admission, keeping the visible projection until its prefix arrives.
    const overwritesLive = joined && candidate.live.some(({ event }) => {
      if ((event.event !== "delta" && event.event !== "reasoning_delta") || !event.turn_id
        || event.turn_seq === undefined || contains(durableMembers?.get(event.turn_id), event.turn_seq)) return false;
      return body?.events.some((end) => {
        if (end.turn_id !== event.turn_id || end.turn_seq === undefined || end.turn_seq <= event.turn_seq!) return false;
        if (event.event === "delta" && end.event === "message" && end.kind === undefined) return true;
        if (end.event !== "stream_end" && end.event !== "reasoning_end") return false;
        return (end.stream_id ?? "") === (event.stream_id ?? "")
          && ((event.event === "delta" && end.event === "stream_end" && typeof end.text === "string")
            || (event.event === "reasoning_delta" && end.event === "reasoning_end" && !!end.text));
      });
    });
    if (overwritesLive && joined && groupRange) {
      return this.stageFragment(joined, read, groupRange.start > 0
        ? { turn: groupRange.turn, oldEnd: 0, front: groupRange.start } : null);
    }
    const withdrawnSources = new Set([...this.withdrawnSources, ...(joined?.withdrawn ?? []).map((event) => this.describe(event).source)]);
    const withdrawn = new Set(Array.from(withdrawnSources).flatMap((source) => {
      const unit = this.bySource.get(source);
      return unit ? [unit] : [];
    }));
    const matches = matchUnits(candidate.units, this.units);
    const overlaps = new Set([...withdrawn, ...matches.byOld.keys()]);
    const firstOverlap = this.messages.findIndex((row) => overlaps.has(this.byRow.get(row.id)!));
    const windowRows = new Set(this.messages.slice(Math.max(0, firstOverlap)).map((row) => row.id));
    const received = replacedHistory ? [] : Array.from(this.units).filter((unit) => unit.received > 0
      && Array.from(unit.rows).some((id) => windowRows.has(id)));
    const protectedUnits = received.filter((unit) => !this.unitCovered(unit, candidate));
    const newTail = read.empty && protectedUnits.length > 0
      && protectedUnits.every((unit) => unit.received > read.revision);
    const appendedInputs = this.messages.filter((row) => row.role === "user" && row.turnId
      && this.byRow.get(row.id)!.introduced > read.revision);
    const appendedTurns = new Set(appendedInputs.map((row) => row.turnId!));
    const appendedInputUnits = new Set(appendedInputs.map((row) => this.byRow.get(row.id)!));
    const reset = replacedHistory || replaceWindow || (read.kind === "latest" && overlaps.size === 0
      && !body?.page?.truncated_oversized_turn
      && protectedUnits.every((unit) => unit.introduced > read.revision
        && (appendedInputUnits.has(unit) || (unit.members.size > 0
          && Array.from(unit.members.keys()).every((turn) => appendedTurns.has(turn))))));
    if (read.kind !== "older" && this.messages.length > 0 && overlaps.size === 0 && !newTail && !reset) {
      this.finishRead(read);
      return false;
    }
    const held = new Set<Unit>();
    const protectedStarts = new Map<string, number>();
    for (const old of protectedUnits) {
      for (const unit of matches.byOld.get(old) ?? []) held.add(unit);
      for (const turn of old.members.keys()) {
        const start = unitPosition(old, turn);
        if (start !== null) protectedStarts.set(turn, Math.min(start, protectedStarts.get(turn) ?? Infinity));
      }
    }
    for (const unit of candidate.units) for (const turn of unit.members.keys()) {
      const start = protectedStarts.get(turn);
      const at = start === undefined ? null : unitPosition(unit, turn);
      if (at !== null && at >= start!) held.add(unit);
    }
    const rows = candidate.messages;
    let cut = rows.findIndex((row) => held.has(candidate.byRow.get(row.id)!));
    if (cut < 0) cut = rows.length;
    const lastRow = new Map<Unit, number>();
    rows.forEach((row, index) => lastRow.set(candidate.byRow.get(row.id)!, index));
    // A whole source can straddle several rows: never install only part of it.
    for (let changed = true; changed;) {
      changed = false;
      for (let index = 0; index < cut; index++) {
        const unit = candidate.byRow.get(rows[index].id)!;
        if (lastRow.get(unit)! >= cut) { cut = index; changed = true; break; }
      }
    }
    const admittedRows = rows.slice(0, cut);
    const admitted = new Set(admittedRows.map((row) => candidate.byRow.get(row.id)!));
    const cutOrder = cut < rows.length ? candidate.byRow.get(rows[cut].id)!.order : Infinity;
    for (const unit of candidate.units) {
      if (unit.rows.size === 0 && unit.order < cutOrder && !held.has(unit)) admitted.add(unit);
    }
    if (read.kind === "older" && Array.from(candidate.units).some((unit) => !admitted.has(unit)
      && !matches.byNew.has(unit))) {
      this.finishRead(read, "Could not place earlier history");
      return false;
    }
    const fullyAdopt = protectedUnits.length === 0 && cut === rows.length
      && !body?.page?.truncated_oversized_turn
      && (this.messages.length === 0 || reset || overlaps.size > 0);
    const replaced = new Set<Unit>();
    for (const old of this.units) if ((reset && !protectedUnits.includes(old))
      || ((withdrawn.has(old) || Array.from(matches.byOld.get(old) ?? []).some((unit) => admitted.has(unit)))
        && (old.received === 0 || this.unitCovered(old, candidate)))) replaced.add(old);
    const previousCount = this.messages.length;
    const firstReplaced = this.messages.findIndex((row) => replaced.has(this.byRow.get(row.id)!));
    const prefix = read.kind !== "older" && !reset && firstReplaced > 0
      ? this.messages.slice(0, firstReplaced) : [];
    const keepSuffix = !fullyAdopt || read.kind === "older";
    const anchors = new Map<Unit, number>();
    if (keepSuffix) for (const [index, row] of this.messages.entries()) {
      const old = this.byRow.get(row.id)!;
      if (!replaced.has(old)) continue;
      for (const unit of matches.byOld.get(old) ?? []) {
        if (admitted.has(unit) && !anchors.has(unit)) anchors.set(unit, index);
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
    this.withdrawnSources = new Set(Array.from(withdrawnSources).filter((source) => withdrawn.has(this.bySource.get(source)!)));
    const retainedMembers: Members = new Map();
    for (const unit of this.units) mergeMembers(retainedMembers, unit.members);
    const installed: Members = new Map();
    mergeCoveredMembers(installed, this.installed, retainedMembers);
    const certificates = new Map(this.textCoverage
      .filter((text) => this.bySource.has(`text:${textKey(text)}`))
      .map((text) => [textKey(text), text]));
    for (const unit of admitted) {
      if (durableMembers) mergeCoveredMembers(installed, unit.members, durableMembers);
      else mergeMembers(installed, unit.members);
      for (const text of unit.text) {
        const evidence = durableText.get(textKey(text));
        if (!evidence?.snapshot || evidence.after === null) continue;
        const previous = certificates.get(textKey(evidence));
        if (!previous || evidence.through > previous.through) certificates.set(textKey(evidence), copyText(evidence));
      }
    }
    this.installed = installed;
    this.textCoverage = Array.from(certificates.values());
    const confirmedInputs = new Set<string>();
    for (const event of body?.events ?? []) {
      if (event.event !== "user_message" || !admitted.has(candidate.bySource.get(candidate.describe(event).source)!)) continue;
      if (event.input_id) confirmedInputs.add(`id:${event.input_id}`);
      if (event.provenance?.session_message?.message_id) confirmedInputs.add(`message:${event.provenance.session_message.message_id}`);
    }
    this.live = this.live.filter(({ event }) => !(event.event === "user_message"
      && ((event.input_id && confirmedInputs.has(`id:${event.input_id}`))
        || (event.provenance?.session_message?.message_id && confirmedInputs.has(`message:${event.provenance.session_message.message_id}`))))
      && !this.represented(event));
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
    this.projection.closedTurnIds = new Set(this.projection.closedTurnIds);
    this.projection.closedAssistantIds = new Set(this.projection.closedAssistantIds);
    this.projection.closedAnswerStreamIds = new Set(this.projection.closedAnswerStreamIds);
    for (const event of body?.events ?? []) {
      if (event.event === "turn_end" && event.turn_id && event.turn_seq !== undefined
        && contains(this.installed.get(event.turn_id), event.turn_seq)) this.projection.closedTurnIds.add(event.turn_id);
    }
    const admittedRowIds = new Set(admittedRows.map((row) => row.id));
    for (const id of candidate.projection.closedAssistantIds) {
      if (admittedRowIds.has(id)) this.projection.closedAssistantIds.add(id);
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
    if (joined && admitted.size === candidate.units.size) this.fragmentCompletedTurnIds = [...completed];
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
    const previous = this.byRow.get(target.id)!;
    const unit = { ...previous, rows: new Set(previous.rows) };
    this.units.delete(previous);
    unit.rows.delete(target.id);
    this.byRow.delete(target.id);
    const replacements = scratch.messages.map((row) => ({ ...row, activitySegmentId: target.activitySegmentId }));
    for (const row of replacements) unit.rows.add(row.id);
    this.installUnit(unit);
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
      pendingFragmentGap: this.pendingFragmentGap ? { ...this.pendingFragmentGap } : null,
      withdrawnSources: new Set(this.withdrawnSources) };
  }
}
