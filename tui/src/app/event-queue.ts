type EventTask<T> =
  | { kind: "event"; event: T }
  | { kind: "task"; run: () => void }

interface CooperativeEventQueueOptions<T> {
  dispatch(event: T): void
  paused(): boolean
  batchSize?: number
  batchBudgetMs?: number
}

/**
 * Drains gateway events cooperatively so repaint and terminal input stay responsive.
 * A caller-owned pause predicate keeps IME submission and history hydration atomic.
 */
export class CooperativeEventQueue<T> {
  private readonly dispatch: (event: T) => void
  private readonly paused: () => boolean
  private readonly batchSize: number
  private readonly batchBudgetMs: number
  private items: Array<EventTask<T>> = []
  private drain: ReturnType<typeof setImmediate> | null = null
  private idleTask: (() => void) | null = null

  constructor(options: CooperativeEventQueueOptions<T>) {
    this.dispatch = options.dispatch
    this.paused = options.paused
    this.batchSize = options.batchSize ?? 64
    this.batchBudgetMs = options.batchBudgetMs ?? 4
  }

  get length(): number {
    return this.items.length
  }

  enqueue(event: T): void {
    this.items.push({ kind: "event", event })
    this.resume()
  }

  enqueueTask(run: () => void): void {
    this.items.push({ kind: "task", run })
    this.resume()
  }

  prepend(events: readonly T[]): void {
    if (events.length) {
      this.items = [
        ...events.map((event): EventTask<T> => ({ kind: "event", event })),
        ...this.items,
      ]
    }
    this.resume()
  }

  whenIdle(task: () => void): void {
    this.idleTask = task
    this.resume()
  }

  resume(): void {
    if (this.drain || this.paused()) return
    if (!this.items.length) {
      const idleTask = this.idleTask
      this.idleTask = null
      idleTask?.()
      return
    }
    this.drain = setImmediate(() => this.drainBatch())
  }

  clear(): void {
    if (this.drain) clearImmediate(this.drain)
    this.drain = null
    this.items = []
    this.idleTask = null
  }

  private drainBatch(): void {
    this.drain = null
    const started = performance.now()
    let processed = 0
    // Keep each item in the queue while it runs. Handlers can then defer work
    // until every event already accepted by the transport has been projected.
    while (!this.paused() && processed < this.items.length) {
      const task = this.items[processed++]!
      if (task.kind === "task") task.run()
      else this.dispatch(task.event)
      if (processed >= this.batchSize || performance.now() - started >= this.batchBudgetMs) break
    }
    this.items.splice(0, processed)
    this.resume()
  }
}
