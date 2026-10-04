import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SettingsTextEditor } from "@/components/settings/shared/SettingsTextEditor";
import i18n from "@/i18n";

beforeEach(async () => { await i18n.changeLanguage("en"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("settings text editor copy", () => {
  it.each([undefined, "", "  ", "Headers", " Headers "])(
    "does not repeat its title as a description (%s)", async (description) => {
      const warning = vi.spyOn(console, "warn");
      render(<SettingsTextEditor title="Headers" description={description} value="{}" onSave={vi.fn()} />);
      fireEvent.click(screen.getByRole("button", { name: "Headers" }));
      const dialog = await screen.findByRole("dialog", { name: "Headers" });
      expect(within(dialog).getAllByText("Headers")).toHaveLength(1);
      expect(dialog).not.toHaveAttribute("aria-describedby");
      expect(dialog).toHaveAccessibleDescription("");
      expect(within(dialog).getByRole("textbox", { name: "Headers" })).toHaveValue("{}");
      expect(within(dialog).getByRole("textbox", { name: "Headers" })).toHaveFocus();
      expect(warning).not.toHaveBeenCalled();
    },
  );

  it("keeps meaningful help associated with the dialog and saves edited values", async () => {
    const warning = vi.spyOn(console, "warn");
    const save = vi.fn();
    const help = "Use a JSON object for additional request headers.";
    render(<SettingsTextEditor title="Headers" description={help} value="{}" onSave={save} />);
    fireEvent.click(screen.getByRole("button", { name: "Headers" }));
    const dialog = await screen.findByRole("dialog", { name: "Headers" });
    expect(dialog).toHaveAccessibleDescription(help);
    expect(within(dialog).getAllByText(help)).toHaveLength(1);
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Headers" }), { target: { value: '{"Accept":"application/json"}' } });
    fireEvent.click(within(dialog).getByRole("button", { name: i18n.t("settings.actions.save"), exact: true }));
    expect(save).toHaveBeenCalledWith('{"Accept":"application/json"}');
    await waitFor(() => expect(dialog).not.toBeInTheDocument());
    expect(warning).not.toHaveBeenCalled();
  });
});
