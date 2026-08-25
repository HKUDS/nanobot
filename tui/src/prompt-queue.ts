import type { MessageOptions } from "./protocol"

export interface QueuedPrompt {
  content: string
  options: MessageOptions
}

/** Owns prompts that should start after the active turn finishes. */
export class PromptQueue {
  private prompts: QueuedPrompt[] = []

  get length(): number {
    return this.prompts.length
  }

  enqueue(prompt: QueuedPrompt): void {
    this.prompts.push(prompt)
  }

  takeLast(): QueuedPrompt | null {
    return this.prompts.pop() ?? null
  }

  takeFollowUp(): QueuedPrompt | null {
    return this.prompts.shift() ?? null
  }

  snapshot(): readonly QueuedPrompt[] {
    return this.prompts
  }

  restore(): QueuedPrompt[] {
    const prompts = this.prompts
    this.prompts = []
    return prompts
  }

  clear(): void {
    this.prompts = []
  }
}
