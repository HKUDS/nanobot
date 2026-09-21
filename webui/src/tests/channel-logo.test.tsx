import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { channelUiPresentation, registeredChannelUiContributions } from "@/channel-plugins/registry";
import { ChannelLogo } from "@/components/settings/channels/ChannelIdentity";
import { __clearLogoFallbackCacheForTests } from "@/hooks/useLogoFallback";
import { logoFallbackUrls } from "@/lib/provider-brand";
import type { NanobotFeatureInfo } from "@/lib/types";

function feature(name: string): NanobotFeatureInfo {
  return {
    name,
    display_name: channelUiPresentation(name)?.displayName ?? name,
    type: "channel",
    enabled: false,
    installed: true,
    ready: true,
    status: "not_enabled",
    install_supported: false,
    requires_restart: false,
  };
}

function expectFootprint(icon: Element) {
  expect(icon).toHaveClass("h-8", "w-8", "shrink-0", "overflow-hidden", "rounded-[9px]");
  expect(icon).toHaveAttribute("aria-hidden", "true");
  expect(icon.className.split(/\s+/).some((value) => value.startsWith("border"))).toBe(false);
}

describe("channel logos", () => {
  beforeEach(__clearLogoFallbackCacheForTests);
  afterEach(cleanup);

  const remoteChannels = registeredChannelUiContributions()
    .filter(({ contribution }) => contribution.presentation.logoUrl)
    .map(({ channel }) => channel);

  it.each(remoteChannels)("keeps %s in one stable tile while loading", (channel) => {
    const { container } = render(<ChannelLogo feature={feature(channel)} showBrandLogos />);
    const icon = container.firstElementChild!;
    const image = icon.querySelector("img")!;
    const fallback = icon.querySelector("span")!;
    const presentation = channelUiPresentation(channel)!;

    expectFootprint(icon);
    expect(icon).toHaveClass("bg-muted");
    expect(fallback).toHaveClass("opacity-100");
    expect(image).toHaveAttribute("src", presentation.logoUrl);
    expect(image).toHaveAttribute("alt", "");
    expect(image).toHaveAttribute("referrerpolicy", "no-referrer");
    expect(image).toHaveClass("object-contain", "opacity-0");

    fireEvent.load(image);

    expectFootprint(icon);
    expect(fallback).toHaveClass("opacity-0");
    expect(image).toHaveClass("opacity-100");
    expect(image).not.toHaveClass("invert", "grayscale", "object-cover");
    expect(icon).toHaveClass(presentation.logoLayout === "tile" ? "bg-transparent" : "bg-white");
    expect(image).toHaveClass(...(presentation.logoLayout === "tile" ? ["h-8", "w-8"] : ["h-6", "w-6"]));
  });

  it.each(["linear", "feishu", "lark"])("insets unknown %s fallback assets instead of stretching them", (channel) => {
    const { container } = render(<ChannelLogo feature={feature(channel)} showBrandLogos />);
    const icon = container.firstElementChild!;
    const image = icon.querySelector("img")!;
    fireEvent.load(image);
    expect(icon).toHaveClass("bg-transparent");
    expect(image).toHaveClass("h-8", "w-8");

    fireEvent.error(image);
    expect(icon).toHaveClass("bg-muted");
    expect(image).toHaveClass("h-6", "w-6", "opacity-0");
    fireEvent.load(image);
    expect(icon).toHaveClass("bg-white");
    expectFootprint(icon);
  });

  it("falls back to initials after all remote sources fail without changing size", () => {
    const { container } = render(<ChannelLogo feature={feature("slack")} showBrandLogos />);
    const icon = container.firstElementChild!;
    for (const url of logoFallbackUrls(channelUiPresentation("slack")!.logoUrl)) {
      const image = icon.querySelector("img")!;
      expect(image).toHaveAttribute("src", url);
      fireEvent.error(image);
      expect(container.firstElementChild).toBe(icon);
      expectFootprint(icon);
      expect(icon).toHaveClass("bg-muted");
      expect(icon.querySelector("span")).toHaveClass("opacity-100");
    }
    expect(icon.querySelector("img")).toBeNull();
    expect(icon).toHaveTextContent(channelUiPresentation("slack")!.initials!);
  });

  it("respects the brand logo preference even for cached images", () => {
    const { container, rerender } = render(<ChannelLogo feature={feature("slack")} showBrandLogos />);
    const icon = container.firstElementChild!;
    fireEvent.load(icon.querySelector("img")!);

    rerender(<ChannelLogo feature={feature("slack")} showBrandLogos={false} />);
    expectFootprint(icon);
    expect(icon.querySelector("img")).toBeNull();
    expect(icon).toHaveClass("bg-muted");
    expect(icon.querySelector("span")).toHaveClass("opacity-100");

    rerender(<ChannelLogo feature={feature("slack")} showBrandLogos />);
    expect(icon.querySelector("img")).toHaveClass("opacity-100");
    expect(icon).toHaveClass("bg-white");
  });

  it("uses a generic envelope for Email without requesting a vendor logo", () => {
    const { container } = render(<ChannelLogo feature={feature("email")} showBrandLogos />);
    expectFootprint(container.firstElementChild!);
    expect(container.querySelector("svg.lucide-mail")).not.toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(channelUiPresentation("email")?.logoUrl).toBeUndefined();
  });

  it("falls back to QQ's official favicon rather than its CDN's identity", () => {
    const { container } = render(<ChannelLogo feature={feature("qq")} showBrandLogos />);
    const image = container.querySelector("img")!;
    expect(image).toHaveAttribute("src", channelUiPresentation("qq")!.logoUrl);
    fireEvent.error(image);
    expect(image).toHaveAttribute("src", "https://im.qq.com/favicon.ico");
    fireEvent.load(image);
    expect(container.firstElementChild).toHaveClass("bg-white");
  });

  it("keeps the local nanobot mark and unknown channel initials readable", () => {
    const { container, rerender } = render(<ChannelLogo feature={feature("websocket")} showBrandLogos />);
    expectFootprint(container.firstElementChild!);
    expect(container.querySelector("img")).toHaveAttribute("src", "/brand/nanobot_mark.svg");

    rerender(<ChannelLogo feature={feature("custom-channel")} showBrandLogos />);
    expectFootprint(container.firstElementChild!);
    expect(container.firstElementChild).toHaveTextContent("CU");
    expect(container.querySelector("img")).toBeNull();
  });
});
