import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ContextInspector } from "@/components/thread/ContextInspector";
import type { ContextGraph, ContextSnapshot } from "@/lib/types";

// Painting is explicit here so slow rendering can be exercised without a canvas.
vi.mock("@/components/thread/ContextGraphScene", () => ({
  ContextGraphScene: ({ graph, onReady }: { graph: ContextGraph; onReady: (graph: ContextGraph) => void }) =>
    <button onClick={() => onReady(graph)}>Paint snapshot</button>,
}));
afterEach(() => vi.useRealTimers());

async function start(count: number) {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "performance"] });
  const snapshots: ContextSnapshot[] = Array.from({ length: count }, (_, index) => ({
    id: String(index), contextWindowTokens: 10000,
    usage: { prompt_tokens: (index + 1) * 100 }, graph: { nodes: [], edges: [] },
  }));
  await act(async () => {
    render(<ContextInspector context={null} rounds={[]} snapshots={snapshots} />);
    await vi.dynamicImportSettled();
  });
  const play = screen.getByRole("button", { name: "Play context history" });
  fireEvent.click(play);
  return play;
}
const paint = () => fireEvent.click(screen.getByRole("button", { name: "Paint snapshot" }));
const progress = () => screen.getByRole("progressbar").getAttribute("aria-valuenow");

it("replays short histories at five steps per second and can restart", async () => {
  const play = await start(2);
  expect(play).toBeDisabled();
  expect(progress()).toBe("1");
  paint();
  act(() => vi.advanceTimersByTime(200));
  expect(progress()).toBe("2");
  paint();
  act(() => vi.advanceTimersByTime(200));
  expect(play).toBeEnabled();
  fireEvent.click(play);
  expect(progress()).toBe("1");
});

it("speeds up longer histories without dropping unpainted snapshots", async () => {
  await start(400);
  // A delayed first paint does not skip intermediate request states.
  act(() => vi.advanceTimersByTime(350));
  expect(progress()).toBe("1");
  paint();
  act(() => vi.advanceTimersByTime(1));
  expect(progress()).toBe("2");
  paint();
  act(() => vi.advanceTimersByTime(1));
  expect(progress()).toBe("3");
  paint();
  act(() => vi.advanceTimersByTime(1));
  expect(progress()).toBe("4");
  paint();
  // The fourth deadline remains at 400ms, not 100ms after its late paint.
  act(() => vi.advanceTimersByTime(47));
  expect(progress()).toBe("5");
});

it("keeps replay usage frame-local and restores the latest measurement when playback ends", async () => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "performance"] });
  const snapshots: ContextSnapshot[] = [
    { id: "measured", contextWindowTokens: 10000, usage: { prompt_tokens: 1000, cached_tokens: 500 }, graph: { nodes: [], edges: [] } },
    { id: "pending", contextWindowTokens: 20000, graph: { nodes: [], edges: [] } },
  ];
  await act(async () => {
    render(<ContextInspector context={{ contextTokens: 1000, contextWindowTokens: 10000 }}
      rounds={[{ inputTokens: 1000, cachedTokens: 500 }]} snapshots={snapshots} />);
    await vi.dynamicImportSettled();
  });
  expect(progress()).toBe("10");
  const play = screen.getByRole("button", { name: "Play context history" });
  fireEvent.click(play);
  expect(progress()).toBe("10");
  paint();
  act(() => vi.advanceTimersByTime(200));
  expect(progress()).toBeNull();
  fireEvent.pointerEnter(screen.getByRole("progressbar").parentElement!.parentElement!);
  expect(screen.getByText("— / 20k")).toBeVisible();
  expect(screen.queryByText("50%")).not.toBeInTheDocument();
  paint();
  act(() => vi.advanceTimersByTime(200));
  expect(play).toBeEnabled();
  expect(progress()).toBe("10");
  expect(screen.getByText("1k / 10k")).toBeVisible();
  expect(screen.getByText("50%")).toBeVisible();
});
