import { expect, test } from "bun:test"

import { branchPoints } from "./branch-menu"

test("branch points preserve absolute user indices from paginated history", () => {
  expect(branchPoints([
    { role: "user", content: "question" },
    { role: "assistant", content: "  first\nreply  ", forkIndex: 11 },
    { role: "activity", content: "read_file" },
    { role: "assistant", content: "second", forkIndex: 12 },
  ])).toEqual([
    { beforeUserIndex: 11, preview: "first reply" },
    { beforeUserIndex: 12, preview: "second" },
  ])
})
