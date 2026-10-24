import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SessionAutomationJob } from "@/lib/types";

const job: SessionAutomationJob = {
  id: "job-1", name: "Morning check", enabled: true,
  schedule: { kind: "every", every_ms: 3_600_000 },
  payload: { message: "Check the project status" },
  state: { next_run_at_ms: Date.now() + 3_600_000 },
};
let release: (() => void) | undefined;
let moduleLoad: Promise<unknown> | undefined;

async function loadView(fail = false) {
  const loaded = vi.fn();
  const gate = new Promise<void>((resolve) => { release = resolve; });
  vi.doMock("@/components/settings/system/AutomationsSettings", (original) => {
    loaded();
    moduleLoad = gate.then(() => {
      if (fail) throw new Error("Automation chunk unavailable");
      return original<typeof import("@/components/settings/system/AutomationsSettings")>();
    });
    return moduleLoad;
  });
  const { initializeI18n, loadAllLocaleResources } = await import("@/i18n");
  await initializeI18n();
  await loadAllLocaleResources();
  const { SessionInfoPopoverView } = await import("@/components/thread/SessionInfoPopoverView");
  render(<><textarea aria-label="Unsent draft" defaultValue="Keep this draft" /><SessionInfoPopoverView
    title="Release work" jobs={[job]} loading={false} loadFailed={false} now={Date.now()}
    onAction={async () => []} onEdit={async () => [job]}
  /></>);
  return loaded;
}

async function selectJob() {
  fireEvent.click(screen.getByRole("button", { name: "Session details" }));
  fireEvent.click(await screen.findByRole("button", { name: /Morning check/ }));
  return screen.findByRole("dialog", { name: "Morning check" });
}

beforeEach(() => { vi.resetModules(); localStorage.clear(); });
afterEach(async () => {
  cleanup();
  await act(async () => { release?.(); await moduleLoad?.catch(() => {}); });
  release = undefined;
  moduleLoad = undefined;
  vi.doUnmock("@/components/settings/system/AutomationsSettings");
  vi.restoreAllMocks();
});

describe("session automation dialog loading", () => {
  it("loads only on inspection and replaces a named loading dialog with the real controls", async () => {
    const loaded = await loadView();
    await vi.dynamicImportSettled();
    expect(loaded).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Session details" }));
    const row = await screen.findByRole("button", { name: /Morning check/ });
    expect(loaded).not.toHaveBeenCalled();
    fireEvent.click(row);
    const pending = await screen.findByRole("dialog", { name: "Morning check" });
    expect(within(pending).getByRole("status", { name: "Loading automations..." })).toHaveAttribute("aria-busy", "true");
    await act(async () => { release?.(); await moduleLoad; });
    await screen.findByText("Check the project status");
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Edit" })).toBeEnabled();
    expect(screen.getByRole("textbox", { name: "Unsent draft", hidden: true })).toHaveValue("Keep this draft");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Session details" })).toHaveFocus());
  });

  it("can close during download without a late dialog reopening", async () => {
    const loaded = await loadView();
    const dialog = await selectJob();
    await waitFor(() => expect(loaded).toHaveBeenCalledOnce());
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Session details" })).toHaveFocus());
    await act(async () => { release?.(); await moduleLoad; });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Unsent draft", hidden: true })).toHaveValue("Keep this draft");
    await selectJob();
    expect(await screen.findByText("Check the project status")).toBeVisible();
    expect(loaded).toHaveBeenCalledOnce();
  });

  it("contains a failed chunk in a closeable dialog without losing the chat draft", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    await loadView(true);
    await selectJob();
    await act(async () => { release?.(); await moduleLoad?.catch(() => {}); });
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load automations.");
    expect(screen.getByRole("textbox", { name: "Unsent draft", hidden: true })).toHaveValue("Keep this draft");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Session details" })).toHaveFocus());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
