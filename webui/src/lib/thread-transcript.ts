import {
  projectThreadEvent,
  type ThreadProjectionEffects,
  type ThreadProjectionState,
} from "./thread-event-projection";
import { persistedCanonicalRunState } from "./canonical-run-snapshot";
import { copyThreadCheckpoint, createThreadCheckpoint, type ThreadCheckpoint } from "./thread-checkpoint";
import { hasPendingAgentActivity } from "./activity-timeline";
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
  hasMoreBefore: boolean;
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
function copyText(value: TextSource): TextSource {
  return { ...value, members: value.members.map(([a, b]) => [a, b]) };
}
function emptyPaging(): ThreadPaging {
  return { loading: false, loadingOlder: false, error: null, olderError: null,
    beforeCursor: null, hasMoreBefore: false, userMessageOffset: 0,
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
  private revision = 0;
  private order = 0;

  constructor(messages: UIMessage[] = [], saved?: ThreadTranscriptSnapshot) {
    const checkpoint = saved ? copyThreadCheckpoint(saved) : createThreadCheckpoint(messages);
    this.projection = checkpoint.projection;
    this.sideChannelTurnIds = checkpoint.sideChannelTurnIds;
    if (saved) {
      this.installed = copyMembers(saved.installed);
      this.textCoverage = saved.textCoverage.map(copyText);
      this.boundaries = new Map(saved.boundaries);
      this.knownTurns = new Set(saved.knownTurns);
      this.paging = { ...saved.paging, loading: false, loadingOlder: false };
      this.revision = saved.revision;
      for (const unit of saved.units) this.installUnit({ ...unit, rows: new Set(unit.rows),
        sources: new Set(unit.sources), members: copyMembers(unit.members), text: unit.text.map(copyText) });
    } else {
      for (const row of messages) this.registerInput(row, false);
    }
  }

  get messages(): UIMessage[] { return this.projection.messages; }

  private installUnit(unit: Unit): void {
    this.order = Math.max(this.order, unit.order + 1);
    this.units.add(unit);
    for (const row of unit.rows) this.byRow.set(row, unit);
    for (const key of unit.sources) this.bySource.set(key, unit);
  }

  rejectTurn(turn: string): void {
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
  }): UIMessage[] {
    if (!options.persisted && this.represented(event)) return this.messages;
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
    this.projection = projection;
    const connected = new Set<Unit>();
    const existing = this.bySource.get(source);
    if (existing) connected.add(existing);
    for (const id of [...effects.bodyWrites, ...effects.consumed]) {
      const unit = this.byRow.get(id);
      if (unit) connected.add(unit);
    }
    const revision = options.persisted ? 0 : ++this.revision;
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
    if (read.kind === "older" && (read.lineage !== this.paging.lineage || read.before !== this.paging.beforeCursor)) return false;
    if (read.kind === "older" && !body?.page) {
      this.finishRead(read, "Earlier history did not include a page cursor");
      return false;
    }
    const candidate = new ThreadTranscript();
    for (const [index, event] of (body?.events ?? []).entries()) candidate.project(event,
      { createId: () => `history-${index}`, now: 0, persisted: true });
    for (const unit of candidate.units) mergeMembers(candidate.installed, unit.members);
    const overlaps = new Set(Array.from(this.units).filter((old) =>
      Array.from(candidate.units).some((unit) => sourcesOverlap(unit, old))));
    const firstOverlap = this.messages.findIndex((row) => overlaps.has(this.byRow.get(row.id)!));
    const windowRows = new Set(this.messages.slice(Math.max(0, firstOverlap)).map((row) => row.id));
    const received = Array.from(this.units).filter((unit) => unit.received > 0
      && Array.from(unit.rows).some((id) => windowRows.has(id)));
    const canonical = body ? persistedCanonicalRunState(body) : null;
    const completed = new Set(canonical?.completedTurnIds);
    const protectedUnits = received.filter((unit) => !this.unitCovered(unit, candidate)
      || (unit.text.length > 0 && (body?.page?.truncated_oversized_turn
        || unit.text.some((text) => !completed.has(text.turn)))));
    const newTail = read.empty && protectedUnits.length > 0
      && protectedUnits.every((unit) => unit.received > read.revision);
    const appendedInputs = this.messages.filter((row) => row.role === "user" && row.turnId
      && this.byRow.get(row.id)!.introduced > read.revision);
    const appendedTurns = new Set(appendedInputs.map((row) => row.turnId!));
    const appendedInputUnits = new Set(appendedInputs.map((row) => this.byRow.get(row.id)!));
    const reset = read.kind === "latest" && overlaps.size === 0
      && !body?.page?.truncated_oversized_turn
      && protectedUnits.every((unit) => unit.introduced > read.revision
        && (appendedInputUnits.has(unit) || (unit.members.size > 0
          && Array.from(unit.members.keys()).every((turn) => appendedTurns.has(turn)))));
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
    if (read.kind === "older" && Array.from(candidate.units).some((unit) => !admitted.has(unit)
      && !Array.from(this.units).some((old) => sourcesOverlap(unit, old)))) {
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
    this.projection = fullyAdopt && read.kind !== "older"
      ? { ...candidate.projection, messages: nextMessages,
          activitySegmentId: candidate.projection.activitySegmentId
            ? segments.get(candidate.projection.activitySegmentId) ?? null : null,
          fileEditSegmentId: candidate.projection.fileEditSegmentId
            ? segments.get(candidate.projection.fileEditSegmentId) ?? null : null,
          closedTurnIds: new Set([...this.projection.closedTurnIds, ...candidate.projection.closedTurnIds]),
          closedAnswerStreamIds: new Set([...this.projection.closedAnswerStreamIds, ...candidate.projection.closedAnswerStreamIds]) }
      : { ...this.projection, messages: nextMessages };
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
      mergeMembers(installed, unit.members);
      for (const text of unit.text) if (text.snapshot && text.after !== null) {
        const previous = certificates.get(textKey(text));
        if (!previous || text.through > previous.through) certificates.set(textKey(text), copyText(text));
      }
    }
    this.installed = installed;
    this.textCoverage = Array.from(certificates.values());
    if (fullyAdopt && read.kind !== "older") {
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
      paging: { ...this.paging }, revision: this.revision };
  }
}
