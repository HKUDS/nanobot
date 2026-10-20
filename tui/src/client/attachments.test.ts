import { afterEach, expect, test } from "bun:test"
import { pastedFilePath, uploadAttachments } from "../../../packages/client-events/attachments"

const originalFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = originalFetch })

test("recognizes whole paths across native platforms without consuming prose, code, URLs or fakepath", () => {
  for (const [text, path] of [
    ['"C:\\project\\my clip.mp4"', "C:\\project\\my clip.mp4"],
    ["'./clips/my clip.webm'", "./clips/my clip.webm"],
    ["/tmp/my clip.mov", "/tmp/my clip.mov"], ["clips/clip.mp4", "clips/clip.mp4"],
    ["clip.mp4", "clip.mp4"],
  ]) expect(pastedFilePath(text!)).toBe(path!)
  for (const text of ["please read ./file.txt", "const p = './file.txt'", "https://host/clip.mp4",
    "C:\\fakepath\\clip.mp4", "line\n./clip.mp4", "`./clip.mp4`"]) expect(pastedFilePath(text)).toBeNull()
})

test("local paths send zero HTTP bodies; mixed batches upload only the required bytes", async () => {
  const requests: { url: string; body: Blob }[] = []
  globalThis.fetch = (async (url, init) => {
    requests.push({ url: String(url), body: init?.body as Blob })
    return Response.json({ reference: "upload-token" })
  }) as typeof fetch
  const local = { path: "/workspace/original.mp4", name: "original.mp4" }
  expect(await uploadAttachments([local], null, "ws://unused", () => true)).toEqual([local])
  expect(requests).toHaveLength(0)
  expect(await uploadAttachments([local, { data_url: "data:video/webm;base64,eA==", name: "upload.webm" }],
    { path: "/api/attachments", token: "private-capability" }, "ws://localhost:1234", () => true))
    .toEqual([local, { reference: "upload-token", name: "upload.webm" }])
  expect(requests).toHaveLength(1)
  expect(requests[0]?.url).toBe("http://localhost:1234/api/attachments")
  expect(await requests[0]?.body.text()).toBe("x")
})
