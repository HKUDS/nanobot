import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import * as clipboard from "@/lib/clipboard";
import {
  installSettingsViewTestHooks, jsonResponse, openPopover, renderSettingsView,
  requestMutationMock, settingsPayload,
} from "@/tests/settings-test-utils";

describe("Copilot device sign-in", () => {
  installSettingsViewTestHooks();

  it.each(["approve", "close", "unmount", "close-before-start"])("handles %s without losing the preset draft", async (ending) => {
    const payload = settingsPayload();
    payload.providers = [{
      name: "github_copilot", label: "GitHub Copilot", configured: true,
      auth_type: "oauth", model_catalog: "hybrid", oauth_login_supported: true,
    }];
    const flow = {
      status: "authorization_required", provider: "github_copilot", flow_id: "device-flow",
      authorization_url: "https://github.com/login/device", user_code: "ABCD-EFGH",
      completion_input: "device_code", expires_in: 600,
    };
    let approved = false;
    let recovered = false;
    let resolveStart!: (value: typeof flow) => void;
    requestMutationMock.mockImplementation(async (action, args) => {
      if (action === "settings.provider.oauth_login") {
        return ending === "close-before-start"
          ? new Promise((resolve) => { resolveStart = resolve; }) : flow;
      }
      if (action === "settings.provider.oauth_complete") {
        if (args.cancel) return { status: "cancelled", provider: flow.provider, flow_id: flow.flow_id };
        if (!approved) return { status: "pending", provider: flow.provider, flow_id: flow.flow_id };
        recovered = true;
        return { ...payload, providers: payload.providers.map((row) => ({ ...row })) };
      }
      throw new Error(`Unexpected mutation: ${action}`);
    });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/provider-models?")) return jsonResponse({
        provider: "github_copilot", status: "available", catalog_kind: "hybrid",
        source: recovered ? "remote" : "fallback", error_kind: recovered ? null : "auth_required",
        models: [{ id: "github-copilot/new-model" }],
      });
      return jsonResponse(payload);
    }));
    renderSettingsView({ initialSection: "models" });
    fireEvent.click(await screen.findByRole("button", { name: "New model preset" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Preset name" }), { target: { value: "Draft" } });
    await openPopover(screen.getByRole("button", { name: "Select model" }));
    fireEvent.click(await screen.findByRole("button", { name: "Sign in again" }));
    if (ending === "close-before-start") {
      cleanup();
      await act(async () => { resolveStart(flow); });
    } else {
      const dialog = await screen.findByRole("dialog", { name: "GitHub Copilot" });
      expect(within(dialog).getByRole("textbox", { name: "Device code" })).toHaveValue("ABCD-EFGH");
      expect(within(dialog).queryByRole("button", { name: "Finish sign-in" })).not.toBeInTheDocument();
      expect(within(dialog).queryByRole("textbox", { name: "Authorization code" })).not.toBeInTheDocument();
      if (ending === "approve") {
        const copy = vi.spyOn(clipboard, "copyTextToClipboard").mockResolvedValue(true);
        const open = vi.spyOn(window, "open").mockReturnValue(null);
        try {
          fireEvent.click(within(dialog).getByRole("button", { name: "Copy" }));
          await within(dialog).findByRole("button", { name: "Copied" });
          expect(copy).toHaveBeenCalledWith("ABCD-EFGH");
          fireEvent.click(within(dialog).getByRole("button", { name: "Open GitHub" }));
          expect(open).toHaveBeenCalledWith(flow.authorization_url, "_blank", "noopener,noreferrer");
          approved = true;
          await waitFor(() => expect(recovered).toBe(true), { timeout: 3000 });
          expect(screen.queryByRole("dialog", { name: "GitHub Copilot" })).not.toBeInTheDocument();
          expect(screen.getByRole("textbox", { name: "Preset name" })).toHaveValue("Draft");
          await openPopover(screen.getByRole("button", { name: "Select model" }));
          expect(await screen.findByRole("option", { name: /new-model/ })).toBeVisible();
          expect(requestMutationMock.mock.calls.some(([, args]) => args.cancel)).toBe(false);
        } finally {
          copy.mockRestore();
          open.mockRestore();
        }
        return;
      }
      if (ending === "unmount") cleanup();
      else fireEvent.keyDown(dialog, { key: "Escape" });
    }
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.provider.oauth_complete",
      { provider: "github_copilot", flow_id: "device-flow", cancel: true },
      expect.any(Number),
    ));
    expect(recovered).toBe(false);
  });
});
