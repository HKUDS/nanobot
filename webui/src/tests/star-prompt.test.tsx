import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { StarLink, StarPrompt } from "@/components/StarPrompt";
import { starPromptAction } from "@/lib/api";
import i18n from "@/i18n";

vi.mock("@/lib/api", () => ({ starPromptAction: vi.fn() }));
const client = {
  onStatus: (handler: (status: string) => void) => { handler("open"); return () => {}; },
};
vi.mock("@/providers/ClientProvider", () => ({ useClient: () => ({ client }) }));
const action = vi.mocked(starPromptAction);

beforeEach(async () => {
  vi.clearAllMocks();
  await i18n.changeLanguage("en");
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  action.mockResolvedValue({ show: true });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

async function enter() {
  await act(async () => { await Promise.resolve(); });
}

it("claims once on entry and lets users skip without permanently dismissing", async () => {
  const view = render(<StarPrompt ready />);
  await enter();
  expect(screen.getByRole("dialog")).toHaveAccessibleName("Thanks for using nanobot");
  fireEvent.click(screen.getByRole("button", { name: "Not now" }));
  view.rerender(<StarPrompt ready />);
  await enter();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(action).toHaveBeenCalledTimes(1);
  expect(action).toHaveBeenCalledWith(client, "claim");
});

it.each(["pointerdown", "keydown", "input", "wheel"])(
  "skips this visit when %s occurs before the first screen is ready", async (event) => {
    const view = render(<StarPrompt ready={false} />);
    fireEvent(document, new Event(event, { bubbles: true }));
    view.rerender(<StarPrompt ready />);
    await enter();
    expect(action).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  },
);

it.each(["pointerdown", "keydown", "input", "wheel"])(
  "discards a delayed claim when %s occurs while waiting", async (event) => {
    let resolve!: (value: { show: boolean }) => void;
    action.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    const view = render(<StarPrompt ready />);
    fireEvent(document, new Event(event, { bubbles: true }));
    await act(async () => resolve({ show: true }));
    view.rerender(<StarPrompt ready />);
    await enter();
    expect(action).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  },
);

it("stays hidden when another page claimed the invitation or storage fails", async () => {
  action.mockResolvedValueOnce({ show: false });
  const view = render(<StarPrompt ready />);
  await enter();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  view.unmount();
  action.mockRejectedValueOnce(new Error("disk full"));
  render(<StarPrompt ready />);
  await enter();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("keeps a failed permanent dismissal retryable", async () => {
  render(<StarPrompt ready />);
  await enter();
  action.mockRejectedValueOnce(new Error("offline"));
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Don’t ask again" })));
  expect(screen.getByRole("alert")).toHaveTextContent("Could not save");
  expect(screen.getByRole("dialog")).toBeVisible();
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Don’t ask again" })));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(action).toHaveBeenLastCalledWith(client, "dismiss");
});

it("the About link opens GitHub and persists permanent dismissal", async () => {
  render(<StarLink />);
  const link = screen.getByRole("link", { name: "Star nanobot on GitHub" });
  expect(link).toHaveAttribute("href", "https://github.com/HKUDS/nanobot");
  expect(link).toHaveAttribute("target", "_blank");
  await act(async () => fireEvent.click(link));
  expect(action).toHaveBeenCalledWith(client, "dismiss");
});


it("waits for the initial connection and still attempts only once", async () => {
  let statusChanged!: (status: string) => void;
  vi.spyOn(client, "onStatus").mockImplementationOnce((handler) => {
    statusChanged = handler;
    handler("connecting");
    return () => {};
  });
  render(<StarPrompt ready />);
  expect(action).not.toHaveBeenCalled();
  await act(async () => statusChanged("open"));
  expect(screen.getByRole("dialog")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Not now" }));
  await act(async () => statusChanged("open"));
  expect(action).toHaveBeenCalledTimes(1);
});
