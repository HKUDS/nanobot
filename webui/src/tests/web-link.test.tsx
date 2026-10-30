import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { WebLink } from "@/components/WebLink";

const href = "https://example.com/?q=one#two";

describe("browser-owned web links", () => {
  it("keeps the address, anchor attributes and caller styling", () => {
    render(<WebLink href={href} className="underline" title="Full title">Example</WebLink>);
    const link = screen.getByRole("link", { name: "Example" });
    expect(link).toHaveAttribute("href", href);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer noopener");
    expect(link).toHaveClass("underline");
    expect(link).toHaveAttribute("title", "Full title");
  });

  it.each(["mouse", "touch"])("leaves %s context menus to the browser", (pointerType) => {
    render(<WebLink href={href}>Example</WebLink>);
    const link = screen.getByRole("link", { name: "Example" });
    fireEvent.pointerDown(link, { pointerType, button: 2 });
    expect(fireEvent.contextMenu(link)).toBe(true);
  });

  it.each([{ key: "ContextMenu" }, { key: "F10", shiftKey: true }])(
    "leaves the $key keyboard menu to the browser", (event) => {
      render(<WebLink href={href}>Example</WebLink>);
      const link = screen.getByRole("link", { name: "Example" });
      link.focus();
      expect(fireEvent.keyDown(link, event)).toBe(true);
      expect(link).toHaveFocus();
    },
  );

  it.each([{}, { ctrlKey: true }, { metaKey: true }, { shiftKey: true }])(
    "preserves native navigation for click modifiers %j", (modifiers) => {
      render(<WebLink href={href}>Example</WebLink>);
      expect(fireEvent.click(screen.getByRole("link", { name: "Example" }), modifiers)).toBe(true);
    },
  );

  it.each(["http://127.1:4173/page?q=one#two", "/api/media/report.pdf", "./notes.html", "mailto:test@example.com", "tel:+1234567", "#section"])(
    "preserves supported link %s", (value) => {
      render(<WebLink href={value}>Example</WebLink>);
      expect(screen.getByRole("link", { name: "Example" })).toHaveAttribute("href", value);
    },
  );

  it.each(["javascript:alert(1)", "data:text/html,hello", "file:///etc/passwd", "https://user:password@example.com/", "https://example.com/\n", "https:\\example.com", "https://example.com/" + "x".repeat(8192)])(
    "keeps unsafe or malformed addresses as text (%#)", (value) => {
      render(<WebLink href={value}>Example</WebLink>);
      expect(screen.getByText("Example")).toBeVisible();
      expect(screen.queryByRole("link")).not.toBeInTheDocument();
    },
  );
});
