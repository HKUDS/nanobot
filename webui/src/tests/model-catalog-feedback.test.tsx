import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ModelIdPicker } from "@/components/settings/shared/ModelControls";
import type { ProviderModelsPayload } from "@/lib/types";
import { installSettingsViewTestHooks, jsonResponse, openPopover, settingsPayload } from "@/tests/settings-test-utils";
import en from "@/i18n/locales/en/common.json";
import zhCN from "@/i18n/locales/zh-CN/common.json";

function settings() {
  return {
    ...settingsPayload(),
    providers: [{
      name: "openai_codex", label: "OpenAI Codex", configured: true,
      auth_type: "oauth" as const, model_catalog: "hybrid" as const,
      oauth_login_supported: true,
    }],
  };
}

function catalog(
  source: ProviderModelsPayload["source"],
  error_kind: ProviderModelsPayload["error_kind"],
): ProviderModelsPayload {
  return {
    provider: "openai_codex", label: "OpenAI Codex", status: "available",
    catalog_kind: "hybrid", source, error_kind,
    models: [{ id: "openai-codex/offline-model", label: "Offline model" }],
    model_count: 1,
    // Never use raw provider text as a translated, user-facing catalog notice.
    message: "private upstream response fixture",
  };
}

describe("OAuth catalog feedback", () => {
  installSettingsViewTestHooks();

  it.each(["stale", "fallback"] as const)("explains %s auth failures without hiding models or manual IDs", async (source) => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(catalog(source, "auth_required"))));
    const onChange = vi.fn();
    const login = vi.fn();
    render(<ModelIdPicker token="tok" settings={settings()} provider="openai_codex"
      value="" showProviderLogos onChange={onChange} onProviderOAuthLogin={login} />);
    await openPopover(screen.getByRole("button", { name: "Select model" }));
    const notice = await screen.findByRole("status");
    expect(notice).toHaveTextContent("Authorization expired. Please sign in again.");
    expect(notice).toHaveTextContent(source === "stale" ? "cached models" : "built-in models");
    expect(notice).toHaveTextContent("out of date");
    expect(screen.queryByText(/private upstream/)).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Offline model/ })).toBeVisible();
    const search = screen.getByRole("combobox");
    expect(search).toHaveAttribute("aria-describedby", notice.id);
    fireEvent.change(search, { target: { value: "openai-codex/custom-model" } });
    fireEvent.click(screen.getByRole("option", { name: /Use.*custom-model/ }));
    expect(onChange).toHaveBeenCalledWith("openai-codex/custom-model");
    await openPopover(screen.getByRole("button", { name: "Select model" }));
    fireEvent.click(await screen.findByRole("button", { name: "Sign in again" }));
    expect(login).toHaveBeenCalledWith("openai_codex");
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it.each(["unavailable", undefined] as const)("does not request login for temporary or legacy failures (%s)", async (kind) => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(catalog("fallback", kind))));
    render(<ModelIdPicker token="tok" settings={settings()} provider="openai_codex"
      value="" showProviderLogos onChange={vi.fn()} onProviderOAuthLogin={vi.fn()} />);
    await openPopover(screen.getByRole("button", { name: "Select model" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Could not refresh models. Try again later.");
    expect(screen.queryByRole("button", { name: "Sign in again" })).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Offline model/ })).toBeVisible();
  });

  it("reloads an open picker on successful same-account login and clears stale feedback", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(catalog("stale", "auth_required")))
      .mockResolvedValueOnce(jsonResponse({
        ...catalog("remote", null), message: null,
        models: [{ id: "openai-codex/new-model", label: "New model" }],
      }));
    vi.stubGlobal("fetch", fetchMock);
    const props = { token: "tok", provider: "openai_codex", value: "", showProviderLogos: true, onChange: vi.fn() };
    const view = render(<ModelIdPicker {...props} settings={settings()} />);
    await openPopover(screen.getByRole("button", { name: "Select model" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Authorization expired");
    // Login produces a new settings snapshot, even when the account is unchanged.
    view.rerender(<ModelIdPicker {...props} settings={settings()} />);
    expect(await screen.findByRole("option", { name: /New model/ })).toBeVisible();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("ignores an old auth failure arriving after refreshed settings", async () => {
    let finishOld!: (response: Response) => void;
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => new Promise<Response>((resolve) => { finishOld = resolve; }))
      .mockResolvedValueOnce(jsonResponse(catalog("remote", null)));
    vi.stubGlobal("fetch", fetchMock);
    const props = { token: "tok", provider: "openai_codex", value: "", showProviderLogos: true, onChange: vi.fn() };
    const view = render(<ModelIdPicker {...props} settings={settings()} />);
    await openPopover(screen.getByRole("button", { name: "Select model" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    view.rerender(<ModelIdPicker {...props} settings={settings()} />);
    await screen.findByRole("option", { name: /Offline model/ });
    await act(async () => { finishOld(jsonResponse(catalog("fallback", "auth_required"))); });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it.each([en, zhCN])("includes localized notices", (locale) => {
    for (const key of ["catalogAuthRequired", "catalogUnavailable", "catalogStale", "catalogFallback"] as const) {
      expect(locale.settings.models[key].length).toBeGreaterThan(0);
    }
  });
});
