import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NanobotUpdate } from "@/components/settings/overview/NanobotUpdate";
import { ClientProvider } from "@/providers/ClientProvider";
import { installSettingsViewTestHooks, jsonResponse, requestMutationMock } from "@/tests/settings-test-utils";

const idle = {
  state: "idle", mode: "release", message: "", version: null,
  requires_restart: false, can_update: true,
};

function mount(onInstalled?: () => void) {
  return render(<ClientProvider client={{ requestMutation: requestMutationMock } as never} token="tok">
    <NanobotUpdate onInstalled={onInstalled} />
  </ClientProvider>);
}

describe("nanobot updates", () => {
  installSettingsViewTestHooks();

  it("defaults to a release and requires explicit source selection", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(idle)));
    requestMutationMock.mockResolvedValue({ ...idle, state: "running" });
    mount();
    const release = await screen.findByRole("button", { name: "Install latest release" });
    await waitFor(() => expect(release).toBeEnabled());
    fireEvent.click(release);
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith("settings.nanobot.update", { dev: false }, 20000));
  });

  it("sends dev only when the advanced checkbox is selected", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(idle)));
    requestMutationMock.mockResolvedValue({ ...idle, state: "running" });
    mount();
    fireEvent.click(screen.getByText("Advanced options"));
    fireEvent.click(screen.getByRole("checkbox", { name: "Install from source" }));
    const button = screen.getByRole("button", { name: "Install development version" });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith("settings.nanobot.update", { dev: true }, 20000));
  });

  it("restores completion after a refresh and marks restart required", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({
      ...idle, state: "succeeded", version: "0.3.5", requires_restart: true,
    })));
    const installed = vi.fn();
    mount(installed);
    expect(await screen.findByText("Installed v0.3.5. Restart nanobot to apply the update.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Install latest release" })).toBeDisabled();
    expect(installed).toHaveBeenCalledTimes(1);
    expect(requestMutationMock).not.toHaveBeenCalled();
  });

  it("disables updates for a remote browser without permission", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ ...idle, can_update: false })));
    mount();
    expect(await screen.findByText(/Open WebUI on the server's localhost/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Install latest release" })).toBeDisabled();
  });

  it("shows failures and allows a retry", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ ...idle, state: "failed", message: "Offline" })));
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent("Offline");
    expect(screen.getByRole("button", { name: "Install latest release" })).toBeEnabled();
  });
});
