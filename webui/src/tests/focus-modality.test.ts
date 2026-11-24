import { afterEach, describe, expect, it } from "vitest";

import { installFocusModality } from "@/lib/focus-modality";
import { compiledGlobalCss } from "./compiled-global-css";

describe("focus modality", () => {
  const cleanups: Array<() => void> = [];

  afterEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
    document.body.innerHTML = "";
  });

  function setupModality() {
    const cleanup = installFocusModality(document);
    cleanups.push(cleanup);
    return cleanup;
  }

  it("keeps pointer modality across Shift+click, modifier keys, Escape, and shortcuts", () => {
    setupModality();
    const button = document.createElement("button");
    button.textContent = "View diff";
    document.body.append(button);

    expect(document.documentElement.dataset.focusModality).toBe("pointer");

    button.dispatchEvent(new KeyboardEvent("keydown", { key: "Shift", shiftKey: true, bubbles: true }));
    button.dispatchEvent(new MouseEvent("mousedown", { shiftKey: true, bubbles: true }));
    button.focus();
    button.dispatchEvent(new KeyboardEvent("keydown", { key: "Shift", shiftKey: true, repeat: true, bubbles: true }));
    button.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    button.dispatchEvent(new KeyboardEvent("keydown", { key: "c", ctrlKey: true, bubbles: true }));
    button.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true, bubbles: true }));
    button.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", altKey: true, bubbles: true }));

    expect(document.documentElement.dataset.focusModality).toBe("pointer");
  });

  it("enters keyboard modality on keyboard navigation and keeps it across Escape until pointer input", () => {
    setupModality();
    const button = document.createElement("button");
    document.body.append(button);
    button.focus();

    button.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }));
    expect(document.documentElement.dataset.focusModality).toBe("keyboard");

    button.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(document.documentElement.dataset.focusModality).toBe("keyboard");

    button.dispatchEvent(new MouseEvent("mousedown", { shiftKey: true, bubbles: true }));
    expect(document.documentElement.dataset.focusModality).toBe("pointer");

    button.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
    expect(document.documentElement.dataset.focusModality).toBe("keyboard");

    button.dispatchEvent(new Event("touchstart", { bubbles: true }));
    expect(document.documentElement.dataset.focusModality).toBe("pointer");

    button.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    expect(document.documentElement.dataset.focusModality).toBe("keyboard");
  });

  it("distinguishes text-entry editing from keyboard focus navigation", () => {
    setupModality();
    const input = document.createElement("input");
    const textarea = document.createElement("textarea");
    document.body.append(input, textarea);

    input.focus();
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }));
    input.dispatchEvent(new KeyboardEvent("keydown", { key: " ", bubbles: true }));
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(document.documentElement.dataset.focusModality).toBe("pointer");

    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    expect(document.documentElement.dataset.focusModality).toBe("keyboard");

    textarea.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    textarea.focus();
    textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    expect(document.documentElement.dataset.focusModality).toBe("pointer");

    textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }));
    expect(document.documentElement.dataset.focusModality).toBe("keyboard");
  });

  it("gates Tailwind focus-visible variants and base outlines on pointer modality while exempting text inputs", async () => {
    const css = await compiledGlobalCss(
      'class="focus-visible:ring-2 group-focus-visible:ring-2 peer-focus-visible:ring-2 has-focus-visible:ring-2"',
    );
    const selectors: string[] = [];
    css.walkRules((rule) => {
      if (rule.selector.includes("focus-visible")) selectors.push(rule.selector);
    });

    expect(selectors.some((selector) =>
      selector.includes(".focus-visible\\:ring-2:focus-visible:where(:root:not([data-focus-modality=\"pointer\"]) *")
      && selector.includes("textarea"),
    )).toBe(true);
    expect(selectors.some((selector) =>
      selector.includes(':where(:root:not([data-focus-modality="pointer"])) .group:focus-visible .group-focus-visible\\:ring-2'),
    )).toBe(true);
    expect(selectors.some((selector) =>
      selector.includes(':where(:root:not([data-focus-modality="pointer"])) .peer:focus-visible ~ .peer-focus-visible\\:ring-2'),
    )).toBe(true);
    expect(selectors.some((selector) =>
      selector.includes(':where(:root:not([data-focus-modality="pointer"])) .has-focus-visible\\:ring-2:has(:focus-visible)'),
    )).toBe(true);
    const pointerOutline = css.nodes.find((rule) => rule.type === "rule"
      && rule.selector.startsWith(':root[data-focus-modality="pointer"] :focus-visible:not('));
    expect(pointerOutline).toMatchObject({
      selector: expect.stringContaining("textarea"),
      nodes: expect.arrayContaining([expect.objectContaining({ prop: "outline", value: "none" })]),
    });
  });
});
