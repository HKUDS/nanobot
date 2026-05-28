import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AgentActivityCluster } from "@/components/thread/AgentActivityCluster";
import type { CliAppInfo, McpPresetInfo, UIMessage } from "@/lib/types";

const BLENDER_CLI_APP: CliAppInfo = {
  name: "blender",
  display_name: "Blender",
  category: "3d",
  description: "3D creation",
  requires: "",
  source: "harness",
  entry_point: "cli-anything-blender",
  install_supported: true,
  installed: true,
  available: true,
  status: "installed",
  logo_url: "https://example.invalid/blender.svg",
  brand_color: "#E87D0D",
  skill_installed: true,
};

const BROWSERBASE_MCP: McpPresetInfo = {
  name: "browserbase",
  display_name: "Browserbase",
  category: "browser",
  description: "Cloud browser automation",
  docs_url: "https://docs.browserbase.com",
  transport: "streamableHttp",
  requires: "Browserbase API key",
  note: "",
  install_supported: true,
  installed: true,
  configured: true,
  available: true,
  status: "configured",
  logo_url: "https://example.invalid/browserbase.svg",
  brand_color: "#111827",
  required_fields: [],
  connection_summary: "https://mcp.browserbase.com/mcp",
};

function activityMessages(extraReasoning = "", extraTool?: UIMessage): UIMessage[] {
  const rows: UIMessage[] = [
    {
      id: "r1",
      role: "assistant",
      content: "",
      reasoning: `thinking${extraReasoning}`,
      reasoningStreaming: true,
      isStreaming: true,
      createdAt: 1,
    },
    {
      id: "t1",
      role: "tool",
      kind: "trace",
      content: "search()",
      traces: ["search()"],
      createdAt: 2,
    },
  ];
  if (extraTool) rows.push(extraTool);
  return rows;
}

function installAnimationFrameQueue() {
  const originalRequest = window.requestAnimationFrame;
  const originalCancel = window.cancelAnimationFrame;
  const callbacks = new Map<number, FrameRequestCallback>();
  let nextId = 1;

  window.requestAnimationFrame = ((callback: FrameRequestCallback) => {
    const id = nextId;
    nextId += 1;
    callbacks.set(id, callback);
    return id;
  }) as typeof window.requestAnimationFrame;
  window.cancelAnimationFrame = ((id: number) => {
    callbacks.delete(id);
  }) as typeof window.cancelAnimationFrame;

  return {
    flush() {
      const pending = Array.from(callbacks.entries());
      callbacks.clear();
      for (const [, callback] of pending) callback(0);
    },
    restore() {
      window.requestAnimationFrame = originalRequest;
      window.cancelAnimationFrame = originalCancel;
    },
  };
}

function setScrollGeometry(
  element: HTMLElement,
  geometry: { scrollHeight: number; clientHeight: number; scrollTop?: number },
) {
  Object.defineProperties(element, {
    scrollHeight: { configurable: true, value: geometry.scrollHeight },
    clientHeight: { configurable: true, value: geometry.clientHeight },
    scrollTop: {
      configurable: true,
      value: geometry.scrollTop ?? element.scrollTop,
      writable: true,
    },
  });
}

function installReducedMotion() {
  const original = window.matchMedia;
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: () => ({
      matches: true,
      media: "(prefers-reduced-motion: reduce)",
      addEventListener: () => {},
      removeEventListener: () => {},
    }),
  });
  return () => {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: original,
    });
  };
}

describe("AgentActivityCluster", () => {
  it("jumps to the latest activity when opened", () => {
    const raf = installAnimationFrameQueue();
    try {
      render(
        <AgentActivityCluster
          messages={activityMessages()}
          isTurnStreaming
          hasBodyBelow={false}
        />,
      );

      const scrollport = screen.getByTestId("agent-activity-scroll");
      setScrollGeometry(scrollport, {
        scrollHeight: 1000,
        clientHeight: 120,
        scrollTop: 0,
      });

      act(() => {
        raf.flush();
      });

      expect(scrollport.scrollTop).toBe(880);
    } finally {
      raf.restore();
    }
  });

  it("follows new reasoning and tool activity while the user is at the bottom", () => {
    const raf = installAnimationFrameQueue();
    try {
      const { rerender } = render(
        <AgentActivityCluster
          messages={activityMessages()}
          isTurnStreaming
          hasBodyBelow={false}
        />,
      );

      const scrollport = screen.getByTestId("agent-activity-scroll");
      setScrollGeometry(scrollport, {
        scrollHeight: 1000,
        clientHeight: 120,
        scrollTop: 0,
      });
      act(() => {
        raf.flush();
      });

      rerender(
        <AgentActivityCluster
          messages={activityMessages(" with more detail", {
            id: "t2",
            role: "tool",
            kind: "trace",
            content: "open_browser()",
            traces: ["open_browser()"],
            createdAt: 3,
          })}
          isTurnStreaming
          hasBodyBelow={false}
        />,
      );
      setScrollGeometry(scrollport, {
        scrollHeight: 1500,
        clientHeight: 120,
        scrollTop: scrollport.scrollTop,
      });

      act(() => {
        raf.flush();
      });

      expect(scrollport.scrollTop).toBe(1380);
    } finally {
      raf.restore();
    }
  });

  it("does not pull the user down after they scroll up inside the activity pane", () => {
    const raf = installAnimationFrameQueue();
    try {
      const { rerender } = render(
        <AgentActivityCluster
          messages={activityMessages()}
          isTurnStreaming
          hasBodyBelow={false}
        />,
      );

      const scrollport = screen.getByTestId("agent-activity-scroll");
      setScrollGeometry(scrollport, {
        scrollHeight: 1000,
        clientHeight: 120,
        scrollTop: 0,
      });
      act(() => {
        raf.flush();
      });

      scrollport.scrollTop = 100;
      fireEvent.scroll(scrollport);

      rerender(
        <AgentActivityCluster
          messages={activityMessages(" still streaming")}
          isTurnStreaming
          hasBodyBelow={false}
        />,
      );
      setScrollGeometry(scrollport, {
        scrollHeight: 1500,
        clientHeight: 120,
        scrollTop: scrollport.scrollTop,
      });

      act(() => {
        raf.flush();
      });

      expect(scrollport.scrollTop).toBe(100);
    } finally {
      raf.restore();
    }
  });

  it("turns the live reasoning marker into an animated check when thinking completes", async () => {
    const liveReasoning: UIMessage = {
      id: "r-check",
      role: "assistant",
      content: "",
      reasoning: "checking a source",
      reasoningStreaming: true,
      isStreaming: true,
      createdAt: 1,
    };
    const { rerender } = render(
      <AgentActivityCluster
        messages={[liveReasoning]}
        isTurnStreaming
        hasBodyBelow
      />,
    );

    expect(screen.getByTestId("activity-reasoning-marker")).toHaveAttribute("data-state", "thinking");

    rerender(
      <AgentActivityCluster
        messages={[{
          ...liveReasoning,
          reasoningStreaming: false,
          isStreaming: false,
        }]}
        isTurnStreaming={false}
        hasBodyBelow
      />,
    );

    const marker = screen.getByTestId("activity-reasoning-marker");
    expect(marker).toHaveAttribute("data-state", "done");
    expect(marker.querySelector("svg")).toBeInTheDocument();
    await waitFor(() => expect(marker).toHaveClass("animate-in"));
  });

  it("briefly shows completed activity, then auto-collapses before the answer", () => {
    vi.useFakeTimers();
    const liveReasoning: UIMessage = {
      id: "r-collapse",
      role: "assistant",
      content: "",
      reasoning: "checking files",
      reasoningStreaming: true,
      isStreaming: true,
      createdAt: 1,
    };
    try {
      const { rerender } = render(
        <AgentActivityCluster
          messages={[liveReasoning]}
          isTurnStreaming
          hasBodyBelow
        />,
      );
      expect(screen.getByTestId("agent-activity-scroll")).toBeInTheDocument();

      rerender(
        <AgentActivityCluster
          messages={[{
            ...liveReasoning,
            reasoningStreaming: false,
            isStreaming: false,
          }]}
          isTurnStreaming={false}
          hasBodyBelow
        />,
      );

      expect(screen.getByTestId("agent-activity-scroll")).toBeInTheDocument();
      act(() => {
        vi.advanceTimersByTime(901);
      });
      expect(screen.queryByTestId("agent-activity-scroll")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: /1 steps/i })).toHaveAttribute(
        "aria-expanded",
        "false",
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("uses persisted turn latency for completed history instead of replay timestamps", () => {
    render(
      <AgentActivityCluster
        messages={[{
          id: "r-history",
          role: "assistant",
          content: "",
          reasoning: "historical thought",
          createdAt: 1,
        }]}
        isTurnStreaming={false}
        hasBodyBelow
        turnLatencyMs={12_400}
      />,
    );

    expect(screen.getByText("Thought for 12s")).toBeInTheDocument();
  });

  it("omits the duration when completed history has no reliable timing", () => {
    render(
      <AgentActivityCluster
        messages={[{
          id: "r-old-history",
          role: "assistant",
          content: "",
          reasoning: "old historical thought",
          createdAt: 1,
        }]}
        isTurnStreaming={false}
        hasBodyBelow
      />,
    );

    expect(screen.getByText("Thought")).toBeInTheDocument();
    expect(screen.queryByText("Thought for 0s")).not.toBeInTheDocument();
  });

  it("renders file edit totals and a compact expanded file list", async () => {
    const restoreMotion = installReducedMotion();
    try {
      render(
        <AgentActivityCluster
          messages={activityMessages("", {
            id: "t2",
            role: "tool",
            kind: "trace",
            content: "edit_file()",
            traces: ["edit_file()"],
            fileEdits: [{
              call_id: "call-edit",
              tool: "edit_file",
              path: "src/app.tsx",
              absolute_path: "/Users/renxubin/project/src/app.tsx",
              phase: "end",
              added: 12,
              deleted: 3,
              approximate: false,
              status: "done",
            }],
            createdAt: 3,
          })}
          isTurnStreaming={false}
          hasBodyBelow={false}
        />,
      );

      expect(screen.getByRole("button", { name: /edited app\.tsx/i })).toBeInTheDocument();
      expect(screen.getByTestId("activity-header-file-reference")).toHaveTextContent("app.tsx");
      expect(screen.getByTestId("activity-header-file-reference")).toHaveAttribute(
        "aria-label",
        "/Users/renxubin/project/src/app.tsx",
      );
      fireEvent.click(screen.getByRole("button", { name: /edited app\.tsx/i }));

      expect(screen.queryByText("Edited files")).not.toBeInTheDocument();
      const fileRef = screen.getByTestId("activity-file-reference");
      expect(fileRef).toHaveTextContent("src/app.tsx");
      expect(fileRef).toHaveAttribute("aria-label", "/Users/renxubin/project/src/app.tsx");
      for (const diffPair of screen.getAllByTestId("activity-diff-pair")) {
        expect(diffPair).toHaveClass("items-baseline");
        expect(diffPair).toHaveClass("leading-[inherit]");
        expect(diffPair.className).not.toContain("translate-y");
      }
      await waitFor(() => {
        expect(screen.getAllByText("+12").length).toBeGreaterThan(0);
        expect(screen.getAllByText("-3").length).toBeGreaterThan(0);
      });
    } finally {
      restoreMotion();
    }
  });

  it("labels whole-file deletes as deleted instead of edited", () => {
    render(
      <AgentActivityCluster
        messages={activityMessages("", {
          id: "t-delete",
          role: "tool",
          kind: "trace",
          content: "apply_patch()",
          traces: ["apply_patch()"],
          fileEdits: [{
            call_id: "call-delete",
            tool: "apply_patch",
            path: "angry-birds.html",
            phase: "end",
            added: 0,
            deleted: 590,
            approximate: false,
            status: "done",
            operation: "delete",
          }],
          createdAt: 3,
        })}
        isTurnStreaming={false}
        hasBodyBelow={false}
      />,
    );

    expect(screen.getByRole("button", { name: /deleted angry-birds\.html/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /edited angry-birds\.html/i })).not.toBeInTheDocument();
  });

  it("renders file-only edits without a redundant disclosure", () => {
    render(
      <AgentActivityCluster
        messages={[{
          id: "t-file-only",
          role: "tool",
          kind: "trace",
          content: "apply_patch()",
          traces: ["apply_patch()"],
          fileEdits: [{
            call_id: "call-patch",
            tool: "apply_patch",
            path: "src/app.tsx",
            absolute_path: "/Users/renxubin/project/src/app.tsx",
            phase: "end",
            added: 12,
            deleted: 3,
            approximate: false,
            status: "done",
          }],
          createdAt: 3,
        }]}
        isTurnStreaming={false}
        hasBodyBelow={false}
      />,
    );

    expect(screen.queryByRole("button", { name: /edited app\.tsx/i })).not.toBeInTheDocument();
    expect(screen.queryByTestId("agent-activity-scroll")).not.toBeInTheDocument();
    expect(screen.getByText("Edited")).toBeInTheDocument();
    expect(screen.getByTestId("activity-header-file-reference")).toHaveTextContent("app.tsx");
    expect(screen.getByText("+12")).toBeInTheDocument();
    expect(screen.getByText("-3")).toBeInTheDocument();
  });

  it("renders CLI app runs as dedicated activity rows", () => {
    const line = 'run_cli_app({"name":"blender","args":["--background","scene.blend"],"json":true})';
    render(
      <AgentActivityCluster
        messages={[{
          id: "t-cli",
          role: "tool",
          kind: "trace",
          content: line,
          traces: [line],
          createdAt: 1,
        }]}
        isTurnStreaming
        hasBodyBelow={false}
        cliApps={[BLENDER_CLI_APP]}
      />,
    );

    const cliRuns = screen.getByTestId("activity-cli-runs");
    expect(cliRuns).toHaveTextContent("Using");
    expect(cliRuns).toHaveTextContent("@blender");
    expect(cliRuns).toHaveTextContent("--json --background scene.blend");
    expect(screen.getByTestId("activity-cli-logo-blender")).toBeInTheDocument();
    expect(screen.queryByText(/run_cli_app/)).not.toBeInTheDocument();
  });

  it("keeps CLI rows in chronological trace order", () => {
    const cliArgs = { name: "blender", args: ["project", "new"], json: true };
    const cliLine = `run_cli_app(${JSON.stringify(cliArgs)})`;
    render(
      <AgentActivityCluster
        messages={[
          {
            id: "t-search",
            role: "tool",
            kind: "trace",
            content: 'web_search({"query":"nanobot architecture"})',
            traces: ['web_search({"query":"nanobot architecture"})'],
            createdAt: 1,
          },
          {
            id: "t-cli",
            role: "tool",
            kind: "trace",
            content: cliLine,
            traces: [cliLine],
            toolEvents: [{
              phase: "end",
              call_id: "call-blender",
              name: "run_cli_app",
              arguments: cliArgs,
            }],
            createdAt: 2,
          },
          {
            id: "t-fetch",
            role: "tool",
            kind: "trace",
            content: 'web_fetch({"url":"https://example.com/diagram"})',
            traces: ['web_fetch({"url":"https://example.com/diagram"})'],
            createdAt: 3,
          },
        ]}
        isTurnStreaming
        hasBodyBelow={false}
        cliApps={[BLENDER_CLI_APP]}
      />,
    );

    const searchRow = screen.getByText("Searching").closest("li");
    const cliRow = screen.getByText("@blender").closest("li");
    const fetchRow = screen.getByText("Reading").closest("li");

    expect(searchRow).not.toBeNull();
    expect(cliRow).not.toBeNull();
    expect(fetchRow).not.toBeNull();
    expect(searchRow!.compareDocumentPosition(cliRow!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(cliRow!.compareDocumentPosition(fetchRow!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("labels rejected CLI app calls as failed instead of ran", () => {
    render(
      <AgentActivityCluster
        messages={[{
          id: "t-cli-fail",
          role: "tool",
          kind: "trace",
          content: 'run_cli_app({"name":"github","args":["repo","view"],"json":"true"})',
          traces: ['run_cli_app({"name":"github","args":["repo","view"],"json":"true"})'],
          toolEvents: [
            {
              phase: "error",
              call_id: "call-github",
              name: "run_cli_app",
              arguments: { name: "github", args: ["repo", "view"], json: "true" },
              error: "Error: CLI app 'github' not found",
            },
          ],
          createdAt: 1,
        }]}
        isTurnStreaming={false}
        hasBodyBelow={false}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /failed @github/i }));

    expect(screen.getByTestId("activity-cli-runs")).toHaveTextContent("Failed");
    expect(screen.getByTestId("activity-cli-runs")).toHaveTextContent("@github");
    expect(screen.getByTestId("activity-cli-runs")).toHaveTextContent("Error: CLI app 'github' not found");
    expect(screen.queryByText("Ran CLI")).not.toBeInTheDocument();
  });

  it("renders MCP preset tool calls as branded activity rows", () => {
    render(
      <AgentActivityCluster
        messages={[{
          id: "t-mcp",
          role: "tool",
          kind: "trace",
          content: "mcp_browserbase_browser_navigate()",
          traces: ["mcp_browserbase_browser_navigate({\"url\":\"https://example.com\"})"],
          toolEvents: [
            {
              phase: "start",
              call_id: "call-browserbase",
              name: "mcp_browserbase_browser_navigate",
              arguments: { url: "https://example.com" },
            },
          ],
          createdAt: 1,
        }]}
        isTurnStreaming
        hasBodyBelow={false}
        mcpPresets={[BROWSERBASE_MCP]}
      />,
    );

    const mcpRuns = screen.getByTestId("activity-mcp-runs");
    expect(mcpRuns).toHaveTextContent("Using");
    expect(mcpRuns).toHaveTextContent("Browserbase");
    expect(mcpRuns).toHaveTextContent("browser_navigate");
    expect(mcpRuns).toHaveTextContent("url: https://example.com");
    expect(screen.getByTestId("activity-mcp-logo-browserbase")).toBeInTheDocument();
    expect(screen.queryByText(/mcp_browserbase_browser_navigate/)).not.toBeInTheDocument();
  });

  it("renders public web fetch traces with the site favicon", () => {
    render(
      <AgentActivityCluster
        messages={[{
          id: "t-web-fetch",
          role: "tool",
          kind: "trace",
          content: 'web_fetch({"url":"https://auth0.com/blog/jwt-security-best-practices"})',
          traces: ['web_fetch({"url":"https://auth0.com/blog/jwt-security-best-practices"})'],
          createdAt: 1,
        }]}
        isTurnStreaming
        hasBodyBelow={false}
      />,
    );

    const favicon = screen.getByTestId("activity-web-favicon-auth0.com");
    expect(favicon.querySelector("img")?.getAttribute("src")).toContain("auth0.com");
    expect(screen.getByText("Reading")).toBeInTheDocument();
    expect(screen.getByText("auth0.com/blog/jwt-security-best-practices")).toBeInTheDocument();
  });

  it("renders plain-text fetch progress with the site favicon", () => {
    render(
      <AgentActivityCluster
        messages={[{
          id: "t-web-fetch-text",
          role: "tool",
          kind: "trace",
          content: "Fetching https://auth0.com/blog/jwt-security-best-practices",
          traces: ["Fetching https://auth0.com/blog/jwt-security-best-practices"],
          createdAt: 1,
        }]}
        isTurnStreaming
        hasBodyBelow={false}
      />,
    );

    expect(screen.getByTestId("activity-web-favicon-auth0.com")).toBeInTheDocument();
    expect(screen.getByText("Reading")).toBeInTheDocument();
    expect(screen.getByText("auth0.com/blog/jwt-security-best-practices")).toBeInTheDocument();
  });

  it("does not request favicons for private web fetch targets", () => {
    render(
      <AgentActivityCluster
        messages={[{
          id: "t-web-fetch-local",
          role: "tool",
          kind: "trace",
          content: 'web_fetch({"url":"http://localhost:3000/dashboard"})',
          traces: ['web_fetch({"url":"http://localhost:3000/dashboard"})'],
          createdAt: 1,
        }]}
        isTurnStreaming
        hasBodyBelow={false}
      />,
    );

    expect(screen.queryByTestId("activity-web-favicon-localhost")).not.toBeInTheDocument();
    expect(screen.getByText("url: http://localhost:3000/dashboard")).toBeInTheDocument();
  });

  it("summarizes long shell traces instead of dumping scripts", () => {
    const command = [
      "cat << 'EOF' | bash",
      "SECRET_TOKEN=sk-test",
      "for id in m1 m2 m3; do",
      "  echo done $id",
      "done",
      "EOF",
    ].join("\n");
    const line = `exec(${JSON.stringify({ command })})`;
    render(
      <AgentActivityCluster
        messages={[{
          id: "t-shell",
          role: "tool",
          kind: "trace",
          content: line,
          traces: [line],
          createdAt: 1,
        }]}
        isTurnStreaming={false}
        hasBodyBelow
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /1 tool calls/i }));

    expect(screen.getByText("Shell")).toBeInTheDocument();
    expect(screen.getByText(/cat << 'EOF' \| bash · script, 6 lines/)).toBeInTheDocument();
    expect(screen.queryByText(/SECRET_TOKEN/)).not.toBeInTheDocument();
    expect(screen.queryByText(/for id in/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Done$/)).not.toBeInTheDocument();
  });

  it("does not render zero diff counters for completed edits", () => {
    render(
      <AgentActivityCluster
        messages={activityMessages("", {
          id: "t2",
          role: "tool",
          kind: "trace",
          content: "edit_file()",
          traces: ["edit_file()"],
          fileEdits: [{
            call_id: "call-edit",
            tool: "edit_file",
            path: "src/app.tsx",
            phase: "end",
            added: 0,
            deleted: 0,
            approximate: false,
            status: "done",
          }],
          createdAt: 3,
        })}
        isTurnStreaming={false}
        hasBodyBelow={false}
      />,
    );

    expect(screen.getByRole("button", { name: /edited app\.tsx/i })).toBeInTheDocument();
    expect(screen.queryByText("+0")).not.toBeInTheDocument();
    expect(screen.queryByText("-0")).not.toBeInTheDocument();
  });

  it("drops stale pathless pending edits after the turn completes", () => {
    render(
      <AgentActivityCluster
        messages={[{
          id: "t1",
          role: "tool",
          kind: "trace",
          content: "",
          traces: [],
          fileEdits: [{
            call_id: "call-edit",
            tool: "edit_file",
            path: "",
            phase: "start",
            added: 98,
            deleted: 0,
            approximate: true,
            status: "editing",
            pending: true,
          }],
          createdAt: 1,
        }]}
        isTurnStreaming={false}
        hasBodyBelow={false}
      />,
    );

    expect(screen.queryByRole("button", { name: /preparing edit/i })).not.toBeInTheDocument();
    expect(screen.queryByText("+98")).not.toBeInTheDocument();
    expect(screen.queryByText("0 tool calls")).not.toBeInTheDocument();
  });

  it("renders pending file edit placeholders before the path is known", () => {
    render(
      <AgentActivityCluster
        messages={activityMessages("", {
          id: "t2",
          role: "tool",
          kind: "trace",
          content: "",
          traces: [],
          fileEdits: [{
            call_id: "call-edit",
            tool: "edit_file",
            path: "",
            phase: "start",
            added: 0,
            deleted: 0,
            approximate: true,
            status: "editing",
            pending: true,
          }],
          createdAt: 3,
        })}
        isTurnStreaming
        hasBodyBelow={false}
      />,
    );

    expect(screen.getByRole("button", { name: /preparing edit/i })).toBeInTheDocument();
    expect(screen.getByText("Preparing file edit…")).toBeInTheDocument();
  });

  it("shows the reason when a file edit fails", () => {
    render(
      <AgentActivityCluster
        messages={activityMessages("", {
          id: "t2",
          role: "tool",
          kind: "trace",
          content: "apply_patch()",
          traces: ["apply_patch()"],
          fileEdits: [{
            call_id: "call-patch",
            tool: "apply_patch",
            path: "angry-birds.html",
            phase: "error",
            added: 0,
            deleted: 0,
            approximate: false,
            status: "error",
            error: "Error applying patch: old_text not found in angry-birds.html",
          }],
          createdAt: 3,
        })}
        isTurnStreaming={false}
        hasBodyBelow={false}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /failed angry-birds\.html/i }));

    expect(screen.getByText("Target text was not found in angry-birds.html.")).toBeInTheDocument();
  });

  it("merges repeated edits for the same path and lets successful edits win over failures", async () => {
    const restoreMotion = installReducedMotion();
    try {
      render(
        <AgentActivityCluster
          messages={activityMessages("", {
            id: "t2",
            role: "tool",
            kind: "trace",
            content: "edit_file()",
            traces: ["edit_file()"],
            fileEdits: [
              {
                call_id: "call-edit-1",
                tool: "edit_file",
                path: "minecraft-fps/index.html",
                phase: "end",
                added: 2,
                deleted: 1,
                approximate: false,
                status: "done",
              },
              {
                call_id: "call-edit-2",
                tool: "edit_file",
                path: "minecraft-fps/index.html",
                phase: "error",
                added: 0,
                deleted: 0,
                approximate: false,
                status: "error",
                error: "patch failed",
              },
              {
                call_id: "call-edit-3",
                tool: "edit_file",
                path: "minecraft-fps/index.html",
                phase: "end",
                added: 6,
                deleted: 6,
                approximate: false,
                status: "done",
              },
            ],
            createdAt: 3,
          })}
          isTurnStreaming={false}
          hasBodyBelow={false}
        />,
      );

      expect(screen.getByRole("button", { name: /edited index\.html/i })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /failed index\.html/i })).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: /edited index\.html/i }));

      const fileRefs = screen.getAllByTestId("activity-file-reference");
      expect(fileRefs).toHaveLength(1);
      expect(fileRefs[0]).toHaveTextContent("minecraft-fps/index.html");
      expect(screen.queryByText("Failed")).not.toBeInTheDocument();
      await waitFor(() => {
        expect(screen.getAllByText("+8").length).toBeGreaterThan(0);
        expect(screen.getAllByText("-7").length).toBeGreaterThan(0);
      });
    } finally {
      restoreMotion();
    }
  });
});
