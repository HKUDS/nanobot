import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { OverviewSettings } from "@/components/settings/overview/OverviewSettings";
import { ProviderPickerIcon } from "@/components/settings/shared/ModelControls";
import { ModelPresetBadge } from "@/components/thread/ModelPresetBadge";
import { __clearLogoFallbackCacheForTests } from "@/hooks/useLogoFallback";
import { providerBrand } from "@/lib/provider-brand";
import { settingsPayload } from "@/tests/settings-test-utils";

describe.each(["picker", "overview", "composer", "hero"] as const)("%s provider logos", (surface) => {
  beforeEach(__clearLogoFallbackCacheForTests);
  afterEach(cleanup);

  function renderIcon(provider: string, showBrandLogos = true) {
    const settings = settingsPayload();
    settings.agent.resolved_provider = provider;
    const view = render(surface === "picker"
      ? <ProviderPickerIcon provider={provider} showBrandLogos={showBrandLogos} />
      : surface === "overview"
        ? <OverviewSettings settings={settings} showBrandLogos={showBrandLogos} onSelectSection={() => {}} />
        : <ModelPresetBadge provider={provider} label={provider} isHero={surface === "hero"} />);
    const prefix = surface === "picker" ? "provider-picker" : surface === "overview" ? "overview" : "composer-model";
    return { ...view, icon: () => view.getByTestId(`${prefix}-logo-${provider}`) };
  }

  function expectFrame(icon: HTMLElement) {
    expect(icon).toHaveClass("shrink-0", "overflow-hidden");
    expect(icon.className.split(/\s+/).some((value) => value.startsWith("border"))).toBe(false);
    if (surface === "composer") expect(icon).toHaveClass("h-[18px]", "w-[18px]");
    else if (surface === "hero") expect(icon).toHaveClass("h-4", "w-4");
    else expect(icon).toHaveClass("h-5", "w-5");
  }

  it.each(["github_copilot", "deepseek", "kimi_coding"])("keeps %s readable on a white inset tile", (provider) => {
    const view = renderIcon(provider);
    const icon = view.icon();
    const image = icon.querySelector("img")!;
    expectFrame(icon);
    expect(icon).toHaveClass("bg-muted");
    expect(image).toHaveClass("h-3.5", "w-3.5", "opacity-0");
    fireEvent.load(image);
    expect(icon).toHaveClass("bg-white");
    expect(image).toHaveClass("opacity-100");
  });

  it("avoids the Moonshot halo, and insets unknown fallback images", () => {
    const view = renderIcon("moonshot");
    const icon = view.icon();
    const image = icon.querySelector("img")!;
    expectFrame(icon);
    fireEvent.load(image);
    expect(icon).toHaveClass("bg-transparent");
    expect(icon).not.toHaveClass("bg-white");
    expect(image).toHaveClass(surface === "composer" || surface === "hero" ? "h-full" : "h-5");
    fireEvent.error(image);
    expect(image).toHaveAttribute("src", providerBrand("moonshot")!.logoUrls[1]);
    expect(icon).toHaveClass("bg-muted");
    expect(image).toHaveClass("h-3.5", "w-3.5", "opacity-0");
    fireEvent.load(image);
    expect(icon).toHaveClass("bg-white");
    expect(image).toHaveClass("opacity-100");
  });

  it("falls back to initials when every URL fails", () => {
    const view = renderIcon("moonshot");
    for (const url of providerBrand("moonshot")!.logoUrls) {
      const image = view.container.querySelector("img")!;
      expect(image).toHaveAttribute("src", url);
      fireEvent.error(image);
    }
    expect(view.container).toHaveTextContent("MS");
    expect(view.container.querySelector(`img[src="${providerBrand("moonshot")!.logoUrl}"]`)).toBeNull();
  });

  if (surface === "picker" || surface === "overview") {
    it("does not show remote logos when disabled", () => {
      const view = renderIcon("moonshot", false);
      expect(view.container.querySelector("img")).toBeNull();
    });
  }
});

it("preserves the unconfigured-provider warning", () => {
  const view = render(<ProviderPickerIcon provider="moonshot" showBrandLogos unconfigured />);
  expect(view.getByTestId("provider-picker-unconfigured-icon")).toHaveClass("text-amber-700");
  expect(view.container.querySelector("img")).toBeNull();
  cleanup();
});
