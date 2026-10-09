import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  McpManagementDialog,
  type McpManagementTab,
} from "@/components/settings/system/McpManagementDialog";
import i18n from "@/i18n";
import type { McpPresetInfo } from "@/lib/types";

const connectedPreset: McpPresetInfo = {
  name: "docs",
  display_name: "Docs MCP",
  category: "productivity",
  description: "Search and maintain the team knowledge base.",
  docs_url: "https://example.com/docs-mcp",
  transport: "streamableHttp",
  auth: null,
  requires: "",
  note: "",
  install_supported: true,
  installed: true,
  configured: true,
  available: true,
  status: "configured",
  runtime_status: "connected",
  required_fields: [],
  connection_summary: "https://mcp.example.com/mcp",
  tool_count: 3,
  tool_names: ["search_docs", "write_note", "list_sources"],
  enabled_tools: ["*"],
  checked_at: "2026-08-12T08:00:00Z",
  source: "custom",
};

describe("McpManagementDialog", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  it("keeps tool scope changes as a draft until Save changes", () => {
    const onToolsChange = vi.fn();
    renderDialog({ initialTab: "tools", onToolsChange });

    const dialog = screen.getByRole("dialog", { name: "Docs MCP" });
    expect(dialog).toHaveClass("h-[min(34rem,calc(100dvh-2rem))]");
    expect(within(dialog).getByRole("tab", { name: /Tools/ })).toHaveAttribute("aria-selected", "true");
    expect(within(dialog).getByText("3 enabled")).toBeInTheDocument();
    expect(within(dialog).queryByText("Close")).not.toBeInTheDocument();

    const searchDocs = within(dialog).getByRole("checkbox", { name: /search_docs/ });
    expect(searchDocs).toBeChecked();
    fireEvent.click(searchDocs);

    expect(searchDocs).not.toBeChecked();
    expect(within(dialog).getByText("2 enabled")).toBeInTheDocument();
    expect(onToolsChange).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));
    expect(onToolsChange).toHaveBeenCalledWith("docs", ["write_note", "list_sources"]);
  });

  it("searches the inventory and exposes connection management in the same modal", () => {
    const onAction = vi.fn();
    renderDialog({ initialTab: "tools", onAction });

    const dialog = screen.getByRole("dialog", { name: "Docs MCP" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Search tools" }), {
      target: { value: "write" },
    });
    expect(within(dialog).getByRole("checkbox", { name: /write_note/ })).toBeInTheDocument();
    expect(within(dialog).queryByRole("checkbox", { name: /search_docs/ })).not.toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("tab", { name: "Connection" }));
    expect(within(dialog).getByText("https://mcp.example.com/mcp")).toBeInTheDocument();
    expect(within(dialog).getByText("Streamable HTTP")).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "Open docs" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Remove connection" })).toBeInTheDocument();
    expect(within(dialog).queryByText("Last checked")).not.toBeInTheDocument();
    expect(within(dialog).queryByText("Connection actions apply immediately.")).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Reconnect" }));
    expect(onAction).toHaveBeenCalledWith("reconnect", "docs", {});
  });

  it("loads tools on entry and replaces passive inspection copy with recovery", async () => {
    const onAction = vi.fn();
    renderDialog({
      initialTab: "tools",
      onAction,
      preset: { ...connectedPreset, tool_count: 0, tool_names: [], enabled_tools: ["*"] },
    });

    const dialog = screen.getByRole("dialog", { name: "Docs MCP" });
    await waitFor(() => expect(onAction).toHaveBeenCalledWith("test", "docs"));
    expect(within(dialog).queryByText("Not inspected")).not.toBeInTheDocument();
    expect(within(dialog).getByText("No tools available")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Refresh tools" }));
    expect(onAction).toHaveBeenCalledTimes(2);
  });

  it("lets users inspect an app and open its tool scope without changing the connection", () => {
    const onAction = vi.fn();
    renderDialog({ initialTab: "overview", onAction });
    const dialog = screen.getByRole("dialog", { name: "Docs MCP" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Tools 3 / 3" }));
    expect(within(dialog).getByRole("tab", { name: "Tools" })).toHaveAttribute("aria-selected", "true");
    expect(within(dialog).getByRole("checkbox", { name: /search_docs/ })).toBeChecked();
    expect(onAction).not.toHaveBeenCalled();
  });

  it("shows a skeleton for the first inspection and keeps tools and draft selections during reinspection", () => {
    const emptyPreset = { ...connectedPreset, tool_count: 0, tool_names: [] };
    const { updateDialog } = renderDialog({
      initialTab: "tools",
      preset: emptyPreset,
      actionKey: "test:docs",
    });

    const dialog = screen.getByRole("dialog", { name: "Docs MCP" });
    expect(within(dialog).getByRole("status", { name: "Loading tools…" })).toHaveAttribute("aria-busy", "true");
    expect(within(dialog).queryByRole("textbox", { name: "Search tools" })).not.toBeInTheDocument();
    expect(within(dialog).queryByText("No tools available")).not.toBeInTheDocument();

    updateDialog(connectedPreset);
    expect(within(dialog).queryByRole("status", { name: "Loading tools…" })).not.toBeInTheDocument();
    const searchDocs = within(dialog).getByRole("checkbox", { name: /search_docs/ });
    fireEvent.click(searchDocs);
    expect(searchDocs).not.toBeChecked();

    updateDialog({ ...connectedPreset, tool_names: [] }, "test:docs");
    expect(within(dialog).queryByRole("status", { name: "Loading tools…" })).not.toBeInTheDocument();
    expect(within(dialog).getByRole("checkbox", { name: /search_docs/ })).not.toBeChecked();
    expect(within(dialog).getByRole("checkbox", { name: /write_note/ })).toBeChecked();
    expect(within(dialog).getByText("2 enabled")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Save changes" })).toBeEnabled();
  });

  it.each([
    { error: undefined, message: "No tools available" },
    { error: "Inspection failed", message: "Inspection failed" },
  ])("offers recovery when inspection finishes with $message", ({ error, message }) => {
    const onAction = vi.fn();
    const emptyPreset = { ...connectedPreset, tool_count: 0, tool_names: [], error };
    const { updateDialog } = renderDialog({
      initialTab: "tools",
      preset: emptyPreset,
      actionKey: "test:docs",
      onAction,
    });

    const dialog = screen.getByRole("dialog", { name: "Docs MCP" });
    expect(within(dialog).getByRole("status", { name: "Loading tools…" })).toBeInTheDocument();
    updateDialog(emptyPreset);
    expect(within(dialog).queryByRole("status", { name: "Loading tools…" })).not.toBeInTheDocument();
    expect(within(dialog).getByText(message)).toBeInTheDocument();
    if (error) expect(within(dialog).getByRole("alert")).toHaveTextContent(error);
    fireEvent.click(within(dialog).getByRole("button", { name: "Refresh tools" }));
    expect(onAction).toHaveBeenLastCalledWith("test", "docs");
  });
});

function renderDialog({
  initialTab,
  onAction = vi.fn(),
  onToolsChange = vi.fn(),
  preset = connectedPreset,
  actionKey = null,
}: {
  initialTab: McpManagementTab;
  onAction?: ReturnType<typeof vi.fn>;
  onToolsChange?: ReturnType<typeof vi.fn>;
  preset?: McpPresetInfo;
  actionKey?: string | null;
}) {
  function Harness({ preset, actionKey }: { preset: McpPresetInfo; actionKey: string | null }) {
    const [tab, setTab] = useState(initialTab);
    return (
      <McpManagementDialog
        preset={preset}
        values={{}}
        actionKey={actionKey}
        statusLabel="Connected"
        statusTone="success"
        tab={tab}
        icon={<span aria-hidden>DM</span>}
        onTabChange={setTab}
        onOpenChange={vi.fn()}
        onFieldChange={vi.fn()}
        onAction={onAction}
        onOAuthConnect={vi.fn()}
        onToolsChange={onToolsChange}
      />
    );
  }
  const view = render(<Harness preset={preset} actionKey={actionKey} />);
  return {
    ...view,
    updateDialog: (nextPreset: McpPresetInfo, nextActionKey: string | null = null) => {
      view.rerender(<Harness preset={nextPreset} actionKey={nextActionKey} />);
    },
  };
}
