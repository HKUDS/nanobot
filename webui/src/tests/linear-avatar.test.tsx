import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { LinearAvatar } from "../../../nanobot/channels/linear/webui/LinearAvatar";

afterEach(cleanup);
describe("Linear workspace logo", () => {
  it("keeps workspace artwork uncropped without a background plate and recovers to an icon", () => {
    const view = render(<LinearAvatar workspace name="nanobot" url="https://public.linear.app/org/logo" />);
    const image = view.container.querySelector("img")!;
    expect(image).toHaveAttribute("width", "28");
    expect(image).toHaveAttribute("height", "28");
    expect(image).toHaveAttribute("referrerpolicy", "no-referrer");
    expect(image.parentElement).toHaveClass("h-7", "w-7");
    expect(image.parentElement).not.toHaveClass("overflow-hidden", "bg-muted");
    expect(image).toHaveClass("object-contain");
    expect(view.container.querySelector("svg")).toBeNull();
    fireEvent.error(image);
    expect(view.container.querySelector("img")).toBeNull();
    expect(view.container.querySelector("svg")).not.toBeNull();
    view.rerender(<LinearAvatar workspace name="nanobot" url="https://uploads.linear.app/org/new-logo" />);
    expect(view.container.querySelector("img")).toHaveAttribute("src", "https://uploads.linear.app/org/new-logo");
  });

  it.each([null, "https://untrusted.example/logo", "http://public.linear.app/logo"])(
    "uses an icon for missing or untrusted logo %s", url => {
      const view = render(<LinearAvatar workspace name="nanobot" url={url} />);
      expect(view.container.querySelector("img")).toBeNull();
      expect(view.container.querySelector("svg")).not.toBeNull();
    },
  );
});
