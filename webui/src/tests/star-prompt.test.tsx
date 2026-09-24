import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { StarLink, StarPrompt } from "@/components/StarPrompt";
import { starPromptAction } from "@/lib/api";
import i18n from "@/i18n";

vi.mock("@/lib/api", () => ({ starPromptAction: vi.fn() }));
const client = { status: "open" };
vi.mock("@/providers/ClientProvider", () => ({ useClient: () => ({ client }) }));
const action = vi.mocked(starPromptAction);

beforeEach(async () => {
  vi.clearAllMocks();
  await i18n.changeLanguage("en");
  vi.useFakeTimers();
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  action.mockResolvedValue({ show: true });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

async function enter() {
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
}

it("claims once on entry and lets users skip without permanently dismissing", async () => {
  const view = render(<StarPrompt ready busy={false} />);
  await enter();
  expect(screen.getByRole("dialog")).toHaveAccessibleName("Thanks for using nanobot");
  fireEvent.click(screen.getByRole("button", { name: "Not now" }));
  view.rerender(<StarPrompt ready busy={false} />);
  await enter();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(action).toHaveBeenCalledTimes(1);
  expect(action).toHaveBeenCalledWith(client, "claim");
});

it("never interrupts a running conversation, including when it later finishes", async () => {
  const view = render(<StarPrompt ready busy />);
  await enter();
  view.rerender(<StarPrompt ready busy={false} />);
  await enter();
  expect(action).not.toHaveBeenCalled();
});

it("stays hidden when another page claimed the invitation or storage fails", async () => {
  action.mockResolvedValueOnce({ show: false });
  const view = render(<StarPrompt ready busy={false} />);
  await enter();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  view.unmount();
  action.mockRejectedValueOnce(new Error("disk full"));
  render(<StarPrompt ready busy={false} />);
  await enter();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("keeps a failed permanent dismissal retryable", async () => {
  render(<StarPrompt ready busy={false} />);
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
