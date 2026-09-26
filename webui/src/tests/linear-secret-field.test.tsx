import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LinearSecretField } from "../../../nanobot/channels/linear/webui/LinearSecretField";

const field = { key: "channels.linear.clientSecret", label: "OAuth client secret", secret: true };
afterEach(cleanup);

function setup(onSave = vi.fn(async () => {}), configured = true) {
  const rendered = render(<LinearSecretField field={field} configured={configured} disabled={false} onSave={onSave} />);
  return { ...rendered, onSave };
}
function edit() {
  fireEvent.click(screen.getByRole("button", { name: "Replace OAuth client secret" }));
  return screen.getByLabelText("OAuth client secret", { exact: true, selector: "input" });
}

describe("Linear saved secret", () => {
  it("shows a saved status rather than an empty editable field", () => {
    setup();
    expect(screen.getByRole("status")).toHaveTextContent("Saved");
    expect(screen.getByRole("group", { name: field.label }).querySelector("input")).toBeNull();
    expect(screen.queryByRole("button", { name: "Show secret" })).not.toBeInTheDocument();
  });

  it("starts with an ordinary blank input when not configured", () => {
    const { onSave } = setup(undefined, false);
    const input = screen.getByLabelText(field.label, { exact: true, selector: "input" });
    expect(input).toHaveValue("");
    expect(input).toHaveAttribute("placeholder", "Enter secret");
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
    fireEvent.change(input, { target: { value: "   " } });
    expect(screen.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSave).not.toHaveBeenCalled();
  });

  it("does not save on blur or revealing the new draft; Escape restores saved state", () => {
    const { onSave } = setup();
    const input = edit();
    expect(input).toHaveFocus();
    fireEvent.change(input, { target: { value: "new-draft" } });
    fireEvent.blur(input);
    fireEvent.click(screen.getByRole("button", { name: "Show secret" }));
    expect(input).toHaveAttribute("type", "text");
    expect(onSave).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.getByRole("status")).toHaveTextContent("Saved");
    expect(screen.getByRole("button", { name: "Replace OAuth client secret" })).toHaveFocus();
    expect(edit()).toHaveValue("");
    expect(screen.getByLabelText(field.label, { exact: true, selector: "input" })).toHaveAttribute("type", "password");
  });

  it("keeps the editor stable during a slow save and prevents duplicate commits", async () => {
    let finish!: () => void;
    const onSave = vi.fn(() => new Promise<void>(resolve => { finish = resolve; }));
    setup(onSave);
    const input = edit();
    fireEvent.change(input, { target: { value: "new-draft" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave).toHaveBeenCalledWith(field.key, "new-draft");
    expect(input).toBeInTheDocument();
    expect(input).toHaveValue("new-draft");
    expect(screen.getByRole("group", { name: field.label })).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
    fireEvent.keyDown(input, { key: "Escape" });
    expect(input).toHaveValue("new-draft");
    await act(async () => finish());
    expect(screen.getByRole("status")).toHaveTextContent("Saved");
    expect(screen.queryByDisplayValue("new-draft")).not.toBeInTheDocument();
  });

  it("retains a failed draft for retry without exposing raw server errors", async () => {
    const onSave = vi.fn().mockRejectedValueOnce(new Error("transport: new-draft"))
      .mockResolvedValueOnce(undefined);
    setup(onSave);
    const input = edit();
    fireEvent.change(input, { target: { value: "new-draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Save", exact: true }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not confirm the save");
    expect(screen.getByRole("alert")).not.toHaveTextContent("new-draft");
    expect(input).toHaveAccessibleDescription(/Could not confirm/);
    expect(input).toHaveValue("new-draft");
    fireEvent.click(screen.getByRole("button", { name: "Save", exact: true }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Saved"));
    expect(onSave).toHaveBeenCalledTimes(2);
  });
});
