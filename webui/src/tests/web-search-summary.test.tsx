import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it } from "vitest";

import { AgentActivityCluster } from "@/components/thread/AgentActivityCluster";

const entrypoints = ["structured event", "trace-only"] as const;

afterEach(cleanup);

it.each(entrypoints)("keeps multiline search summaries single-line with full hover details (%s)", async (entrypoint) => {
  const domain = "research-and-development.platform.example.com";
  const query = "nanobot release notes\nweb search activity regression coverage";
  const args = { query: `site:${domain} ${query}` };
  const line = `web_search(${JSON.stringify(args)})`;
  const label = `Searched ${domain}`;
  render(
    <AgentActivityCluster
      messages={[{
        id: "t-multiline-search",
        role: "tool",
        kind: "trace",
        content: line,
        traces: [line],
        ...(entrypoint === "structured event" ? {
          toolEvents: [{
            phase: "end" as const,
            call_id: "call-multiline-search",
            name: "web_search",
            arguments: args,
            result: "No results found.",
          }],
        } : {}),
        createdAt: 1,
      }]}
      isTurnStreaming={false}
      hasBodyBelow={false}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /^Worked/ }));

  const activityLine = screen.getByTestId("activity-line");
  const searchLabel = within(activityLine).getByText(label).parentElement!;
  const detail = within(activityLine).getByText(query, { collapseWhitespace: false });
  expect(screen.getAllByTestId("activity-step")).toHaveLength(1);
  expect(activityLine).toHaveClass("overflow-hidden", "whitespace-nowrap");
  expect(detail).toHaveClass("min-w-0", "flex-1", "truncate");
  expect(detail).not.toHaveClass("whitespace-pre-line");
  expect(detail.textContent).toBe(query);
  expect(searchLabel).toHaveClass("truncate", "max-w-[50%]");
  expect(searchLabel).not.toHaveClass("max-w-[70%]");

  // Model truncation only; the browser check proves actual layout and available width.
  for (const text of [searchLabel, detail]) {
    Object.defineProperties(text, {
      scrollWidth: { value: 480 },
      clientWidth: { value: 120 },
    });
  }
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  await userEvent.hover(activityLine);
  const tooltip = await screen.findByRole("tooltip");
  expect(tooltip.textContent).toBe(`${label}\n${query}`);
  expect(tooltip.closest(".whitespace-pre-wrap")).toBeInTheDocument();
});

it.each(entrypoints)("does not reserve query width before a hosted search query arrives (%s)", (entrypoint) => {
  render(
    <AgentActivityCluster
      messages={[{
        id: "t-search-start",
        role: "tool",
        kind: "trace",
        content: "web_search()",
        traces: ["web_search()"],
        ...(entrypoint === "structured event" ? {
          toolEvents: [{ phase: "start" as const, call_id: "call-search-start", name: "web_search", arguments: {} }],
        } : {}),
        createdAt: 1,
      }]}
      isTurnStreaming
      hasBodyBelow={false}
    />,
  );
  const label = screen.getByText("Searching the web").parentElement!;
  expect(label).toHaveClass("flex-1");
  expect(label).not.toHaveClass("max-w-[50%]");
});
