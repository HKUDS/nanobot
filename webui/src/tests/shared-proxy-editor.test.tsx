import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import { SharedProxyEditor } from "@/components/settings/shared/SharedProxyEditor";
import i18n from "@/i18n";

function editor(initial: string) {
  let current = initial;
  function Harness() {
    const [value, setValue] = useState(initial);
    return <SharedProxyEditor value={value} onChange={(next) => { current = next; setValue(next); }} />;
  }
  render(<Harness />);
  return () => current;
}

describe("Shared proxy editor", () => {
  beforeEach(async () => { await i18n.changeLanguage("en"); });

  it("shows an existing URL password only in a masked password field", () => {
    const value = editor("http://user:p%40ss@proxy:8080");
    expect(screen.getByRole("textbox", { name: "Shared proxy" })).toHaveValue("http://proxy:8080");
    expect(screen.getByRole("textbox", { name: "Username" })).toHaveValue("user");
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
    expect(screen.getByLabelText("Password")).toHaveValue("p@ss");
    fireEvent.change(screen.getByRole("textbox", { name: "Shared proxy" }), { target: { value: "http://new:8080" } });
    expect(value()).toBe("http://user:p%40ss@new:8080");
    fireEvent.click(screen.getByRole("button", { name: "Authentication (optional)" }));
    expect(value()).toBe("http://user:p%40ss@new:8080");
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
  });

  it("keeps pasted authentication out of the plain address and encodes credential edits", () => {
    const value = editor("");
    const address = screen.getByRole("textbox", { name: "Shared proxy" });
    fireEvent.change(address, { target: { value: "http://user:secret@proxy:8080" } });
    expect(address).toHaveValue("http://proxy:8080");
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "new@user" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "p:@ %密" } });
    expect(value()).toBe("http://new%40user:p%3A%40%20%25%E5%AF%86@proxy:8080");
    expect(address).toHaveValue("http://proxy:8080");
  });

  it("preserves whole-URL environment references and explains where authentication is set", () => {
    const value = editor("${FULL_PROXY}");
    fireEvent.click(screen.getByRole("button", { name: "Authentication (optional)" }));
    expect(screen.getByText("Set authentication in the referenced proxy URL.")).toBeVisible();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    expect(value()).toBe("${FULL_PROXY}");
  });
});
