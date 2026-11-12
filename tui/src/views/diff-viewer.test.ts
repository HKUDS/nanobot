import { describe, expect, test } from "bun:test"

import { latestTurnFileEdits, mergeFileEdits } from "./diff-viewer"

describe("DiffViewer projection", () => {
  test("merges lifecycle frames without losing the final unified patch", () => {
    const edits = mergeFileEdits(
      [{ call_id: "edit-1", tool: "edit_file", path: "src/app.ts", status: "editing" }],
      [{
        call_id: "edit-1",
        tool: "edit_file",
        path: "src/app.ts",
        status: "done",
        added: 2,
        deleted: 1,
        diff: { format: "unified", text: "--- a/src/app.ts\n+++ b/src/app.ts" },
      }],
    )

    expect(edits).toHaveLength(1)
    expect(edits[0]?.status).toBe("done")
    expect(edits[0]?.diff?.text).toContain("+++ b/src/app.ts")
  })

  test("uses only the newest user turn instead of leaking an older diff", () => {
    const oldEdit = {
      call_id: "old",
      tool: "edit_file",
      path: "old.ts",
      status: "done",
      diff: { format: "unified", text: "old" },
    }
    expect(latestTurnFileEdits([
      { role: "user", content: "edit the old file" },
      { role: "activity", content: "", fileEdits: [oldEdit] },
      { role: "assistant", content: "done" },
      { role: "user", content: "just explain it" },
      { role: "assistant", content: "explained" },
    ])).toEqual([])

    expect(latestTurnFileEdits([
      { role: "user", content: "edit the old file" },
      { role: "activity", content: "", fileEdits: [oldEdit] },
      { role: "assistant", content: "done" },
    ])).toEqual([oldEdit])
  })
})
