import { afterEach, expect, test } from "bun:test"
import { fetchHistory, fetchSessionUsage } from "."

const originalFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = originalFetch })

function respond(events: Array<Record<string, unknown>>, page = {}) {
  globalThis.fetch = Object.assign(async () => Response.json({
    schemaVersion: 3, projection: "events",
    events: events.map((event) => ({ chat_id: "chat", turn_id: "turn", ...event })),
    page,
  }), { preconnect: originalFetch.preconnect })
}

test("restores canonical event history, media, tools, file edits and absolute fork indices", async () => {
  const media = [{ kind: "image" as const, url: "/api/media/image", name: "shot.png" }]
  const tools = [{ phase: "end", call_id: "read", name: "read_file" }]
  const edits = [{ tool: "edit_file", path: "a.py", added: 1 }]
  respond([
    { event: "user_message", starts_turn: true, text: "question", media_urls: media, projection_id: "user" },
    { event: "user_message", starts_turn: true, text: "question", media_urls: media, projection_id: "user" },
    { event: "reasoning_delta", text: "private reasoning" },
    { event: "reasoning_end", text: "private reasoning" },
    { event: "message", kind: "reasoning", text: "private reasoning" },
    { event: "message", kind: "tool_hint", text: "read_file", tool_events: tools },
    { event: "file_edit", edits },
    { event: "delta", text: "partial" },
    { event: "stream_end", text: "answer" },
    { event: "message", text: "answer" },
    { event: "turn_end" },
  ], { has_more_before: true, before_cursor: "older", user_message_offset: 7 })
  expect(await fetchHistory("http://fixture", "token", "chat")).toEqual({
    messages: [
      { role: "user", content: "question", media, turnId: "turn" },
      { role: "activity", content: "read_file", toolEvents: tools },
      { role: "activity", content: "", fileEdits: edits },
      { role: "assistant", content: "answer", forkIndex: 8 },
    ],
    hasMoreBefore: true, beforeCursor: "older", userMessageOffset: 7,
  })
})

test("keeps distinct answer segments and resumes an unfinished stream", async () => {
  respond([
    { event: "user_message", starts_turn: true, text: "question" },
    { event: "delta", text: "first" },
    { event: "stream_end", text: "first" },
    { event: "message", kind: "progress", text: "tool summary", trace_detail: { ref: "trace" } },
    { event: "stream_end", text: "second", resuming: true, merge_next: true },
    { event: "delta", text: " continued" },
    { event: "stream_end" },
    { event: "turn_end" },
    { event: "user_message", starts_turn: true, text: "next", turn_id: "next" },
    { event: "delta", text: "unfinished", turn_id: "next" },
  ])
  const history = await fetchHistory("http://fixture", "token", "chat")
  expect(history.messages.map((row) => row.content)).toEqual([
    "question", "first", "tool summary", "second continued", "next", "unfinished",
  ])
})

test("recovers usage from turn_end and respects successful compaction boundaries", async () => {
  const rounds = Array.from({ length: 10 }, (_, i) => ({ prompt_tokens: (i + 1) * 10 }))
  const completed = {
    event: "turn_end", usage: { context_tokens: 100 },
    context_window_tokens: 1000, round_usages: rounds,
  }
  respond([{ event: "stream_end", text: "answer" }, completed])
  expect(await fetchSessionUsage("http://fixture", "token", "chat")).toEqual({
    context: { tokens: 100, windowTokens: 1000 }, rounds: rounds.slice(-8),
  })
  const compacted = { event: "context_compaction", compaction_id: "compact", phase: "succeeded" }
  respond([completed, compacted, { event: "delta", text: "still running", turn_id: "next" }])
  expect(await fetchSessionUsage("http://fixture", "token", "chat")).toEqual({
    context: null, rounds: rounds.slice(-8),
  })
  expect((await fetchHistory("http://fixture", "token", "chat")).messages[0]).toEqual({
    role: "activity", content: "", compaction: { id: "compact", phase: "succeeded" },
  })
  respond([completed, compacted, { ...completed, turn_id: "next", usage: { context_tokens: 20 }, round_usages: [] }])
  expect((await fetchSessionUsage("http://fixture", "token", "chat")).context)
    .toEqual({ tokens: 20, windowTokens: 1000 })
})

test("rejects unsupported successful responses and malformed events instead of showing empty history", async () => {
  for (const payload of [
    {}, { schemaVersion: 3, messages: [] },
    { schemaVersion: 3, projection: "events", events: null },
    { schemaVersion: 3, projection: "future", messages: [] },
  ]) {
    globalThis.fetch = Object.assign(async () => Response.json(payload), { preconnect: originalFetch.preconnect })
    await expect(fetchHistory("http://fixture", "token", "chat")).rejects.toThrow("history response")
  }
  for (const event of [
    { event: "user_message", text: 42 },
    { event: "stream_end", text: "answer", turn_id: 42 },
    { event: "turn_end", context_window_tokens: "64000" },
  ]) {
    respond([event])
    await expect(fetchHistory("http://fixture", "token", "chat")).rejects.toThrow("Invalid history event")
  }
  respond([])
  expect((await fetchHistory("http://fixture", "token", "chat")).messages).toEqual([])
})
