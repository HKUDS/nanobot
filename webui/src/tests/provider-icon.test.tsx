import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ProviderIcon } from "@/components/settings/models/ProviderSettings";
import { __clearLogoFallbackCacheForTests } from "@/hooks/useLogoFallback";
import { providerBrand } from "@/lib/provider-brand";

describe("settings provider icons", () => {
  beforeEach(__clearLogoFallbackCacheForTests);
  afterEach(cleanup);

  function expectFootprint(icon: Element) {
    expect(icon).toHaveClass("h-8", "w-8", "shrink-0", "overflow-hidden", "rounded-[9px]");
    expect(icon.className.split(/\s+/).some((value) => value.startsWith("border"))).toBe(false);
  }

  it.each([
    "openai_codex", "anthropic", "deepseek", "gemini", "xai_grok", "longcat", "openrouter", "github_copilot",
    "edenai", "opencode", "opencode_zen", "opencode_go", "kimi_coding",
  ])(
    "shows %s on a single white tile with a small inset after loading",
    (provider) => {
      const { container } = render(<ProviderIcon provider={provider} showBrandLogos />);
      const icon = container.firstElementChild!;
      const image = icon.querySelector("img")!;
      const fallback = icon.querySelector("span")!;

      expectFootprint(icon);
      expect(icon).toHaveClass("bg-muted");
      expect(fallback).toHaveTextContent(providerBrand(provider)!.initials);
      expect(fallback).toHaveClass("opacity-100");
      expect(image).toHaveClass("h-6", "w-6", "object-contain", "opacity-0");
      expect(image).toHaveAttribute("alt", "");

      fireEvent.load(image);

      expectFootprint(icon);
      expect(icon).toHaveClass("bg-white");
      expect(icon).not.toHaveClass("bg-muted");
      expect(icon).not.toHaveAttribute("style");
      expect(fallback).toHaveClass("opacity-0");
      expect(image).toHaveClass("opacity-100");
      expect(image).not.toHaveClass("invert", "grayscale");
    },
  );

  it.each([
    "aihubmix", "bedrock", "exa", "groq", "lm_studio", "minimax", "minimax_anthropic",
    "modelscope", "moonshot", "olostep", "tavily", "xiaomi_mimo", "zhipu",
  ])(
    "does not double-frame %s's primary tile, but preserves unknown fallback assets",
    (provider) => {
      const { container } = render(<ProviderIcon provider={provider} showBrandLogos />);
      const icon = container.firstElementChild!;
      const image = icon.querySelector("img")!;
      expectFootprint(icon);
      expect(image).toHaveAttribute("src", providerBrand(provider)!.logoUrl);
      expect(image).toHaveClass("h-8", "w-8", "object-contain", "opacity-0");

      fireEvent.load(image);
      expect(image).toHaveClass("opacity-100");
      expect(icon).toHaveClass("bg-transparent");
      expect(icon).not.toHaveClass("bg-white", "bg-muted");

      fireEvent.error(image);
      expect(image).toHaveAttribute("src", providerBrand(provider)!.logoUrls[1]);
      expect(image).toHaveClass("h-6", "w-6", "object-contain", "opacity-0");
      expect(icon).toHaveClass("bg-muted");
      fireEvent.load(image);
      expectFootprint(icon);
      expect(image).toHaveClass("h-6", "w-6", "opacity-100");
      expect(icon).toHaveClass("bg-white");
      expect(icon).not.toHaveClass("bg-transparent");
    },
  );

  it("keeps its placeholder through alternate URLs and complete image failure", () => {
    const { container } = render(<ProviderIcon provider="openai_codex" showBrandLogos />);
    const icon = container.firstElementChild!;
    const fallback = icon.querySelector("span")!;

    for (const url of providerBrand("openai_codex")!.logoUrls) {
      const image = icon.querySelector("img")!;
      expect(image).toHaveAttribute("src", url);
      expect(image).toHaveClass("opacity-0");
      fireEvent.error(image);
      expect(container.firstElementChild).toBe(icon);
      expectFootprint(icon);
      expect(icon).toHaveClass("bg-muted");
      expect(fallback).toHaveClass("opacity-100");
    }

    expect(icon.querySelector("img")).toBeNull();
    expect(fallback).toHaveTextContent("AI");
    expect(icon).toHaveAttribute("aria-hidden", "true");
  });

  it("respects disabled brand logos without changing footprint, including cached logos", () => {
    const { container, rerender } = render(<ProviderIcon provider="openai_codex" showBrandLogos />);
    const icon = container.firstElementChild!;
    fireEvent.load(icon.querySelector("img")!);

    rerender(<ProviderIcon provider="openai_codex" showBrandLogos={false} />);
    expect(container.firstElementChild).toBe(icon);
    expectFootprint(icon);
    expect(icon).toHaveClass("bg-muted");
    expect(icon.querySelector("img")).toBeNull();
    expect(icon.querySelector("svg")).not.toBeNull();
    expect(icon).not.toHaveTextContent("AI");

    rerender(<ProviderIcon provider="openai_codex" showBrandLogos />);
    expectFootprint(icon);
    expect(icon).toHaveClass("bg-white");
    expect(icon.querySelector("img")).toHaveClass("opacity-100");
  });

  it("uses the same footprint for unknown and custom providers", () => {
    const { container, rerender } = render(<ProviderIcon provider="custom" showBrandLogos />);
    expectFootprint(container.firstElementChild!);
    expect(container.firstElementChild).toHaveClass("bg-muted");
    expect(container.firstElementChild).not.toHaveClass("bg-white");
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("svg")).not.toBeNull();

    rerender(<ProviderIcon provider="my-provider" showBrandLogos />);
    expectFootprint(container.firstElementChild!);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("svg")).not.toBeNull();
  });
});
