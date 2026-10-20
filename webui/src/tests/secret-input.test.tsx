import { useRef, useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { SavedSecret } from "@/components/settings/SavedSecret";
import { SecretInput } from "@/components/ui/secret-input";

function Form({ disabled = false, onSubmit }: { disabled?: boolean; onSubmit: () => void }) {
  const [visible, setVisible] = useState(false);
  const [value, setValue] = useState("");
  const ref = useRef<HTMLInputElement>(null);
  return <form onSubmit={(event) => { event.preventDefault(); onSubmit(); }}>
    <SecretInput ref={ref} id="test-secret" aria-label="Password" value={value}
      autoComplete="current-password" disabled={disabled} visible={visible}
      onChange={(event) => setValue(event.target.value)}
      onToggle={() => setVisible((current) => !current)}
      toggleLabel={visible ? "Hide password" : "Show password"} toggleControls="test-secret" />
    <button type="button" onClick={() => ref.current?.focus()}>Focus password</button>
    <button type="submit">Submit</button>
  </form>;
}

it("preserves native input, focus and Enter submission while toggling only visibility", async () => {
  const onSubmit = vi.fn();
  const user = userEvent.setup();
  render(<Form onSubmit={onSubmit} />);
  const input = screen.getByLabelText("Password");
  expect(input).toHaveAttribute("autocomplete", "current-password");
  await user.type(input, "example-draft");
  await user.click(screen.getByRole("button", { name: "Show password" }));
  expect(input).toHaveAttribute("type", "text");
  expect(input).toHaveValue("example-draft");
  expect(onSubmit).toHaveBeenCalledTimes(0);
  expect(screen.getByRole("button", { name: "Hide password" })).toHaveAttribute("aria-controls", "test-secret");
  await user.click(screen.getByRole("button", { name: "Hide password" }));
  expect(input).toHaveAttribute("type", "password");
  await user.click(screen.getByRole("button", { name: "Focus password" }));
  expect(input).toHaveFocus();
  await user.keyboard("{Enter}");
  expect(onSubmit).toHaveBeenCalledTimes(1);
});

it("disables both typing and visibility", async () => {
  const user = userEvent.setup();
  render(<Form disabled onSubmit={vi.fn()} />);
  const input = screen.getByLabelText("Password");
  const toggle = screen.getByRole("button", { name: "Show password" });
  expect(input).toBeDisabled();
  expect(toggle).toBeDisabled();
  await user.type(input, "draft");
  await user.click(toggle);
  expect(input).toHaveValue("");
  expect(input).toHaveAttribute("type", "password");
});

it("opens a saved hint as an empty replacement draft", async () => {
  function Editor() {
    const [editing, setEditing] = useState(false);
    return editing ? <SecretInput aria-label="Replacement" value="" onChange={() => {}}
      visible={false} onToggle={() => {}} toggleLabel="Show replacement" />
      : <SavedSecret hint="••••masked" editLabel="Edit key" onEdit={() => setEditing(true)} />;
  }
  render(<Editor />);
  expect(screen.getByText("••••masked")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Edit key" }));
  expect(screen.getByLabelText("Replacement")).toHaveValue("");
});
