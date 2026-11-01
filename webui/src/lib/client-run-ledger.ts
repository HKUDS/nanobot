type TurnRef = Readonly<{ chatId: string; turnId: string }>;
type DeliveryRole = "candidate-owner" | "supplement";
type Delivery =
  | { phase: "queued" | "sent" | "unknown"; role: DeliveryRole }
  | { phase: "accepted"; role: "candidate-owner" };

interface TurnRecord {
  delivery: Delivery | null;
  // Only openOrder marks unsettled ownership; a timestamp alone does not.
  openOrder: number | null;
  startedAt: number | null;
}

interface ChatRecord {
  generation: number;
  latestTurnId: string | null;
  effectiveStartedAt: number | null;
  anonymousActive: boolean;
  turns: Map<string, TurnRecord>;
  /** Closed turns permit late inputs, messages, completions and idle. */
  closed: Set<string>;
  /** Canonical fences discard every frame with a matching top-level turn id. */
  fenced: Set<string>;
}

export interface CanonicalRunSnapshot {
  /** User turn ids present in the canonical transcript page. */
  observedTurnIds: readonly string[];
  /** Whether the server still considers the transcript tail active. */
  hasPendingToolCalls: boolean;
  /** Exact active turn when supplied by a current gateway. */
  activeTurnId?: string | null;
  /** Supplied completion identities are authoritative for lifecycle turns. */
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
  | { kind: "admission" | "input"; owner?: { turnId: string; startedAt?: number } }
  | { kind: "status"; activity: "running" | "idle"; startedAt?: number }
  | { kind: "completed" | "message" | "progress" | "activity" | "rejection" }
  | { kind: "recovery"; active: boolean }
);

type Command =
  | ({ kind: "submit"; role: DeliveryRole } & TurnRef)
  | ({ kind: "written" | "reject" } & TurnRef)
  | { kind: "transport-lost" }
  | { kind: "local-stop" | "forget"; chatId: string }
  | { kind: "fence"; chatId: string; completedTurnIds: readonly string[] }
  | { kind: "restore-pending"; chatId: string; generation: number; turnId: string | null };

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
  active: boolean;
  generation: number;
  latestTurnId: string | null;
  startedAt: number | null;
  unsettled: boolean;
}

const COMPLETED_TURN_FENCE_MAX = 256;

export class ClientRunLedger {
  private chats = new Map<string, ChatRecord>();

  view(chatId: string): RunState {
    const chat = this.chats.get(chatId);
    return {
      active: chat?.anonymousActive === true || chat?.effectiveStartedAt != null || this.hasOpenTurn(chat),
      generation: chat?.generation ?? 0,
      latestTurnId: chat?.latestTurnId ?? null,
      startedAt: chat?.effectiveStartedAt ?? null,
      unsettled: this.hasOpenTurn(chat),
    };
  }

  isCompleted({ chatId, turnId }: TurnRef): boolean {
    const chat = this.chats.get(chatId);
    return chat?.closed.has(turnId) === true || chat?.fenced.has(turnId) === true;
  }

  hasPendingSend({ chatId, turnId }: TurnRef): boolean {
    return this.chats.get(chatId)?.turns.get(turnId)?.delivery != null;
  }

  states(): readonly Readonly<{ chatId: string; state: RunState }>[] {
    return Array.from(this.chats.keys(), (chatId) => ({ chatId, state: this.view(chatId) }));
  }

  unresolvedChatIds(): string[] {
    return Array.from(this.chats).flatMap(([chatId, chat]) => (
      chat.anonymousActive || chat.effectiveStartedAt !== null || this.hasOpenTurn(chat) ? [chatId] : []
    ));
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
    const chat = this.chats.get(chatId);
    if (!chat) return null;
    let candidate: string | null = null;
    for (const [turnId, turn] of chat.turns) {
      if (turn.openOrder === null) continue;
      if (candidate !== null) return null;
      candidate = turnId;
    }
    return candidate;
  }

  transition(command: Command): readonly RunEffect[] {
    if (command.kind === "transport-lost") return this.applyCommand(command);
    const before = this.view(command.chatId);
    return this.withRunStatus(command.chatId, before, this.applyCommand(command));
  }

  private withRunStatus(chatId: string, before: RunState, effects: readonly RunEffect[]): readonly RunEffect[] {
    const state = this.view(chatId);
    if (state.active === before.active && state.startedAt === before.startedAt
      && state.latestTurnId === before.latestTurnId && state.generation === before.generation
      && state.unsettled === before.unsettled) return effects;
    return [...effects, { kind: "run-status", chatId, state }];
  }

  private applyCommand(command: Command): readonly RunEffect[] {
    const effects: RunEffect[] = [];
    switch (command.kind) {
      case "submit": {
        const chat = this.ensureChat(command.chatId);
        if (command.role === "candidate-owner") this.advance(chat, command.turnId);
        this.ensureTurn(chat, command.turnId).delivery = { phase: "queued", role: command.role };
        break;
      }
      case "written": {
        const turn = this.chats.get(command.chatId)?.turns.get(command.turnId);
        if (turn?.delivery) turn.delivery = { phase: "sent", role: turn.delivery.role };
        break;
      }
      case "reject":
        this.reject(command.chatId, command.turnId, effects);
        break;
      case "transport-lost":
        for (const chat of this.chats.values()) {
          for (const turn of chat.turns.values()) {
            if (turn.delivery?.phase === "sent") {
              turn.delivery = { phase: "unknown", role: turn.delivery.role };
            }
          }
        }
        break;
      case "local-stop": {
        const chat = this.chats.get(command.chatId);
        if (!chat) break;
        const openTurnIds = this.openTurnIds(chat);
        if (chat.latestTurnId) this.rememberClosed(chat, chat.latestTurnId);
        for (const turnId of openTurnIds) this.rememberClosed(chat, turnId);
        for (const turnId of openTurnIds) this.settle(command.chatId, turnId, effects);
        chat.latestTurnId = null;
        chat.anonymousActive = false;
        chat.effectiveStartedAt = null;
        break;
      }
      case "forget":
        this.chats.delete(command.chatId);
        break;
      case "restore-pending": {
        if (this.view(command.chatId).generation !== command.generation || this.view(command.chatId).active) break;
        const chat = this.ensureChat(command.chatId);
        if (command.turnId
          ? chat.closed.has(command.turnId) || chat.fenced.has(command.turnId)
          : chat.generation !== 0 || chat.closed.size > 0 || chat.fenced.size > 0) break;
        this.advance(chat, command.turnId);
        chat.anonymousActive = command.turnId === null;
        break;
      }
      case "fence":
        this.fence(command.chatId, command.completedTurnIds, effects);
        break;
      default: {
        const unhandled: never = command;
        throw new Error(`Unexpected run command: ${unhandled}`);
      }
    }
    return effects;
  }

  observe(observation: RunObservation): ObservationResult {
    const before = this.view(observation.chatId);
    const result = this.applyObservation(observation);
    return { ...result, effects: this.withRunStatus(observation.chatId, before, result.effects) };
  }

  private applyObservation(observation: RunObservation): ObservationResult {
    const { chatId, turnId } = observation;
    let chat = this.chats.get(chatId);
    const effects: RunEffect[] = [];
    if (turnId !== null && chat?.fenced.has(turnId)) return { forward: "drop", effects };
    if (
      turnId && chat?.closed.has(turnId)
      && observation.kind !== "admission" && observation.kind !== "input"
      && observation.kind !== "message" && observation.kind !== "completed"
      && !(observation.kind === "status" && observation.activity === "idle")
    ) return { forward: "drop", effects };

    let forward: ObservationResult["forward"] = "normal";
    if ((observation.kind === "admission" || observation.kind === "input") && observation.owner?.turnId) {
      const owner = observation.owner;
      chat = this.ensureChat(chatId);
      if (chat.closed.has(owner.turnId) || chat.fenced.has(owner.turnId)) {
        if (turnId && turnId !== owner.turnId && chat.turns.get(turnId)?.delivery?.role === "candidate-owner") {
          this.reject(chatId, turnId, effects);
        }
        forward = "without-owner";
      } else {
        if (turnId && turnId !== owner.turnId && chat.turns.get(turnId)?.delivery?.role === "candidate-owner") {
          this.settle(chatId, turnId, effects);
        }
        if (chat.latestTurnId !== owner.turnId) this.advance(chat, owner.turnId);
        if (typeof owner.startedAt === "number") {
          this.ensureTurn(chat, owner.turnId).startedAt = owner.startedAt;
          chat.effectiveStartedAt = owner.startedAt;
        }
      }
    }

    if (observation.kind === "admission") {
      if (turnId) this.accept(chat, turnId);
      return { forward, effects };
    }
    if (observation.systemCommand) return { forward, effects };
    if (observation.kind === "rejection") {
      if (turnId) this.reject(chatId, turnId, effects);
      return { forward, effects };
    }
    if (turnId) this.accept(chat, turnId);

    if (observation.kind === "recovery") {
      if (!observation.active) {
        if (!turnId || !chat?.latestTurnId || turnId === chat.latestTurnId) {
          effects.push(...this.applyCommand({ kind: "local-stop", chatId }));
        }
      } else {
        chat = this.ensureChat(chatId);
        if (turnId) this.advance(chat, turnId);
        else chat.anonymousActive = true;
      }
      return { forward, effects };
    }
    if (observation.kind === "activity" && !this.view(chatId).active
      && (turnId !== null || !chat?.latestTurnId || !this.isCompleted({ chatId, turnId: chat.latestTurnId }))) {
      chat = this.ensureChat(chatId);
      this.advance(chat, turnId);
      chat.anonymousActive = turnId === null;
    }

    const completion = observation.kind === "completed"
      || (observation.kind === "status" && observation.activity === "idle");
    const superseded = completion && chat?.latestTurnId != null && turnId !== chat.latestTurnId;
    if (observation.kind === "status" && observation.activity === "running" && typeof observation.startedAt === "number") {
      chat = this.ensureChat(chatId);
      this.advance(chat, turnId);
      if (turnId) this.ensureTurn(chat, turnId).startedAt = observation.startedAt;
      chat.effectiveStartedAt = observation.startedAt;
    } else if (observation.kind === "status" || observation.kind === "completed") {
      // A running status without a numeric start time also settles the turn.
      chat = this.ensureChat(chatId);
      if (turnId) this.rememberClosed(chat, turnId);
      if (turnId) this.settle(chatId, turnId, effects);
      if (chat.latestTurnId === null || turnId === chat.latestTurnId) {
        chat.anonymousActive = false;
        chat.effectiveStartedAt = null;
      }
      effects.push({ kind: "completion", chatId });
    }
    return { forward: superseded ? "drop" : forward, effects };
  }

  /** Check snapshot eligibility without recording fences or producing effects. */
  canApplyCanonical(request: CanonicalRequest): boolean {
    const chat = this.chats.get(request.chatId);
    const completed = new Set(chat?.fenced);
    for (const turnId of request.completedTurnIds) {
      if (turnId) completed.add(turnId);
    }
    const observed = new Set(request.snapshot?.observedTurnIds.filter((turnId) => turnId.length > 0) ?? []);
    const willSettle = (turnId: string) => this.canonicalTurnWillSettle(chat, turnId, completed, observed, request.snapshot);
    const latestTurnId = chat?.latestTurnId ?? null;
    const latestIsRepresented = latestTurnId !== null && (
      completed.has(latestTurnId) || (observed.has(latestTurnId) && willSettle(latestTurnId))
    );
    if (chat) {
      for (const [turnId, turn] of chat.turns) {
        if (turn.openOrder !== null && !willSettle(turnId)) return false;
      }
      if (chat.effectiveStartedAt !== null && latestTurnId === null && (!request.snapshot || request.snapshot.hasPendingToolCalls)) {
        return false;
      }
    }
    return (chat?.generation ?? 0) === request.generation || latestIsRepresented;
  }

  applyCanonical(request: CanonicalRequest): { accepted: boolean; effects: readonly RunEffect[] } {
    const before = this.view(request.chatId);
    const result = this.applyCanonicalSnapshot(request);
    return { ...result, effects: this.withRunStatus(request.chatId, before, result.effects) };
  }

  private applyCanonicalSnapshot(request: CanonicalRequest): { accepted: boolean; effects: readonly RunEffect[] } {
    const { chatId, snapshot } = request;
    const effects: RunEffect[] = [];
    this.fence(chatId, request.completedTurnIds, effects);
    if (!this.canApplyCanonical({ ...request, completedTurnIds: [] })) return { accepted: false, effects };

    const chat = this.chats.get(chatId);
    if (!chat) return { accepted: true, effects };
    const completed = chat.fenced;
    const observed = new Set(snapshot?.observedTurnIds.filter((turnId) => turnId.length > 0) ?? []);
    for (const turnId of this.openTurnIds(chat)) {
      if (!this.canonicalTurnWillSettle(chat, turnId, completed, observed, snapshot)) continue;
      this.rememberClosed(chat, turnId);
      this.settle(chatId, turnId, effects);
    }
    for (const [turnId, turn] of chat.turns) {
      if (turn.delivery?.role !== "supplement") continue;
      if (!this.canonicalTurnWillSettle(chat, turnId, completed, observed, snapshot)) continue;
      turn.delivery = null;
      this.removeEmptyTurn(chat, turnId, turn);
      effects.push({ kind: "discard-send", chatId, turnId });
    }
    chat.anonymousActive = false;
    chat.effectiveStartedAt = null;
    return { accepted: true, effects };
  }

  private ensureChat(chatId: string): ChatRecord {
    let chat = this.chats.get(chatId);
    if (!chat) {
      chat = {
        generation: 0,
        latestTurnId: null,
        effectiveStartedAt: null,
        anonymousActive: false,
        turns: new Map(),
        closed: new Set(),
        fenced: new Set(),
      };
      this.chats.set(chatId, chat);
    }
    return chat;
  }

  private ensureTurn(chat: ChatRecord, turnId: string): TurnRecord {
    let turn = chat.turns.get(turnId);
    if (!turn) {
      turn = { delivery: null, openOrder: null, startedAt: null };
      chat.turns.set(turnId, turn);
    }
    return turn;
  }

  private advance(chat: ChatRecord, turnId: string | null): void {
    chat.generation += 1;
    chat.latestTurnId = turnId || null;
    if (turnId) {
      chat.anonymousActive = false;
      const turn = this.ensureTurn(chat, turnId);
      if (turn.openOrder === null) turn.openOrder = chat.generation;
    }
  }

  private hasOpenTurn(chat: ChatRecord | undefined): boolean {
    if (!chat) return false;
    for (const turn of chat.turns.values()) {
      if (turn.openOrder !== null) return true;
    }
    return false;
  }

  private openTurnIds(chat: ChatRecord): string[] {
    const turns: { turnId: string; order: number }[] = [];
    for (const [turnId, turn] of chat.turns) {
      if (turn.openOrder !== null) turns.push({ turnId, order: turn.openOrder });
    }
    return turns.sort((left, right) => left.order - right.order).map(({ turnId }) => turnId);
  }

  private accept(chat: ChatRecord | undefined, turnId: string): void {
    const turn = chat?.turns.get(turnId);
    if (!chat || !turn?.delivery) return;
    if (turn.delivery.role === "supplement") {
      turn.delivery = null;
      this.removeEmptyTurn(chat, turnId, turn);
    } else if (turn.delivery.phase !== "accepted") {
      turn.delivery = { phase: "accepted", role: "candidate-owner" };
    }
  }

  private removeEmptyTurn(chat: ChatRecord, turnId: string, turn: TurnRecord): void {
    if (turn.delivery === null && turn.openOrder === null && turn.startedAt === null) chat.turns.delete(turnId);
  }

  private settle(chatId: string, turnId: string, effects: RunEffect[]): void {
    this.chats.get(chatId)?.turns.delete(turnId);
    effects.push({ kind: "discard-send", chatId, turnId });
  }

  private reject(chatId: string, turnId: string, effects: RunEffect[]): void {
    if (!turnId) return;
    const chat = this.chats.get(chatId);
    const rejectedLatest = chat?.latestTurnId === turnId;
    this.settle(chatId, turnId, effects);
    effects.push({ kind: "prune-inbound", chatId, turnIds: [turnId] });
    if (!chat || !rejectedLatest) return;
    let previous: { turnId: string; order: number; startedAt: number | null } | null = null;
    for (const [id, turn] of chat.turns) {
      if (turn.openOrder !== null && (previous === null || turn.openOrder > previous.order)) {
        previous = { turnId: id, order: turn.openOrder, startedAt: turn.startedAt };
      }
    }
    chat.latestTurnId = previous?.turnId ?? null;
    chat.effectiveStartedAt = previous?.startedAt ?? null;
  }

  private rememberClosed(chat: ChatRecord, turnId: string): void {
    chat.closed.add(turnId);
    this.trimTerminalSet(chat.closed);
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
    chat: ChatRecord | undefined,
    turnId: string,
    completed: ReadonlySet<string>,
    observed: ReadonlySet<string>,
    snapshot?: CanonicalRunSnapshot,
  ): boolean {
    if (completed.has(turnId)) return true;
    const delivery = chat?.turns.get(turnId)?.delivery;
    if (snapshot?.completionIdsProvided && delivery?.role !== "supplement") return false;
    if (!snapshot || snapshot.activeTurnId === turnId || snapshot.hasPendingToolCalls) return false;
    return observed.has(turnId) || delivery?.phase === "unknown" || delivery?.phase === "accepted";
  }
}
