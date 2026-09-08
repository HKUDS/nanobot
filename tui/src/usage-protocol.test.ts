import { afterEach, describe, expect, mock, test } from "bun:test"

import { fetchSessionUsage } from "./protocol"

const apiUrl = "http://nanobot.test"
const apiToken = "usage-token"
const chatId = "usage/chat"
const threadPath = "/api/sessions/websocket%3Ausage%2Fchat/webui-thread?limit=120&direction=latest"
const originalFetch = globalThis.fetch

afterEach(() => { globalThis.fetch = originalFetch })

function mockResponses(...responses: Response[]) {
  const fetchMock = mock(async (_input: string | URL | Request, _init?: RequestInit) => {
    const response = responses.shift()
    if (!response) throw new Error("unexpected fetch")
    return response
  })
  globalThis.fetch = Object.assign(fetchMock, { preconnect: originalFetch.preconnect })
  return fetchMock
}

function thread(messages: Array<Record<string, unknown>>) {
  return Response.json({ messages })
}

function assistant(turnId: string, fields: Record<string, unknown>) {
  return { role: "assistant", content: "answer", turnId, ...fields }
}

describe("fetchSessionUsage", () => {
  test("returns the latest eight logical rounds chronologically across deduplicated turns", async () => {
    const rounds = Array.from({ length: 11 }, (_, index) => ({
      prompt_tokens: (index + 1) * 100,
      completion_tokens: index + 1,
    }))
    const fetchMock = mockResponses(thread([
      assistant("first", { id: "first-a", roundUsages: rounds.slice(0, 4) }),
      assistant("first", { id: "first-b", roundUsages: rounds.slice(0, 4) }),
      assistant("second", { id: "second-a", roundUsages: rounds.slice(4, 8) }),
      assistant("second", { id: "second-b", roundUsages: rounds.slice(4, 8) }),
      assistant("third", { roundUsages: rounds.slice(8) }),
    ]))

    expect(await fetchSessionUsage(apiUrl, apiToken, chatId)).toStrictEqual({
      context: null,
      rounds: rounds.slice(-8),
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0]?.[0]).toBe(`${apiUrl}${threadPath}`)
    expect(new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get("Authorization"))
      .toBe(`Bearer ${apiToken}`)
  })

  test("never substitutes aggregate prompt usage for missing or invalid round samples", async () => {
    mockResponses(thread([
      assistant("aggregate-only", { usage: { prompt_tokens: 90_000, total_tokens: 91_000 } }),
      assistant("invalid-rounds", {
        usage: { prompt_tokens: 80_000, context_tokens: 12 },
        contextWindowTokens: 1_000,
        roundUsages: [null, {}, { completion_tokens: 2 }, { prompt_tokens: 0 },
          { prompt_tokens: -1 }, { prompt_tokens: "500" }],
      }),
    ]))

    expect(await fetchSessionUsage(apiUrl, apiToken, chatId)).toStrictEqual({
      context: { tokens: 12, windowTokens: 1_000 },
      rounds: [],
    })
  })

  test("takes context and capacity from the latest message with context usage, not its neighbors", async () => {
    const round = { prompt_tokens: 70, context_tokens: 999 }
    mockResponses(thread([
      assistant("old", { usage: { context_tokens: 100 }, contextWindowTokens: 1_000 }),
      assistant("context", {
        usage: { prompt_tokens: 50_000, context_tokens: 250 },
        contextWindowTokens: 4_000,
      }),
      assistant("newer", {
        usage: { prompt_tokens: 90_000, total_tokens: 91_000 },
        contextWindowTokens: 100_000,
        roundUsages: [round],
      }),
    ]))

    expect(await fetchSessionUsage(apiUrl, apiToken, chatId)).toStrictEqual({
      context: { tokens: 250, windowTokens: 4_000 },
      rounds: [round],
    })
  })

  test("keeps usage-only and empty assistants while ignoring streaming, trace and non-assistant rows", async () => {
    const rounds = [{ prompt_tokens: 80 }, { prompt_tokens: 160, cached_tokens: 40 }]
    const noise = { usage: { context_tokens: 999 }, roundUsages: [{ prompt_tokens: 999 }] }
    mockResponses(thread([
      assistant("usage-only", { content: undefined, usage: { context_tokens: 80 }, roundUsages: [rounds[0]] }),
      assistant("empty", {
        content: "", usage: { context_tokens: 160 }, contextWindowTokens: 2_000,
        roundUsages: [rounds[1]],
      }),
      assistant("empty", { isStreaming: true, ...noise }),
      assistant("empty", { kind: "trace", ...noise }),
      { role: "tool", kind: "trace", ...noise },
      { role: "user", content: "question", ...noise },
    ]))

    expect(await fetchSessionUsage(apiUrl, apiToken, chatId)).toStrictEqual({
      context: { tokens: 160, windowTokens: 2_000 },
      rounds,
    })
  })

  test("successful compaction clears context but not bars, and later completed usage restores it", async () => {
    const oldRound = { prompt_tokens: 800 }
    const newRound = { prompt_tokens: 120 }
    const old = assistant("old", {
      usage: { context_tokens: 800 }, contextWindowTokens: 1_000, roundUsages: [oldRound],
    })
    const compaction = (phase: string) => ({
      role: "activity", kind: "compaction", compaction: { id: "compact-1", phase },
    })
    mockResponses(
      thread([old, compaction("started")]),
      thread([old, compaction("failed")]),
      thread([old, compaction("succeeded")]),
      thread([old, compaction("succeeded"), assistant("new", {
        usage: { context_tokens: 120 }, contextWindowTokens: 2_000, roundUsages: [newRound],
      })]),
    )

    for (const _phase of ["started", "failed"]) {
      expect(await fetchSessionUsage(apiUrl, apiToken, chatId)).toStrictEqual({
        context: { tokens: 800, windowTokens: 1_000 }, rounds: [oldRound],
      })
    }
    expect(await fetchSessionUsage(apiUrl, apiToken, chatId)).toStrictEqual({
      context: null, rounds: [oldRound],
    })
    expect(await fetchSessionUsage(apiUrl, apiToken, chatId)).toStrictEqual({
      context: { tokens: 120, windowTokens: 2_000 }, rounds: [oldRound, newRound],
    })
  })

  test("keeps zero context and missing versus zero cache without borrowing an invalid or missing capacity", async () => {
    const rounds = [
      { prompt_tokens: 40 },
      { prompt_tokens: 80, cached_tokens: 0, cache_write_tokens: 0 },
    ]
    for (const capacity of [undefined, 0, -1, "64000", null]) {
      mockResponses(thread([
        assistant("old", { usage: { context_tokens: 88 }, contextWindowTokens: 64_000 }),
        assistant("latest", {
          usage: { context_tokens: 0 }, contextWindowTokens: capacity, roundUsages: rounds,
        }),
      ]))

      expect(await fetchSessionUsage(apiUrl, apiToken, chatId)).toStrictEqual({
        context: { tokens: 0 }, rounds,
      })
    }
  })

  test("returns an empty snapshot on 404 or missing credentials without reauthentication", async () => {
    const fetchMock = mockResponses(new Response("missing", { status: 404 }))
    const reauthenticate = mock(async () => ({ apiUrl, apiToken: "fresh" }))
    const empty = { context: null, rounds: [] }

    expect(await fetchSessionUsage(apiUrl, apiToken, chatId, reauthenticate)).toStrictEqual(empty)
    expect(await fetchSessionUsage("", apiToken, chatId, reauthenticate)).toStrictEqual(empty)
    expect(await fetchSessionUsage(apiUrl, "", chatId, reauthenticate)).toStrictEqual(empty)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(reauthenticate).not.toHaveBeenCalled()
  })

  test("retries 401 once with the refreshed endpoint and token, retaining the thread request", async () => {
    const fresh = { apiUrl: "http://refreshed.test", apiToken: "fresh-token" }
    const fetchMock = mockResponses(
      new Response("expired", { status: 401 }),
      thread([assistant("fresh", { usage: { context_tokens: 42 } })]),
    )
    const reauthenticate = mock(async (_rejectedToken: string) => fresh)

    expect(await fetchSessionUsage(apiUrl, apiToken, chatId, reauthenticate)).toStrictEqual({
      context: { tokens: 42 }, rounds: [],
    })
    expect(reauthenticate).toHaveBeenCalledTimes(1)
    expect(reauthenticate).toHaveBeenCalledWith(apiToken)
    expect(fetchMock.mock.calls.map(([url, init]) => ({
      url: String(url), authorization: new Headers(init?.headers).get("Authorization"),
    }))).toEqual([
      { url: `${apiUrl}${threadPath}`, authorization: `Bearer ${apiToken}` },
      { url: `${fresh.apiUrl}${threadPath}`, authorization: `Bearer ${fresh.apiToken}` },
    ])
  })

  test("rejects 401 without reauthentication and stops after one rejected refresh", async () => {
    const fetchMock = mockResponses(...Array.from({ length: 3 }, () =>
      new Response("unauthorized", { status: 401 })))
    const reauthenticate = mock(async () => ({ apiUrl, apiToken: "still-rejected" }))

    await expect(fetchSessionUsage(apiUrl, apiToken, chatId)).rejects.toThrow("HTTP 401")
    await expect(fetchSessionUsage(apiUrl, apiToken, chatId, reauthenticate))
      .rejects.toThrow("HTTP 401")
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(reauthenticate).toHaveBeenCalledTimes(1)
    expect(reauthenticate).toHaveBeenCalledWith(apiToken)
  })
})
