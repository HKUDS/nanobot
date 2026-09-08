import { expect, test } from "bun:test"
import { listenForSetupCallback } from "./setup-callback"

test("the local callback validates state, forwards once, and releases its listener", async () => {
  const callbacks: string[] = []
  const authorization = "https://example.test/authorize?redirect_uri=http%3A%2F%2Flocalhost%3A1455%2Fauth%2Fcallback&state=expected"
  const stop = listenForSetupCallback(authorization, (url) => callbacks.push(url))
  try {
    const invalid = await fetch("http://127.0.0.1:1455/auth/callback?state=wrong&code=private")
    expect(invalid.status).toBe(400)
    expect(callbacks).toHaveLength(0)
    const accepted = await fetch("http://127.0.0.1:1455/auth/callback?state=expected&code=private")
    expect(accepted.status).toBe(200)
    expect(await accepted.text()).not.toContain("private")
    await fetch("http://127.0.0.1:1455/auth/callback?state=expected&code=private")
    expect(callbacks).toEqual(["http://localhost:1455/auth/callback?state=expected&code=private"])
  } finally { stop() }
  const releaseAgain = listenForSetupCallback(authorization, () => {})
  releaseAgain()
})

test("untrusted redirect addresses cannot choose arbitrary bind ports", () => {
  expect(() => listenForSetupCallback("https://example.test/?redirect_uri=http://0.0.0.0:22/auth/callback&state=x", () => {})).toThrow()
})
