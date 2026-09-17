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
    fireEvent.click(within(dialog).getByRole("button", { name: "Reload tools" }));
    expect(onAction).toHaveBeenCalledTimes(2);
  });
});

function renderDialog({
  initialTab,
  onAction = vi.fn(),
  onToolsChange = vi.fn(),
  preset = connectedPreset,
}: {
  initialTab: McpManagementTab;
  onAction?: ReturnType<typeof vi.fn>;
  onToolsChange?: ReturnType<typeof vi.fn>;
  preset?: McpPresetInfo;
}) {
  function Harness() {
    const [tab, setTab] = useState(initialTab);
    return (
      <McpManagementDialog
        preset={preset}
        values={{}}
        actionKey={null}
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
  return render(<Harness />);
}
