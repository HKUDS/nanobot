import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { StarLink, StarPrompt } from "@/components/StarPrompt";
import { starPromptAction } from "@/lib/api";
import i18n from "@/i18n";
import { supportedLocales } from "@/i18n/config";

vi.mock("@/lib/api", () => ({ starPromptAction: vi.fn() }));
const client = {
  onStatus: (handler: (status: string) => void) => { handler("open"); return () => {}; },
};
vi.mock("@/providers/ClientProvider", () => ({ useClient: () => ({ client }) }));
const action = vi.mocked(starPromptAction);
const starPromptStyles = readFileSync(resolve(process.cwd(), "src/components/StarPrompt.css"), "utf8");

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

async function clickStarLink(link: HTMLElement) {
  link.addEventListener("click", (event) => event.preventDefault(), { once: true });
  await act(async () => fireEvent.click(link));
}

it("claims once on entry and lets users skip without permanently dismissing", async () => {
  const view = render(<StarPrompt ready />);
  await enter();
  expect(screen.getByRole("dialog")).toHaveAccessibleName("Glad we could help.");
  fireEvent.click(screen.getByRole("button", { name: "Maybe later" }));
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
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Don't ask again" })));
  expect(screen.getByRole("alert")).toHaveTextContent("There may be a network issue. This reminder may appear again.");
  expect(screen.getByRole("dialog")).toBeVisible();
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Don't ask again" })));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(action).toHaveBeenLastCalledWith(client, "dismiss");
});

it("the About link opens GitHub and persists permanent dismissal", async () => {
  render(<StarLink />);
  const link = screen.getByRole("link", { name: "Star nanobot on GitHub" });
  expect(link).toHaveAttribute("href", "https://github.com/HKUDS/nanobot");
  expect(link).toHaveAttribute("target", "_blank");
  await clickStarLink(link);
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
  fireEvent.click(screen.getByRole("button", { name: "Maybe later" }));
  await act(async () => statusChanged("open"));
  expect(action).toHaveBeenCalledTimes(1);
});

it.each(supportedLocales.map(({ code }) => code))("localizes the complete invitation in %s", async (locale) => {
  await i18n.changeLanguage(locale);
  render(<StarPrompt ready />);
  await enter();
  expect(screen.getByRole("dialog")).toHaveAccessibleName(i18n.t("starPrompt.title"));
  expect(screen.getByRole("dialog")).toHaveAccessibleDescription([
    i18n.t("starPrompt.intro"), i18n.t("starPrompt.invitation"), i18n.t("starPrompt.thanks"),
  ].join(" "));
  expect(screen.getByRole("button", { name: i18n.t("starPrompt.later") })).toBeVisible();
  expect(screen.getByRole("button", { name: i18n.t("starPrompt.never") })).toBeVisible();
  expect(screen.getByRole("button", { name: i18n.t("common.close"), exact: true })).toBeVisible();
  expect(screen.getByRole("link", { name: i18n.t("starPrompt.action") })).toHaveAttribute("rel", "noopener noreferrer");
});

it.each(["close button", "Escape"])("restores focus after %s without permanently dismissing", async (method) => {
  const user = userEvent.setup();
  const view = render(<><button>Previous control</button><StarPrompt ready={false} /></>);
  screen.getByRole("button", { name: "Previous control" }).focus();
  view.rerender(<><button>Previous control</button><StarPrompt ready /></>);
  await enter();
  expect(screen.getByRole("heading", { name: "Glad we could help." })).toHaveFocus();
  if (method === "Escape") await user.keyboard("{Escape}");
  else await user.click(screen.getByRole("button", { name: "Close", exact: true }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Previous control" })).toHaveFocus();
  expect(action).toHaveBeenCalledTimes(1);
});

it("keeps the illustration decorative and actions usable if it fails to load", async () => {
  const view = render(<StarPrompt ready={false} />);
  expect(document.querySelector("img")).toBeNull();
  view.rerender(<StarPrompt ready />);
  await enter();
  const artwork = screen.getByRole("dialog").querySelector("img")!;
  expect(artwork).toHaveAttribute("alt", "");
  expect(artwork).toHaveAttribute("width", "1672");
  expect(artwork).toHaveAttribute("height", "941");
  expect(artwork.getAttribute("src")).toContain("star-invitation");
  fireEvent.error(artwork);
  fireEvent.click(screen.getByRole("button", { name: "Maybe later" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("keeps the GitHub action a real link and retries failed preference saves", async () => {
  render(<StarPrompt ready />);
  await enter();
  const link = screen.getByRole("link", { name: "Star on GitHub" });
  expect(link).toHaveAttribute("href", "https://github.com/HKUDS/nanobot");
  expect(link).toHaveAttribute("target", "_blank");
  expect(link.querySelector(".star-prompt-decoration")).toHaveAttribute("aria-hidden", "true");
  action.mockRejectedValueOnce(new Error("offline"));
  await clickStarLink(link);
  expect(screen.getByRole("alert")).toBeVisible();
  expect(screen.getByRole("dialog")).toBeVisible();
  await clickStarLink(link);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(action.mock.calls.map(([, command]) => command)).toEqual(["claim", "dismiss", "dismiss"]);
});

it.each([false, true])("preserves middle-click dismissal for the GitHub link (fullWidth: %s)", async (fullWidth) => {
  const saved = vi.fn();
  render(<StarLink fullWidth={fullWidth} onSaved={saved} />);
  const link = screen.getByRole("link");
  await act(async () => fireEvent(link, new MouseEvent("auxclick", { bubbles: true, button: 2 })));
  expect(action).not.toHaveBeenCalled();
  await act(async () => fireEvent(link, new MouseEvent("auxclick", { bubbles: true, button: 1 })));
  expect(action).toHaveBeenCalledWith(client, "dismiss");
  expect(saved).toHaveBeenCalledTimes(1);
  if (!fullWidth) expect(link.querySelector(".star-prompt-decoration")).toBeNull();
});

it.each([
  { input: "hover", reduced: false },
  { input: "focus-visible", reduced: false },
  { input: "hover", reduced: true },
  { input: "focus-visible", reduced: true },
])("respects reduced motion ($reduced) for $input decoration", ({ input, reduced }) => {
  // happy-dom cannot emulate these device/input states. Enable their media
  // branches and replace pseudo-classes with equally specific attributes so
  // the real stylesheet's cascade, including !important, is still exercised.
  const style = document.createElement("style");
  style.textContent = starPromptStyles
    .replaceAll(":hover", "[data-hover]")
    .replaceAll(":focus-visible", "[data-focus-visible]")
    .replace("(hover: hover) and (pointer: fine)", "all")
    .replace("(prefers-reduced-motion: reduce)", reduced ? "all" : "not all");
  document.head.append(style);
  try {
    render(<StarLink fullWidth />);
    const link = screen.getByRole("link");
    link.setAttribute(`data-${input}`, "");
    const decoration = getComputedStyle(link.querySelector(".star-prompt-decoration")!);
    const sparkle = getComputedStyle(link.querySelector(".star-prompt-sparkle")!);
    if (reduced) {
      expect(decoration.animation).toBe("none");
      expect(decoration.transition).toBe("none");
      expect(decoration.transform).toBe("none");
      expect(sparkle.animation).toBe("none");
      expect(sparkle.display).toBe("none");
    } else {
      expect(decoration.animation).toContain("star-prompt-pop");
      expect(sparkle.animation).toContain("star-prompt-twinkle");
    }
  } finally {
    style.remove();
  }
});
