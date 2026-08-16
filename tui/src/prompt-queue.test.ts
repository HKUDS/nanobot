import { describe, expect, test } from "bun:test"

import { PromptQueue } from "./prompt-queue"

const prompt = (content: string) => ({ content, options: {} })

describe("PromptQueue", () => {
  test("promotes the newest armed prompt to steering", () => {
    const queue = new PromptQueue()
    queue.enqueue(prompt("next one"))
    queue.enqueue(prompt("steer now"))

    expect(queue.takeSteering()?.content).toBe("steer now")
    expect(queue.takeSteering()).toBeNull()
    expect(queue.takeFollowUp()?.content).toBe("next one")
  })

  test("keeps follow-ups FIFO and restores unsent drafts", () => {
    const queue = new PromptQueue()
    queue.enqueue(prompt("first"))
    queue.enqueue(prompt("second"))

    expect(queue.takeFollowUp()?.content).toBe("first")
    expect(queue.restore().map(({ content }) => content)).toEqual(["second"])
    expect(queue.length).toBe(0)
  })
})
