import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { BackgroundProvider, useBackground } from "@/providers/BackgroundProvider";

const state = vi.hoisted(() => ({
  token: "test",
  getToken: () => state.token,
  client: {
    requestMutation: vi.fn(),
    uploadBackground: vi.fn(),
  },
}));
vi.mock("@/providers/ClientProvider", () => ({
  useClient: () => ({ client: state.client, token: state.token, getToken: state.getToken }),
}));
vi.mock("@/hooks/useObjectUrl", () => ({ useObjectUrl: () => null }));

function Probe({ name = "current" }: { name?: string }) {
  const background = useBackground()!;
  return <div data-testid={name}>
    <span data-testid="style">{background.blur}/{background.veil}</span>
    <span data-testid="image">{background.hasBackground ? "present" : "absent"}</span>
    <span data-testid="state">{background.ready ? "ready" : background.loadError ? "error" : "loading"}</span>
    <button onClick={background.retry}>Retry</button>
    <button disabled={!background.ready} onClick={() => void background.upload(new File(["image"], "image.png", { type: "image/png" }))}>Upload</button>
    <button disabled={!background.ready} onClick={() => void background.setStyle(10, 50)}>Save</button>
    <button disabled={!background.ready} onClick={() => void background.remove()}>Remove</button>
  </div>;
}

beforeEach(() => {
  state.token = "test";
  state.client.requestMutation.mockReset().mockResolvedValue({});
  state.client.uploadBackground.mockReset().mockResolvedValue(undefined);
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.clearAllMocks(); });

it("does not let an earlier read overwrite a saved style after retry", async () => {
  let resolveStyle!: (response: Response) => void;
  const firstStyle = new Promise<Response>(resolve => { resolveStyle = resolve; });
  let imageReads = 0;
  let styleReads = 0;
  vi.stubGlobal("fetch", vi.fn((url: string) => url.endsWith("background-style")
    ? ++styleReads === 1 ? firstStyle : Promise.resolve(Response.json({ blur: 5, veil: 88 }))
    : Promise.resolve(new Response(null, { status: ++imageReads === 1 ? 503 : 404 }))));
  render(<BackgroundProvider><Probe /></BackgroundProvider>);
  await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("error"));
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("ready"));
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(screen.getByTestId("style").textContent).toBe("10/50"));
  await act(async () => { resolveStyle(Response.json({ blur: 2, veil: 26 })); await firstStyle; });
  expect(screen.getByTestId("style").textContent).toBe("10/50");
});

it("updates the saving client and loads shared changes when another client refreshes", async () => {
  let value = { blur: 2, veil: 26 };
  let image: Blob | null = null;
  vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(url.endsWith("background-style")
    ? Response.json(value) : image ? new Response(image) : new Response(null, { status: 404 }))));
  state.client.uploadBackground.mockImplementation(async (file) => { image = file; });
  state.client.requestMutation.mockImplementation(async (action, payload) => {
    if (action === "background.style") value = payload as typeof value;
    if (action === "background.delete") image = null;
    return {};
  });
  render(<BackgroundProvider><Probe name="first" /></BackgroundProvider>);
  let second = render(<BackgroundProvider><Probe name="second" /></BackgroundProvider>);
  const firstView = () => within(screen.getByTestId("first"));
  const secondView = () => within(screen.getByTestId("second"));
  await waitFor(() => expect(firstView().getByTestId("state").textContent).toBe("ready"));
  await waitFor(() => expect(secondView().getByTestId("state").textContent).toBe("ready"));
  fireEvent.click(firstView().getByRole("button", { name: "Upload" }));
  await waitFor(() => expect(firstView().getByTestId("image").textContent).toBe("present"));
  fireEvent.click(firstView().getByRole("button", { name: "Save" }));
  await waitFor(() => expect(firstView().getByTestId("style").textContent).toBe("10/50"));
  expect(secondView().getByTestId("style").textContent).toBe("2/26");
  expect(secondView().getByTestId("image").textContent).toBe("absent");
  second.unmount();
  second = render(<BackgroundProvider><Probe name="second" /></BackgroundProvider>);
  await waitFor(() => expect(secondView().getByTestId("state").textContent).toBe("ready"));
  expect(secondView().getByTestId("style").textContent).toBe("10/50");
  expect(secondView().getByTestId("image").textContent).toBe("present");
  fireEvent.click(firstView().getByRole("button", { name: "Remove" }));
  await waitFor(() => expect(firstView().getByTestId("image").textContent).toBe("absent"));
  expect(secondView().getByTestId("image").textContent).toBe("present");
  second.unmount();
  render(<BackgroundProvider><Probe name="second" /></BackgroundProvider>);
  await waitFor(() => expect(secondView().getByTestId("state").textContent).toBe("ready"));
  expect(secondView().getByTestId("image").textContent).toBe("absent");
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

it("allows retry with the latest token when a background read times out", async () => {
  vi.useFakeTimers();
  let stalled = true;
  const fetcher = vi.fn((url: string, init: RequestInit) => {
    expect(init.headers).toEqual({ Authorization: `Bearer ${state.token}` });
    return url.endsWith("background-style")
      ? Promise.resolve(Response.json({ blur: 5, veil: 88 }))
      : stalled ? new Promise<Response>(() => {}) : Promise.resolve(new Response(null, { status: 404 }));
  });
  vi.stubGlobal("fetch", fetcher);
  render(<BackgroundProvider><Probe /></BackgroundProvider>);
  await act(async () => { await vi.advanceTimersByTimeAsync(20_000); });
  expect(screen.getByTestId("state").textContent).toBe("error");
  stalled = false;
  state.token = "refreshed";
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Retry" })); });
  expect(screen.getByTestId("state").textContent).toBe("ready");
  expect(fetcher.mock.lastCall?.[1].headers).toEqual({ Authorization: "Bearer refreshed" });
});
