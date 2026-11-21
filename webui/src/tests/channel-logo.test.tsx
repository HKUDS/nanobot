import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { channelUiPresentation, registeredChannelUiContributions } from "@/channel-plugins/registry";
import { ChannelLogo } from "@/components/settings/channels/ChannelIdentity";
import { __clearLogoFallbackCacheForTests } from "@/hooks/useLogoFallback";
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

  const channelsWithBrandMarks = registeredChannelUiContributions()
    .filter(({ contribution }) => contribution.presentation.logoUrl)
    .map(({ channel }) => channel);

  it.each(channelsWithBrandMarks)("loads the bundled %s mark in one stable tile", (channel) => {
    const { container } = render(<ChannelLogo feature={feature(channel)} showBrandLogos />);
    const icon = container.firstElementChild!;
    const image = icon.querySelector("img")!;
    const fallback = icon.querySelector("span")!;
    const presentation = channelUiPresentation(channel)!;

    expectFootprint(icon);
    expect(icon).toHaveClass("bg-muted");
    expect(fallback).toHaveClass("opacity-100");
    expect(presentation.logoUrl).toMatch(/^\/brand\//);
    expect(image).toHaveAttribute("src", presentation.logoUrl);
    expect(image).toHaveAttribute("alt", "");
    expect(image).toHaveAttribute("referrerpolicy", "no-referrer");
    expect(image).toHaveClass("object-contain", "opacity-0");

    fireEvent.load(image);

    expectFootprint(icon);
    expect(fallback).toHaveClass("opacity-0");
    expect(image).toHaveClass("opacity-100");
    for (const className of ["invert", "grayscale", "object-cover"]) {
      expect(image).not.toHaveClass(className);
    }
    expect(icon).toHaveClass("bg-white");
    expect(image).toHaveClass("h-6", "w-6");
  });

  it.each(["dingtalk", "feishu", "lark", "mochat", "msteams", "napcat", "slack", "wecom"])(
    "shows %s initials without an external image when there is no bundled mark",
    (channel) => {
      const { container } = render(<ChannelLogo feature={feature(channel)} showBrandLogos />);
      const icon = container.firstElementChild!;
      expectFootprint(icon);
      expect(icon).toHaveTextContent(channelUiPresentation(channel)!.initials!);
      expect(icon.querySelector("img")).toBeNull();
    },
  );

  it("keeps QQ readable when its bundled SVG fails, without requesting another image", () => {
    const { container } = render(<ChannelLogo feature={feature("qq")} showBrandLogos />);
    const icon = container.firstElementChild!;
    const image = icon.querySelector("img")!;
    expect(image).toHaveAttribute("src", "/brand/channels/qq.svg");
    fireEvent.error(image);
    expect(container.firstElementChild).toBe(icon);
    expectFootprint(icon);
    expect(icon).toHaveClass("bg-muted");
    expect(icon.querySelector("span")).toHaveClass("opacity-100");
    expect(icon).toHaveTextContent("QQ");
    expect(icon.querySelector("img")).toBeNull();
  });

  it("respects the brand logo preference even for cached images", () => {
    const { container, rerender } = render(<ChannelLogo feature={feature("linear")} showBrandLogos />);
    const icon = container.firstElementChild!;
    fireEvent.load(icon.querySelector("img")!);

    rerender(<ChannelLogo feature={feature("linear")} showBrandLogos={false} />);
    expectFootprint(icon);
    expect(icon.querySelector("img")).toBeNull();
    expect(icon).toHaveClass("bg-muted");
    expect(icon.querySelector("span")).toHaveClass("opacity-100");

    rerender(<ChannelLogo feature={feature("linear")} showBrandLogos />);
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
