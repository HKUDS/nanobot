import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { SettingsFeature } from "@/components/settings/shared/SettingsFeature";

function FeatureFixture({ saveOnClose = false }: { saveOnClose?: boolean }) {
  const [enabled, setEnabled] = useState(false);
  const [saving, setSaving] = useState(false);
  return <SettingsFeature title="Example feature" enabled={enabled} disabled={saving}
    onChange={setEnabled} onClose={() => { if (saveOnClose) setSaving(true); }}>
    <p>Configuration</p>
  </SettingsFeature>;
}

it.each(["title", "configure", "toggle"] as const)("returns Escape to the actual %s opener", async (opener) => {
  const user = userEvent.setup();
  render(<FeatureFixture />);
  const trigger = opener === "toggle" ? screen.getByRole("switch", { name: "Example feature" })
    : screen.getByRole("button", { name: opener === "title" ? "Example feature" : "Configure" });
  await user.click(trigger);
  await screen.findByRole("dialog");
  await user.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  await waitFor(() => expect(trigger).toHaveFocus());
});

it("returns Escape to Configure when saving disables the opening switch", async () => {
  const user = userEvent.setup();
  render(<FeatureFixture saveOnClose />);
  const toggle = screen.getByRole("switch", { name: "Example feature" });
  toggle.focus();
  await user.keyboard(" ");
  await screen.findByRole("dialog");
  expect(toggle).toBeChecked();
  await user.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(toggle).toBeDisabled();
  await waitFor(() => expect(screen.getByRole("button", { name: "Configure" })).toHaveFocus());
});
