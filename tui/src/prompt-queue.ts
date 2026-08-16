import type { MessageOptions } from "./protocol"

export interface QueuedPrompt {
  content: string
  options: MessageOptions
}

/** Owns the difference between steering the active turn and starting the next one. */
export class PromptQueue {
  private prompts: QueuedPrompt[] = []
  private armed = false

  get length(): number {
    return this.prompts.length
  }

  enqueue(prompt: QueuedPrompt): void {
    this.prompts.push(prompt)
    this.armed = true
  }

  /** A second Enter immediately promotes the newest queued prompt to steering. */
  takeSteering(): QueuedPrompt | null {
    if (!this.armed) return null
    this.armed = false
    return this.prompts.pop() ?? null
  }

  takeFollowUp(): QueuedPrompt | null {
    this.armed = false
    return this.prompts.shift() ?? null
  }

  restore(): QueuedPrompt[] {
    const prompts = this.prompts
    this.prompts = []
    this.armed = false
    return prompts
  }

  clear(): void {
    this.prompts = []
    this.armed = false
  }
}
