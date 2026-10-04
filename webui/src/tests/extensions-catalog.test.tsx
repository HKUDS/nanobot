import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ExtensionsCatalogSettings } from "@/components/settings/ExtensionsCatalogSettings";
import i18n from "@/i18n";

beforeEach(async () => { await i18n.changeLanguage("en"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("extensions catalog", () => {
  it("renders the installed extension count", () => {
    render(
      <ExtensionsCatalogSettings
        extensions={[
          {
            id: "query-quota",
            name: "Query Quota",
            description: "Quota dashboard",
            entry: "index.html",
            version: "0.1.0",
            enabled: true,
            config: { title: "Daily quota", limit: 100, used: 62 },
          },
          {
            id: "skill-quota",
            name: "Skill Quota",
            description: "Skill dashboard",
            entry: "index.html",
            version: "0.1.0",
            enabled: false,
            config: { skill: "query-quota" },
          },
        ]}
        onOpenExtension={vi.fn()}
      />,
    );

    expect(screen.getByText("2 installed")).toBeInTheDocument();
  });

  it("renders extension enable/disable switches instead of status text", () => {
    render(
      <ExtensionsCatalogSettings
        extensions={[{
          id: "query-quota",
          name: "Query Quota",
          description: "Quota dashboard",
          entry: "index.html",
          version: "0.1.0",
          enabled: true,
          config: { title: "Daily quota" },
        }]}
        onOpenExtension={vi.fn()}
        onToggleExtension={vi.fn()}
      />,
    );

    expect(screen.getByText(/1 enabled/i)).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: /toggle query quota/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /enable|disable/i })).not.toBeInTheDocument();
  });

  it("opens a config editor and saves edits", async () => {
    const onEdit = vi.fn().mockResolvedValue(undefined);
    render(
      <ExtensionsCatalogSettings
        extensions={[{
          id: "query-quota",
          name: "Query Quota",
          description: "Quota dashboard",
          entry: "index.html",
          version: "0.1.0",
          enabled: true,
          config: { title: "Daily quota", limit: 100, used: 62 },
        }]}
        onOpenExtension={vi.fn()}
        onEditExtension={onEdit}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Query Quota config" }));
    const dialog = await screen.findByRole("dialog", { name: "Query Quota config" });
    const editor = within(dialog).getByRole("textbox", { name: "Query Quota config" });
    fireEvent.change(editor, { target: { value: '{\n  "title": "Daily quota",\n  "limit": 120,\n  "used": 65\n}' } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(onEdit).toHaveBeenCalledWith("query-quota", { title: "Daily quota", limit: 120, used: 65 }));
    await waitFor(() => expect(dialog).not.toBeInTheDocument());
  });
});
