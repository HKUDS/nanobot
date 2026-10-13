import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SyntaxHighlighter from "react-syntax-highlighter/dist/esm/prism-light";
import markup from "react-syntax-highlighter/dist/esm/languages/prism/markup";
import oneLight from "react-syntax-highlighter/dist/esm/styles/prism/one-light";

import { ViewportCodeRows } from "@/components/ViewportCodeRows";

SyntaxHighlighter.registerLanguage("markup", markup);

let notify: IntersectionObserverCallback;
const disconnect = vi.fn();
const observe = vi.fn();
function showChunks(indices: number[]) {
  const entries = [...document.querySelectorAll<HTMLElement>("[data-code-chunk]")]
    .map(target => ({ target, isIntersecting: indices.includes(Number(target.dataset.codeChunk)) }));
  act(() => notify(entries as IntersectionObserverEntry[], {} as IntersectionObserver));
}
function sourceText() {
  return [...document.querySelectorAll("[data-highlighted]")].map(node => node.textContent).join("");
}
function preview(code: string) {
  return <div data-file-preview-scroll><SyntaxHighlighter language="markup" style={oneLight}
    renderer={props => <ViewportCodeRows {...props} />}>{code}</SyntaxHighlighter></div>;
}

describe("viewport code highlighting", () => {
  beforeEach(() => {
    vi.stubGlobal("IntersectionObserver", class {
      constructor(callback: IntersectionObserverCallback) { notify = callback; }
      observe = observe;
      disconnect = disconnect;
    });
    observe.mockClear();
    disconnect.mockClear();
  });
  afterEach(() => {
    act(() => document.getSelection()?.removeAllRanges());
    vi.unstubAllGlobals();
  });

  it("keeps all text in the DOM while limiting highlighted rows, including a jump to the end", () => {
    const code = Array.from({ length: 602 }, (_, index) => `<p>Line ${index} 😀</p>`).join("\n");
    const { container, unmount } = render(preview(code));
    expect(sourceText()).toBe(code);
    expect(observe).toHaveBeenCalledTimes(16);
    expect(container.querySelectorAll("*").length).toBeLessThan(1000);
    showChunks([15]);
    expect(container.querySelector('[data-code-chunk="0"] [data-highlighted]')).toHaveAttribute("data-highlighted", "false");
    expect(container.querySelector('[data-code-chunk="15"] [data-highlighted]')).toHaveAttribute("data-highlighted", "true");
    expect(sourceText()).toBe(code);
    expect(container.querySelectorAll("*").length).toBeLessThan(1000);
    unmount();
    expect(disconnect).toHaveBeenCalledOnce();
  });

  it("retains multiline syntax context across offscreen chunk boundaries and escapes source", () => {
    const code = "<!--\n" + "comment\n".repeat(79) + "-->\n<script>alert('not executed')</script>\n<img onerror='bad()'>";
    const { container } = render(preview(code));
    showChunks([1]);
    const middle = container.querySelector('[data-code-chunk="1"] [data-highlighted]');
    expect(middle?.querySelector("span[style]" )?.getAttribute("style")).toContain("italic");
    expect(sourceText()).toBe(code);
    showChunks([2]);
    expect(container.querySelector("script, img")).toBeNull();
    expect(sourceText()).toBe(code);
  });

  it("does not replace token nodes underneath an active text selection", () => {
    render(preview("<p>Sample</p>\n".repeat(120)));
    const root = screen.getByTestId("viewport-code-rows");
    const first = root.querySelector('[data-highlighted="true"]')!;
    const range = document.createRange();
    range.selectNodeContents(first);
    const selection = document.getSelection()!;
    act(() => selection.addRange(range));
    showChunks([2]);
    expect(first).toHaveAttribute("data-highlighted", "true");
    expect(selection.toString()).toContain("Sample");
    act(() => { selection.removeAllRanges(); document.dispatchEvent(new Event("selectionchange")); });
    expect(first).toHaveAttribute("data-highlighted", "false");
    expect(root.querySelector('[data-code-chunk="2"] [data-highlighted]')).toHaveAttribute("data-highlighted", "true");
  });

  it("falls back to full readable text when IntersectionObserver is unavailable", () => {
    vi.stubGlobal("IntersectionObserver", undefined);
    const code = "<p>Sample</p>\n".repeat(120);
    render(preview(code));
    expect(sourceText()).toBe(code);
  });
});
