import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { BackgroundProvider, useBackground } from "@/providers/BackgroundProvider";

const state = vi.hoisted(() => ({
  change: null as (() => void) | null,
  ready: null as (() => void) | null,
  client: {
    onBackgroundChange: (handler: () => void) => { state.change = handler; return () => { state.change = null; }; },
    onReady: (handler: () => void) => { state.ready = handler; return () => { state.ready = null; }; },
    requestMutation: vi.fn().mockResolvedValue({}),
    uploadBackground: vi.fn().mockResolvedValue(undefined),
  },
}));
vi.mock("@/providers/ClientProvider", () => ({ useClient: () => ({ client: state.client, token: "test" }) }));
vi.mock("@/hooks/useObjectUrl", () => ({ useObjectUrl: () => null }));

function Probe() {
  const background = useBackground()!;
  return <><span data-testid="style">{background.blur}/{background.veil}</span>
    <span data-testid="state">{background.ready ? "ready" : background.loadError ? "error" : "loading"}</span>
    <button onClick={background.retry}>Retry</button>
    <button onClick={() => void background.setStyle(10, 50)}>Save</button></>;
}

afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

it("does not let a delayed initial read overwrite a saved style", async () => {
  let resolveStyle!: (response: Response) => void;
  const style = new Promise<Response>(resolve => { resolveStyle = resolve; });
  vi.stubGlobal("fetch", vi.fn((url: string) => url.endsWith("background-style")
    ? style : Promise.resolve(new Response(null, { status: 404 }))));
  render(<BackgroundProvider><Probe /></BackgroundProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(screen.getByTestId("style").textContent).toBe("10/50"));
  await act(async () => { resolveStyle(Response.json({ blur: 2, veil: 26 })); await style; });
  expect(screen.getByTestId("style").textContent).toBe("10/50");
});

it("reloads shared state when another client changes it", async () => {
  let value = { blur: 2, veil: 26 };
  vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(url.endsWith("background-style")
    ? Response.json(value) : new Response(null, { status: 404 }))));
  render(<BackgroundProvider><Probe /></BackgroundProvider>);
  await waitFor(() => expect(screen.getByTestId("style").textContent).toBe("2/26"));
  value = { blur: 8, veil: 45 };
  act(() => state.change?.());
  await waitFor(() => expect(screen.getByTestId("style").textContent).toBe("8/45"));
});

it("treats image read failures as unknown until retry succeeds", async () => {
  let fail = true;
  vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(url.endsWith("background-style")
    ? Response.json({ blur: 5, veil: 88 }) : new Response(null, { status: fail ? 503 : 404 }))));
  render(<BackgroundProvider><Probe /></BackgroundProvider>);
  await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("error"));
  fail = false;
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("ready"));
});
