import type { WebuiThreadPersistedPayload } from "@/lib/types";

export type HistoryPreviewMode = "slow" | "fast" | "pages" | "error";

export function historyPreviewPage(start: number): WebuiThreadPersistedPayload {
  return {
    schemaVersion: 3, projection: "events",
    events: Array.from({ length: 6 }, (_, offset) => {
      const index = start + offset;
      return [
        { event: "user_message" as const, chat_id: "boundary-a", projection_id: `u${index}`,
          text: `历史消息 ${index + 1}`, starts_turn: true },
        { event: "message" as const, chat_id: "boundary-a", projection_id: `a${index}`,
          text: "这是一段用于体验历史加载的示例内容。\n\n加载完成后，这条消息应保持在原来的阅读位置；九宫格不应提前收起。" },
      ];
    }).flat(),
    page: { before_cursor: start ? String(start) : null, has_more_before: start > 0,
      user_message_offset: start, has_more_after: false },
  };
}

// Only the opt-in browser fixture uses simulated data; production requests are untouched.
export function installHistoryBoundaryPreviewApi(mode: HistoryPreviewMode) {
  const originalFetch = window.fetch.bind(window);
  let failed = false;
  window.fetch = async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : String(input), location.href);
    if (url.origin !== location.origin || !url.pathname.startsWith("/api/")) return originalFetch(input, init);
    if (url.pathname.endsWith("/prompts")) return Response.json({ prompts: [] });
    if (!url.pathname.endsWith("/webui-thread")) return Response.json({});
    const cursor = url.searchParams.get("before");
    if (!cursor) return Response.json(historyPreviewPage(12));
    const continuation = cursor.startsWith("content-");
    const start = Number(cursor.replace("content-", ""));
    await new Promise((resolve) => setTimeout(resolve, mode === "fast" ? 30 : 1500));
    if (mode === "error" && !failed) {
      failed = true;
      return new Response("Preview: history unavailable", { status: 503 });
    }
    if (mode === "pages" && !continuation) {
      return Response.json({ schemaVersion: 3, projection: "events", events: [],
        page: { before_cursor: `content-${start}`, has_more_before: true, user_message_offset: start } });
    }
    return Response.json(historyPreviewPage(Math.max(0, start - 6)));
  };
}
