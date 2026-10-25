import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";

import {
  installSettingsViewTestHooks, renderSettingsView, requestMutationMock, settingsPayload,
} from "@/tests/settings-test-utils";

const path = "agents.defaults.session_ttl_minutes";

function setup(minutes = 720) {
  let persisted = {
    ...settingsPayload(),
    runtime_config: { [path]: minutes, "agents.defaults.unified_session": false },
  };
  requestMutationMock.mockImplementation(async (_action, { values }) => {
    persisted = { ...persisted, requires_restart: true,
      runtime_config: { ...persisted.runtime_config, ...values } };
    return persisted;
  });
  renderSettingsView({ initialSection: "runtime", initialSettings: persisted, onRestart: vi.fn() });
  return () => persisted;
}

const input = () => screen.getByRole("textbox", { name: "Idle timeout" });
const toggle = () => screen.getByRole("switch", { name: "Auto-compact idle sessions" });

function edit(next: string) {
  fireEvent.focus(input());
  fireEvent.change(input(), { target: { value: next } });
}

function expectSaved(minutes: number) {
  expect(requestMutationMock).toHaveBeenLastCalledWith(
    "settings.runtime_config.update", { values: { [path]: minutes } }, 20_000,
  );
}

describe("Idle compaction settings", () => {
  installSettingsViewTestHooks();

  it.each([15, 720, 0])("reads %i minutes in System → Sessions", (minutes) => {
    setup(minutes);
    const sessions = within(screen.getByRole("region", { name: "Sessions" }));
    expect(sessions.getByRole("switch", { name: "Auto-compact idle sessions" })).toHaveAttribute(
      "aria-checked", String(minutes > 0),
    );
    if (minutes) expect(input()).toHaveValue(String(minutes));
    else expect(screen.queryByRole("textbox", { name: "Idle timeout" })).not.toBeInTheDocument();
  });

  it("commits minutes on blur, retains minute precision, and reads saved values after remount", async () => {
    const persisted = setup(15);
    vi.useFakeTimers();
    edit("721");
    await act(async () => { await vi.advanceTimersByTimeAsync(1_500); });
    expect(requestMutationMock).not.toHaveBeenCalled();
    vi.useRealTimers();
    fireEvent.blur(input());
    await waitFor(() => expectSaved(721));
    await waitFor(() => expect(input()).toBeEnabled());
    expect(screen.getAllByText("Saved. Restart to apply changes.").length).toBeGreaterThan(0);
    cleanup();
    renderSettingsView({ initialSection: "runtime", initialSettings: persisted() });
    expect(input()).toHaveValue("721");
  });

  it("saves when keyboard focus leaves the section after reaching Cancel", async () => {
    setup();
    const user = userEvent.setup();
    await user.click(input());
    await user.clear(input());
    await user.type(input(), "37");
    await user.tab();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(requestMutationMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole("heading", { name: "Sessions" }));
    await waitFor(() => expectSaved(37));
  });

  it("disables with zero and restores the previous duration when enabled again", async () => {
    setup();
    fireEvent.click(toggle());
    await waitFor(() => expectSaved(0));
    await waitFor(() => expect(toggle()).toBeEnabled());
    expect(toggle()).not.toBeChecked();
    expect(screen.queryByRole("textbox", { name: "Idle timeout" })).not.toBeInTheDocument();
    fireEvent.click(toggle());
    await waitFor(() => expectSaved(720));
    expect(input()).toHaveValue("720");
  });

  it("enables a saved disabled setting with the default duration", async () => {
    setup(0);
    fireEvent.click(toggle());
    await waitFor(() => expectSaved(15));
    expect(input()).toHaveValue("15");
  });

  it("accepts zero entered in the duration field on Enter", async () => {
    setup();
    edit("0");
    expect(input()).toHaveValue("0");
    fireEvent.keyDown(input(), { key: "Enter" });
    await waitFor(() => expectSaved(0));
    expect(toggle()).not.toBeChecked();
    expect(screen.queryByRole("textbox", { name: "Idle timeout" })).not.toBeInTheDocument();
  });

  it.each(["", "-1", "1.5", "1e3", "9007199254740992"])("retains invalid input %j without saving", async (next) => {
    setup();
    edit(next);
    fireEvent.blur(input());
    expect(await screen.findByText("Enter a non-negative whole number of minutes.")).toBeVisible();
    expect(input()).toHaveValue(next);
    expect(input()).toHaveAttribute("aria-invalid", "true");
    expect(requestMutationMock).not.toHaveBeenCalled();
  });

  it("keeps the draft after a failed save and allows retry", async () => {
    setup();
    requestMutationMock.mockRejectedValueOnce(new Error("Could not save settings"));
    edit("37");
    fireEvent.blur(input());
    expect(await screen.findByText("Could not save settings")).toBeVisible();
    expect(input()).toHaveValue("37");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledTimes(2));
    expectSaved(37);
    await waitFor(() => expect(screen.queryByText("Could not save settings")).not.toBeInTheDocument());
  });

  it.each(["37", "0"])("cancels a focused %s minute draft without committing it on blur", async (next) => {
    setup();
    const user = userEvent.setup();
    await user.click(input());
    await user.clear(input());
    await user.type(input(), next);
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(input()).toHaveValue("720");
    expect(requestMutationMock).not.toHaveBeenCalled();
  });

  it("can cancel a failed toggle without losing the stored enabled state", async () => {
    setup();
    requestMutationMock.mockRejectedValueOnce(new Error("Could not save settings"));
    fireEvent.click(toggle());
    expect(await screen.findByText("Could not save settings")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(toggle()).toBeChecked();
    expect(input()).toHaveValue("720");
    expect(requestMutationMock).toHaveBeenCalledTimes(1);
  });
});
