import { afterEach, describe, expect, mock, test } from "bun:test"

import { fetchSessionUsage } from "./api"

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

function thread(events: Array<Record<string, unknown>>) {
  return Response.json({
    schemaVersion: 3, projection: "events",
    events: events.map((event) => ({ chat_id: chatId, ...event })),
  })
}

function completed(turnId: string, fields: Record<string, unknown>) {
  return { event: "turn_end", turn_id: turnId, ...fields }
}

describe("fetchSessionUsage", () => {
  test("returns the latest eight logical rounds chronologically across deduplicated turns", async () => {
    const rounds = Array.from({ length: 11 }, (_, index) => ({
      prompt_tokens: (index + 1) * 100,
      completion_tokens: index + 1,
    }))
    const fetchMock = mockResponses(thread([
      completed("first", { projection_id: "first-a", round_usages: rounds.slice(0, 4) }),
      completed("first", { projection_id: "first-b", round_usages: rounds.slice(0, 4) }),
      completed("second", { projection_id: "second-a", round_usages: rounds.slice(4, 8) }),
      completed("second", { projection_id: "second-b", round_usages: rounds.slice(4, 8) }),
      completed("third", { round_usages: rounds.slice(8) }),
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
      completed("aggregate-only", { usage: { prompt_tokens: 90_000, total_tokens: 91_000 } }),
      completed("invalid-rounds", {
        usage: { prompt_tokens: 80_000, context_tokens: 12 },
        context_window_tokens: 1_000,
        round_usages: [null, {}, { completion_tokens: 2 }, { prompt_tokens: 0 },
          { prompt_tokens: -1 }, { prompt_tokens: "500" }],
      }),
    ]))

    expect(await fetchSessionUsage(apiUrl, apiToken, chatId)).toStrictEqual({
      context: { tokens: 12, windowTokens: 1_000 },
      rounds: [],
    })
  })

  test("takes context and capacity from the latest completed turn with context usage", async () => {
    const round = { prompt_tokens: 70, context_tokens: 999 }
    mockResponses(thread([
      completed("old", { usage: { context_tokens: 100 }, context_window_tokens: 1_000 }),
      completed("context", {
        usage: { prompt_tokens: 50_000, context_tokens: 250 },
        context_window_tokens: 4_000,
      }),
      completed("newer", {
        usage: { prompt_tokens: 90_000, total_tokens: 91_000 },
        context_window_tokens: 100_000,
        round_usages: [round],
      }),
    ]))

    expect(await fetchSessionUsage(apiUrl, apiToken, chatId)).toStrictEqual({
      context: { tokens: 250, windowTokens: 4_000 },
      rounds: [round],
    })
  })

  test("reads completed usage while ignoring unfinished streams, tools and user events", async () => {
    const rounds = [{ prompt_tokens: 80 }, { prompt_tokens: 160, cached_tokens: 40 }]
    const noise = { usage: { context_tokens: 999 }, round_usages: [{ prompt_tokens: 999 }] }
    mockResponses(thread([
      completed("usage-only", { usage: { context_tokens: 80 }, round_usages: [rounds[0]] }),
      completed("empty", {
        usage: { context_tokens: 160 }, context_window_tokens: 2_000,
        round_usages: [rounds[1]],
      }),
      { event: "delta", text: "still running", ...noise },
      { event: "stream_end", text: "unfinished turn", ...noise },
      { event: "message", kind: "tool_hint", text: "tool", ...noise },
      { event: "user_message", starts_turn: true, text: "question", ...noise },
    ]))

    expect(await fetchSessionUsage(apiUrl, apiToken, chatId)).toStrictEqual({
      context: { tokens: 160, windowTokens: 2_000 },
      rounds,
    })
  })

  test("successful compaction clears context but not bars, and later completed usage restores it", async () => {
    const oldRound = { prompt_tokens: 800 }
    const newRound = { prompt_tokens: 120 }
    const old = completed("old", {
      usage: { context_tokens: 800 }, context_window_tokens: 1_000, round_usages: [oldRound],
    })
    const compaction = (phase: string) => ({
      event: "context_compaction", compaction_id: "compact-1", phase,
    })
    mockResponses(
      thread([old, compaction("started")]),
      thread([old, compaction("failed")]),
      thread([old, compaction("succeeded")]),
      thread([old, compaction("succeeded"), completed("new", {
        usage: { context_tokens: 120 }, context_window_tokens: 2_000, round_usages: [newRound],
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
    for (const capacity of [undefined, 0, -1]) {
      mockResponses(thread([
        completed("old", { usage: { context_tokens: 88 }, context_window_tokens: 64_000 }),
        completed("latest", {
          usage: { context_tokens: 0 }, context_window_tokens: capacity, round_usages: rounds,
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
      thread([completed("fresh", { usage: { context_tokens: 42 } })]),
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

  test("does not issue a request when already aborted", async () => {
    const controller = new AbortController()
    controller.abort()
    const fetchMock = mockResponses()
    const reauthenticate = mock(async () => ({ apiUrl, apiToken: "fresh" }))
    await expect(fetchSessionUsage(apiUrl, apiToken, chatId, reauthenticate, controller.signal))
      .rejects.toHaveProperty("name", "AbortError")
    expect(fetchMock).not.toHaveBeenCalled()
    expect(reauthenticate).not.toHaveBeenCalled()
  })

  test("preserves the abort signal through authenticated retry", async () => {
    const controller = new AbortController()
    const fetchMock = mockResponses(new Response(null, { status: 401 }), thread([]))
    const reauthenticate = mock(async () => ({ apiUrl, apiToken: "fresh" }))
    expect(await fetchSessionUsage(apiUrl, apiToken, chatId, reauthenticate, controller.signal))
      .toEqual({ context: null, rounds: [] })
    expect(fetchMock.mock.calls.map(([, init]) => init?.signal))
      .toEqual([controller.signal, controller.signal])
  })

  test("does not reauthenticate a request cancelled before its 401 arrives", async () => {
    const controller = new AbortController()
    const fetchMock = mockResponses(new Response(null, { status: 401 }))
    const reauthenticate = mock(async () => ({ apiUrl, apiToken: "fresh" }))
    const result = fetchSessionUsage(apiUrl, apiToken, chatId, reauthenticate, controller.signal)
    controller.abort()
    await expect(result).rejects.toHaveProperty("name", "AbortError")
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(reauthenticate).not.toHaveBeenCalled()
  })

  test("does not retry when cancelled during shared reauthentication", async () => {
    const controller = new AbortController()
    const fetchMock = mockResponses(new Response(null, { status: 401 }))
    const reauthenticate = mock(async () => {
      controller.abort()
      return { apiUrl, apiToken: "fresh" }
    })
    await expect(fetchSessionUsage(apiUrl, apiToken, chatId, reauthenticate, controller.signal))
      .rejects.toHaveProperty("name", "AbortError")
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(reauthenticate).toHaveBeenCalledTimes(1)
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
