import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { LinearAvatar } from "../../../nanobot/channels/linear/webui/LinearAvatar";

afterEach(cleanup);
describe("Linear workspace logo", () => {
  it("loads a real CDN logo in a fixed-size square and recovers to the workspace icon", () => {
    const view = render(<LinearAvatar workspace name="nanobot" url="https://public.linear.app/org/logo" />);
    const image = view.container.querySelector("img")!;
    expect(image).toHaveAttribute("width", "36");
    expect(image).toHaveAttribute("height", "36");
    expect(image).toHaveAttribute("referrerpolicy", "no-referrer");
    expect(image.parentElement).toHaveClass("h-9", "w-9", "rounded-control");
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
