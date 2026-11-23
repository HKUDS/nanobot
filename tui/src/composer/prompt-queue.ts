import type { MessageOptions } from "../client"

export interface QueuedPrompt {
  content: string
  displayContent?: string
  options: MessageOptions
}

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
