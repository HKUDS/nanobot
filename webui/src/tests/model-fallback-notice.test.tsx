import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ModelFallbackNotice } from "@/components/thread/ModelFallbackNotice";
import { __clearLogoFallbackCacheForTests } from "@/hooks/useLogoFallback";
import { providerBrand } from "@/lib/provider-brand";

describe("model fallback notice", () => {
  beforeEach(__clearLogoFallbackCacheForTests);
  afterEach(cleanup);

  it("centers the notice contents and labels its model-settings destination", () => {
    const onOpenSettings = vi.fn();
    render(<ModelFallbackNotice model="xai-grok/grok-4.5" reauthProvider="openai_codex"
      reauthProviderLabel="OpenAI Codex" onDismiss={vi.fn()} onOpenSettings={onOpenSettings} />);
    expect(screen.getByRole("status")).toHaveClass("items-center");
    expect(screen.getByRole("status")).not.toHaveClass("items-start");
    fireEvent.click(screen.getByRole("button", { name: "Open model settings" }));
    expect(onOpenSettings).toHaveBeenCalledOnce();
  });

  it.each(["openai_codex", "xai_grok", "github_copilot"])("shows the rejected %s provider, not the backup", (provider) => {
    render(<ModelFallbackNotice model="deepseek/deepseek-chat" reauthProvider={provider}
      reauthProviderLabel={provider} onDismiss={vi.fn()} />);
    const tile = screen.getByTestId("model-fallback-notice-logo");
    const image = tile.querySelector("img")!;
    expect(image).toHaveAttribute("src", providerBrand(provider)!.logoUrl);
    expect(image).toHaveAttribute("alt", "");
    expect(tile).toHaveAttribute("aria-hidden", "true");
    expect(tile).toHaveClass("h-[18px]", "w-[18px]");
    fireEvent.load(image);
    expect(tile).toHaveClass("bg-white");
    for (const url of providerBrand(provider)!.logoUrls) {
      expect(tile.querySelector("img")).toHaveAttribute("src", url);
      fireEvent.error(tile.querySelector("img")!);
    }
    expect(tile.querySelector("img")).toBeNull();
    expect(tile).toHaveTextContent(providerBrand(provider)!.initials.slice(0, 2));
  });

  it("uses the fallback model's brand for a generic notice", () => {
    render(<ModelFallbackNotice model="xai-grok/grok-4.5" onDismiss={vi.fn()} />);
    expect(screen.getByTestId("model-fallback-notice-logo").querySelector("img"))
      .toHaveAttribute("src", providerBrand("xai_grok")!.logoUrl);
  });
});
