import { describe, expect, it } from "vitest";

import {
  canonicalToolTrace,
  mergeToolProgressTraceLines,
  mergeUniqueToolTraceLines,
} from "@/lib/tool-traces";

describe("tool trace identity", () => {
  it("treats persisted and live JSON formatting as the same call", () => {
    const persisted = 'web_search({"query": "site:linkedin.com/company Evomap startup", "count": 10})';
    const live = 'web_search({"query":"site:linkedin.com/company Evomap startup","count":10})';

    expect(canonicalToolTrace(persisted)).toBe(canonicalToolTrace(live));
    expect(mergeUniqueToolTraceLines([persisted], [live])).toEqual({
      traces: [persisted],
      added: false,
    });
  });

  it("keeps genuinely different calls separate", () => {
    const first = 'web_search({"query":"nanobot"})';
    const second = 'web_search({"query":"nanobot cloud"})';

    expect(mergeUniqueToolTraceLines([first], [second])).toEqual({
      traces: [first, second],
      added: true,
    });
  });

  it("replaces an empty streaming placeholder when hosted search arguments arrive", () => {
    expect(mergeToolProgressTraceLines(
      ["web_search()"],
      [{ phase: "start", call_id: "ws-1", name: "web_search", arguments: {} }],
      ['web_search({"query":"nanobot news"})'],
      [{
        phase: "end",
        call_id: "ws-1",
        name: "web_search",
        arguments: { query: "nanobot news" },
      }],
    )).toEqual(['web_search({"query":"nanobot news"})']);
  });
});
