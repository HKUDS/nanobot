import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { McpAppAttachments, McpAppCard, McpAppHostProvider } from "@/components/thread/activity/McpApp";
import type { WebUIMutationTransport } from "@/lib/api";
import type { UIMessage } from "@/lib/types";
import "@/i18n";

const message: UIMessage = {
  id: "tool-1", role: "tool", content: "Weather", createdAt: 1,
  toolEvents: [{ phase: "end", call_id: "call-1", name: "mcp_weather_dashboard", embeds: [
    { type: "mcp_app", app_id: "a".repeat(32), server_name: "Weather" },
  ] }],
};

describe("MCP App host", () => {
  it("leaves the text fallback usable when an optional host is unavailable", () => {
    render(<McpAppHostProvider host={null}><McpAppAttachments messages={[message]} /></McpAppHostProvider>);
    expect(screen.queryByRole("button", { name: "Open app" })).toBeNull();
  });

  it("deduplicates tool progress without executing or loading an app automatically", () => {
    const requestMutation = vi.fn();
    render(<McpAppHostProvider host={{ transport: { requestMutation }, sessionKey: "websocket:a" }}>
      <McpAppAttachments messages={[message, { ...message, id: "duplicate" }]} />
    </McpAppHostProvider>);
    expect(screen.getAllByRole("button", { name: "Open app" })).toHaveLength(1);
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("drops a late app payload after switching host or session", async () => {
    let complete: (value: unknown) => void = () => {};
    const request = new Promise((resolve) => { complete = resolve; });
    const first: WebUIMutationTransport = { requestMutation: () => request as Promise<never> };
    const second: WebUIMutationTransport = { requestMutation: vi.fn() };
    const props = { appId: "a".repeat(32), title: "Weather" };
    const view = render(<McpAppCard {...props} host={{ transport: first, sessionKey: "websocket:a" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Open app" }));
    view.rerender(<McpAppCard {...props} host={{ transport: second, sessionKey: "websocket:b" }} />);
    await act(async () => { complete({ html: "<p>Old host</p>", arguments: {}, result: { content: [] } }); });
    expect(view.container.querySelector("iframe")).toBeNull();
    expect(screen.queryByRole("button", { name: "Close app" })).toBeNull();
  });
});
