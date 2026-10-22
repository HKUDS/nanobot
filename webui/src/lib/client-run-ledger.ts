import type { ServerRun, ServerRunSnapshot } from "./server-run-state";

type TurnRef = Readonly<{ chatId: string; turnId: string }>;
type DeliveryRole = "candidate-owner" | "supplement";
type Delivery = { phase: "queued" | "sent" | "unknown" | "accepted"; role: DeliveryRole };

interface TurnRecord {
  delivery: Delivery | null;
  openOrder: number | null;
}

interface ChatRecord {
  generation: number;
  latestTurnId: string | null;
  turns: Map<string, TurnRecord>;
  closed: Set<string>;
  fenced: Set<string>;
  snapshot: ServerRunSnapshot | null;
  fresh: boolean;
  cancelling: Set<string>;
}

export interface CanonicalRunSnapshot {
  observedTurnIds: readonly string[];
  /** Transcript completeness, not current execution liveness. */
  hasPendingToolCalls: boolean;
  activeTurnId?: string | null;
  completionIdsProvided?: boolean;
}

interface CanonicalRequest {
  chatId: string;
  generation: number;
  completedTurnIds: readonly string[];
  snapshot?: CanonicalRunSnapshot;
}

export type RunObservation = Readonly<{
  chatId: string;
  turnId: string | null;
  systemCommand?: boolean;
}> & (
  | { kind: "admission" | "input"; owner?: string }
  | { kind: "completed" | "message" | "receipt" | "idle" | "rejection" }
);

type Command =
  | ({ kind: "submit"; role: DeliveryRole } & TurnRef)
  | ({ kind: "written" | "reject" | "delivery-unknown" } & TurnRef)
  | { kind: "transport-lost" }
  | { kind: "forget"; chatId: string }
  | { kind: "cancel-request"; chatId: string; runIds: readonly string[] }
  | { kind: "cancel-rejected"; chatId: string }
  | { kind: "fence"; chatId: string; completedTurnIds: readonly string[] };

export type RunEffect =
  | { kind: "run-status"; chatId: string; state: RunState }
  | { kind: "completion"; chatId: string }
  | ({ kind: "discard-send" } & TurnRef)
  | { kind: "prune-inbound"; chatId: string; turnIds: readonly string[] };

interface ObservationResult {
  forward: "normal" | "without-owner" | "drop";
  effects: readonly RunEffect[];
}

export interface RunState {
  /** Last server-confirmed execution set; consult freshness before presenting it as current. */
  active: boolean;
  freshness: "syncing" | "fresh" | "unknown" | "unavailable";
  phase: "idle" | "queued" | "running" | "stopping";
  runs: readonly ServerRun[];
  delivery: "none" | "sending" | "accepted" | "unknown";
  cancelPending: boolean;
  generation: number;
  latestTurnId: string | null;
  startedAt: number | null;
  /** A result or message receipt is still outstanding, independently of execution. */
  unsettled: boolean;
}

const COMPLETED_TURN_FENCE_MAX = 256;
const NO_RUNS: readonly ServerRun[] = [];

/** One client owns execution snapshots, local delivery and canonical fences as separate facts. */
export class ClientRunLedger {
  private chats = new Map<string, ChatRecord>();
  private instanceId: string | null = null;
  private authority: "syncing" | "connected" | "unknown" | "unavailable" = "syncing";

  view(chatId: string): RunState {
    const chat = this.chats.get(chatId);
    const runs = chat?.snapshot?.runs ?? NO_RUNS;
    let delivery: RunState["delivery"] = "none";
    for (const turn of chat?.turns.values() ?? []) {
      const phase = turn.delivery?.phase;
      if (phase === "unknown") { delivery = "unknown"; break; }
      if (phase === "queued" || phase === "sent") delivery = "sending";
      else if (phase === "accepted" && delivery === "none") delivery = "accepted";
    }
    const starts = runs.flatMap((run) => run.started_at === null ? [] : [run.started_at]);
    return {
      active: runs.length > 0,
      freshness: this.authority === "connected" ? chat?.fresh ? "fresh" : "syncing" : this.authority,
      phase: runs.some((run) => run.phase === "stopping") ? "stopping"
        : runs.some((run) => run.phase === "running") ? "running" : runs.length ? "queued" : "idle",
      runs,
      delivery,
      cancelPending: (chat?.cancelling.size ?? 0) > 0,
      generation: chat?.generation ?? 0,
      latestTurnId: chat?.latestTurnId ?? null,
      startedAt: starts.length ? Math.max(...starts) : null,
      unsettled: this.hasOpenTurn(chat) || delivery !== "none",
    };
  }

  /** Only an authenticated current socket's ready handshake may pin the authority epoch. */
  pinAuthority(instanceId: string | null): readonly RunEffect[] {
    const before = this.states();
    const changed = this.instanceId !== instanceId;
    this.instanceId = instanceId;
    this.authority = instanceId === null ? "unavailable" : "connected";
    for (const chat of this.chats.values()) {
      chat.fresh = false;
      if (!changed) continue;
      chat.snapshot = null;
      chat.cancelling.clear();
      for (const turn of chat.turns.values()) {
        if (turn.delivery?.phase === "accepted") turn.delivery = { ...turn.delivery, phase: "unknown" };
      }
    }
    return before.flatMap(({ chatId, state }) => this.withRunStatus(chatId, state, []));
  }

  ingestSnapshot(chatId: string, snapshot: ServerRunSnapshot, socketBaseline = false): { accepted: boolean; effects: readonly RunEffect[] } {
    if (this.authority !== "connected" || snapshot.instance_id !== this.instanceId
      || (!socketBaseline && !this.chats.get(chatId)?.fresh)) return { accepted: false, effects: [] };
    const before = this.view(chatId);
    const chat = this.ensureChat(chatId);
    if (chat.snapshot && snapshot.revision < chat.snapshot.revision) return { accepted: false, effects: [] };
    if (chat.fresh && chat.snapshot?.revision === snapshot.revision) return { accepted: true, effects: [] };
    const previousRuns = chat.snapshot?.runs ?? NO_RUNS;
    chat.snapshot = snapshot;
    // A late pre-outage HTTP response cannot certify that this socket has caught up.
    if (socketBaseline) chat.fresh = true;
    const owners = new Set(snapshot.runs.map((run) => run.run_id));
    for (const owner of chat.cancelling) if (!owners.has(owner)) chat.cancelling.delete(owner);
    for (const run of snapshot.runs) {
      if (!run.turn_id || chat.closed.has(run.turn_id) || chat.fenced.has(run.turn_id)) continue;
      if (!chat.turns.has(run.turn_id)) this.advance(chat, run.turn_id);
      this.accept(chat, run.turn_id);
    }
    // Execution exit requests a new result read; it does not settle delivery or prune transcript frames.
    const ended = previousRuns.some((run) => !owners.has(run.run_id));
    const effects: RunEffect[] = ended ? [{ kind: "completion", chatId }] : [];
    return { accepted: true, effects: this.withRunStatus(chatId, before, effects) };
  }

  isCompleted({ chatId, turnId }: TurnRef): boolean {
    const chat = this.chats.get(chatId);
    return chat?.closed.has(turnId) === true || chat?.fenced.has(turnId) === true;
  }

  isFenced({ chatId, turnId }: TurnRef): boolean {
    return this.chats.get(chatId)?.fenced.has(turnId) === true;
  }

  hasPendingSend({ chatId, turnId }: TurnRef): boolean {
    return this.chats.get(chatId)?.turns.get(turnId)?.delivery != null;
  }

  states(): readonly Readonly<{ chatId: string; state: RunState }>[] {
    return Array.from(this.chats.keys(), (chatId) => ({ chatId, state: this.view(chatId) }));
  }

  unresolvedChatIds(): string[] {
    return this.states().filter(({ state }) => state.active || state.unsettled).map(({ chatId }) => chatId);
  }

  soleSentTurn(lastApplicationMessage: TurnRef | null, chatId?: string): TurnRef | null {
    if (lastApplicationMessage === null) return null;
    let candidate: TurnRef | null = null;
    for (const [id, chat] of this.chats) {
      if (chatId !== undefined && id !== chatId) continue;
      for (const [turnId, turn] of chat.turns) {
        if (turn.delivery?.phase !== "sent") continue;
        if (candidate !== null) return null;
        candidate = { chatId: id, turnId };
      }
    }
    return candidate?.chatId === lastApplicationMessage.chatId
      && candidate.turnId === lastApplicationMessage.turnId ? candidate : null;
  }

  soleUnsettledTurn(chatId: string): string | null {
    const ids = Array.from(this.chats.get(chatId)?.turns ?? []).filter(([, turn]) => turn.openOrder !== null);
    return ids.length === 1 ? ids[0][0] : null;
  }

  transition(command: Command): readonly RunEffect[] {
    if (command.kind === "transport-lost") {
      const before = this.states();
      this.authority = "unknown";
      for (const chat of this.chats.values()) {
        chat.fresh = false;
        chat.cancelling.clear();
        for (const turn of chat.turns.values()) {
          if (turn.delivery?.phase === "sent") turn.delivery = { ...turn.delivery, phase: "unknown" };
        }
      }
      return before.flatMap(({ chatId, state }) => this.withRunStatus(chatId, state, []));
    }
    const before = this.view(command.chatId);
    const effects: RunEffect[] = [];
    switch (command.kind) {
      case "submit": {
        const chat = this.ensureChat(command.chatId);
        if (!chat.turns.has(command.turnId) && command.role === "candidate-owner") this.advance(chat, command.turnId);
        this.ensureTurn(chat, command.turnId).delivery = { phase: "queued", role: command.role };
        break;
      }
      case "written": {
        const turn = this.chats.get(command.chatId)?.turns.get(command.turnId);
        if (turn?.delivery) turn.delivery = { ...turn.delivery, phase: "sent" };
        break;
      }
      case "reject":
        this.reject(command.chatId, command.turnId, effects);
        break;
      case "delivery-unknown": {
        const turn = this.chats.get(command.chatId)?.turns.get(command.turnId);
        if (turn?.delivery && (turn.delivery.phase === "sent" || turn.delivery.phase === "queued")) {
          turn.delivery = { ...turn.delivery, phase: "unknown" };
        }
        break;
      }
      case "forget":
        this.chats.delete(command.chatId);
        break;
      case "cancel-request":
        this.ensureChat(command.chatId).cancelling = new Set(command.runIds);
        break;
      case "cancel-rejected":
        this.chats.get(command.chatId)?.cancelling.clear();
        break;
      case "fence":
        this.fence(command.chatId, command.completedTurnIds, effects);
        break;
    }
    return this.withRunStatus(command.chatId, before, effects);
  }

  private withRunStatus(chatId: string, before: RunState, effects: readonly RunEffect[]): readonly RunEffect[] {
    const state = this.view(chatId);
    if (state.active === before.active && state.startedAt === before.startedAt
      && state.latestTurnId === before.latestTurnId && state.generation === before.generation
      && state.unsettled === before.unsettled && state.freshness === before.freshness
      && state.phase === before.phase && state.delivery === before.delivery
      && state.cancelPending === before.cancelPending && state.runs === before.runs) return effects;
    return [...effects, { kind: "run-status", chatId, state }];
  }

  observe(observation: RunObservation): ObservationResult {
    const before = this.view(observation.chatId);
    const { chatId, turnId } = observation;
    let chat = this.chats.get(chatId);
    const effects: RunEffect[] = [];
    if (observation.kind === "idle"
      && ((turnId === null && this.hasOpenTurn(chat))
        || (turnId !== null && chat?.latestTurnId != null && turnId !== chat.latestTurnId))) {
      return { forward: "drop", effects };
    }
    if (turnId !== null && chat?.fenced.has(turnId)) return { forward: "drop", effects };
    if (turnId && chat?.closed.has(turnId) && observation.kind !== "admission" && observation.kind !== "input"
      && observation.kind !== "message" && observation.kind !== "completed"
      && observation.kind !== "idle") return { forward: "drop", effects };
    let forward: ObservationResult["forward"] = "normal";
    if (!observation.systemCommand) {
      if ((observation.kind === "admission" || observation.kind === "input") && observation.owner) {
        const owner = observation.owner;
        chat = this.ensureChat(chatId);
        if (chat.closed.has(owner) || chat.fenced.has(owner)) {
          if (turnId && turnId !== owner && chat.turns.get(turnId)?.delivery?.role === "candidate-owner") {
            this.reject(chatId, turnId, effects);
          }
          forward = "without-owner";
        } else {
          if (turnId && turnId !== owner && chat.turns.get(turnId)?.delivery?.role === "candidate-owner") {
            this.settle(chatId, turnId, effects);
          }
          if (chat.latestTurnId !== owner) this.advance(chat, owner);
        }
      }
      if (turnId) this.accept(chat, turnId);
      if (observation.kind === "rejection" && turnId) this.reject(chatId, turnId, effects);
      if (observation.kind === "completed") {
        chat = this.ensureChat(chatId);
        if (turnId) {
          chat.closed.add(turnId);
          this.trimTerminalSet(chat.closed);
          this.settle(chatId, turnId, effects);
        }
        effects.push({ kind: "completion", chatId });
      }
    }
    return { forward, effects: this.withRunStatus(chatId, before, effects) };
  }

  canApplyCanonical(request: CanonicalRequest): boolean {
    const chat = this.chats.get(request.chatId);
    const completed = new Set([...chat?.fenced ?? [], ...request.completedTurnIds]);
    const observed = new Set(request.snapshot?.observedTurnIds ?? []);
    const willSettle = (turnId: string) => this.canonicalTurnWillSettle(
      turnId, completed, observed, request.snapshot, chat?.turns.get(turnId)?.delivery?.role,
    );
    if (chat) for (const [turnId, turn] of chat.turns) {
      if (turn.openOrder !== null && !willSettle(turnId)) return false;
    }
    const latest = chat?.latestTurnId;
    return (chat?.generation ?? 0) === request.generation || (latest != null && willSettle(latest));
  }

  applyCanonical(request: CanonicalRequest): { accepted: boolean; effects: readonly RunEffect[] } {
    const before = this.view(request.chatId);
    const effects: RunEffect[] = [];
    // The caller commits canonical text first. Fences never imply execution idle.
    this.fence(request.chatId, request.completedTurnIds, effects);
    const accepted = this.canApplyCanonical({ ...request, completedTurnIds: [] });
    if (accepted) {
      const chat = this.chats.get(request.chatId);
      const observed = new Set(request.snapshot?.observedTurnIds ?? []);
      if (chat) for (const [turnId, turn] of chat.turns) {
        if (!this.canonicalTurnWillSettle(turnId, chat.fenced, observed, request.snapshot, turn.delivery?.role)) continue;
        if (turn.delivery?.role !== "supplement") {
          chat.closed.add(turnId);
          this.trimTerminalSet(chat.closed);
        }
        this.settle(request.chatId, turnId, effects);
      }
    }
    return { accepted, effects: this.withRunStatus(request.chatId, before, effects) };
  }

  private ensureChat(chatId: string): ChatRecord {
    let chat = this.chats.get(chatId);
    if (!chat) {
      chat = { generation: 0, latestTurnId: null, turns: new Map(), closed: new Set(), fenced: new Set(),
        snapshot: null, fresh: false, cancelling: new Set() };
      this.chats.set(chatId, chat);
    }
    return chat;
  }

  private ensureTurn(chat: ChatRecord, turnId: string): TurnRecord {
    let turn = chat.turns.get(turnId);
    if (!turn) { turn = { delivery: null, openOrder: null }; chat.turns.set(turnId, turn); }
    return turn;
  }

  private advance(chat: ChatRecord, turnId: string): void {
    chat.generation += 1;
    chat.latestTurnId = turnId;
    const turn = this.ensureTurn(chat, turnId);
    if (turn.openOrder === null) turn.openOrder = chat.generation;
  }

  private hasOpenTurn(chat: ChatRecord | undefined): boolean {
    return Array.from(chat?.turns.values() ?? []).some((turn) => turn.openOrder !== null);
  }

  private accept(chat: ChatRecord | undefined, turnId: string): void {
    const turn = chat?.turns.get(turnId);
    if (!chat || !turn?.delivery) return;
    if (turn.delivery.role === "supplement") {
      turn.delivery = null;
      if (turn.openOrder === null) chat.turns.delete(turnId);
    } else turn.delivery = { ...turn.delivery, phase: "accepted" };
  }

  private settle(chatId: string, turnId: string, effects: RunEffect[]): void {
    this.chats.get(chatId)?.turns.delete(turnId);
    effects.push({ kind: "discard-send", chatId, turnId });
  }

  private reject(chatId: string, turnId: string, effects: RunEffect[]): void {
    const chat = this.chats.get(chatId);
    this.settle(chatId, turnId, effects);
    effects.push({ kind: "prune-inbound", chatId, turnIds: [turnId] });
    if (chat?.latestTurnId !== turnId) return;
    const previous = Array.from(chat.turns).filter(([, turn]) => turn.openOrder !== null)
      .sort(([, left], [, right]) => (right.openOrder ?? 0) - (left.openOrder ?? 0));
    chat.latestTurnId = previous[0]?.[0] ?? null;
  }

  private fence(chatId: string, turnIds: readonly string[], effects: RunEffect[]): void {
    let chat = this.chats.get(chatId);
    for (const turnId of turnIds) {
      if (!turnId) continue;
      chat ??= this.ensureChat(chatId);
      chat.fenced.add(turnId);
    }
    if (chat) this.trimTerminalSet(chat.fenced);
    effects.push({ kind: "prune-inbound", chatId, turnIds: Array.from(chat?.fenced ?? []) });
  }

  private trimTerminalSet(turnIds: Set<string>): void {
    for (const oldest of turnIds) {
      if (turnIds.size <= COMPLETED_TURN_FENCE_MAX) break;
      turnIds.delete(oldest);
    }
  }

  private canonicalTurnWillSettle(
    turnId: string, completed: ReadonlySet<string>, observed: ReadonlySet<string>, snapshot?: CanonicalRunSnapshot,
    role?: DeliveryRole,
  ): boolean {
    if (completed.has(turnId)) return true;
    // A durable input row confirms an injected message's receipt, not an independent execution/result.
    if (role === "supplement" && observed.has(turnId)) return true;
    if (!snapshot || snapshot.completionIdsProvided || snapshot.activeTurnId === turnId || snapshot.hasPendingToolCalls) return false;
    // Compatibility with old transcript pages still requires an observed result; absence is not delivery proof.
    return observed.has(turnId);
  }
}
