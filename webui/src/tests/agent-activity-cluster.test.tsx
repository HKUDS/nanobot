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

function unifiedFileDiff(lines: string[], truncated = false) {
  return {
    format: "unified" as const,
    context: 3,
    truncated,
    text: lines.join("\n"),
  };
}

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
      expect(screen.getByRole("button", { name: "Thought" })).toHaveAttribute(
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

  it("labels mixed tool activity as work instead of thought", () => {
    render(
      <AgentActivityCluster
        messages={activityMessages()}
        isTurnStreaming={false}
        hasBodyBelow
        turnLatencyMs={12_400}
      />,
    );

    expect(screen.getByText("Worked for 12s")).toBeInTheDocument();
    expect(screen.queryByText("Thought for 12s")).not.toBeInTheDocument();
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

  it("renders file edits as one-line activity rows", async () => {
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

      expect(screen.queryByText("Edited files")).not.toBeInTheDocument();
      const fileRef = screen.getByTestId("activity-file-reference");
      expect(fileRef).toHaveTextContent("src/app.tsx");
      expect(fileRef).toHaveAttribute("aria-label", "src/app.tsx");
      expect(screen.queryByTestId("activity-header-file-reference")).not.toBeInTheDocument();
      expect(screen.queryByTestId("file-edit-diff")).not.toBeInTheDocument();
      for (const diffPair of screen.getAllByTestId("activity-diff-pair")) {
        expect(diffPair).toHaveClass("items-baseline");
        expect(diffPair).toHaveClass("leading-[inherit]");
        expect(diffPair.className).not.toContain("translate-y");
      }
      expect(screen.getByText("+12")).toBeInTheDocument();
      expect(screen.getByText("-3")).toBeInTheDocument();
    } finally {
      restoreMotion();
    }
  });

  it("keeps file edits flat even when the legacy diff preference is enabled", () => {
    localStorage.setItem(
      "nanobot-webui.settings-preferences",
      JSON.stringify({ fileEditDisplayMode: "diff" }),
    );

    try {
      render(
        <AgentActivityCluster
          messages={[{
            id: "t-diff",
            role: "tool",
            kind: "trace",
            content: "edit_file()",
            traces: ["edit_file()"],
            fileEdits: [{
              call_id: "call-edit",
              tool: "edit_file",
              path: "src/app.tsx",
              phase: "end",
              added: 1,
              deleted: 1,
              approximate: false,
              status: "done",
              diff: unifiedFileDiff([
                "--- src/app.tsx",
                "+++ src/app.tsx",
                "@@ -10,2 +10,2 @@",
                " function App() {",
                "-  return <Old />;",
                "+  return <New />;",
              ]),
            }],
            createdAt: 3,
          }]}
          isTurnStreaming={false}
          hasBodyBelow={false}
        />,
      );

      expect(screen.queryByTestId("file-edit-diff")).not.toBeInTheDocument();
      expect(screen.queryByText("return <Old />;")).not.toBeInTheDocument();
      expect(screen.queryByText("return <New />;")).not.toBeInTheDocument();
      expect(screen.getByTestId("activity-file-reference")).toHaveTextContent("src/app.tsx");
      expect(screen.getAllByTestId("activity-diff-pair")).toHaveLength(1);
    } finally {
      localStorage.removeItem("nanobot-webui.settings-preferences");
    }
  });

  it("does not render diff hunks inside the activity list", () => {
    localStorage.setItem(
      "nanobot-webui.settings-preferences",
      JSON.stringify({ fileEditDisplayMode: "diff" }),
    );

    try {
      render(
        <AgentActivityCluster
          messages={[{
            id: "t-multi-hunk-diff",
            role: "tool",
            kind: "trace",
            content: "edit_file()",
            traces: ["edit_file()"],
            fileEdits: [{
              call_id: "call-multi-hunk-edit",
              tool: "edit_file",
              path: "src/app.tsx",
              phase: "end",
              added: 2,
              deleted: 2,
              approximate: false,
              status: "done",
              diff: unifiedFileDiff([
                "--- src/app.tsx",
                "+++ src/app.tsx",
                "@@ -1,3 +1,3 @@",
                " function first() {",
                "-  return oldFirst;",
                "+  return newFirst;",
                " }",
                "@@ -25,3 +25,3 @@",
                " function second() {",
                "-  return oldSecond;",
                "+  return newSecond;",
                " }",
              ]),
            }],
            createdAt: 3,
          }]}
          isTurnStreaming={false}
          hasBodyBelow={false}
        />,
      );

      expect(screen.queryByTestId("file-edit-diff-hunk-gap")).not.toBeInTheDocument();
      expect(screen.queryByText("@@ -25,3 +25,3 @@")).not.toBeInTheDocument();
      expect(screen.queryByText("return newSecond;")).not.toBeInTheDocument();
      expect(screen.getByTestId("activity-file-reference")).toHaveTextContent("src/app.tsx");
    } finally {
      localStorage.removeItem("nanobot-webui.settings-preferences");
    }
  });

  it("summarizes long file edit diffs without an expansion control", () => {
    localStorage.setItem(
      "nanobot-webui.settings-preferences",
      JSON.stringify({ fileEditDisplayMode: "diff" }),
    );
    const lines = Array.from({ length: 165 }, (_, index) => `line-${index + 1}`);

    try {
      render(
        <AgentActivityCluster
          messages={[{
            id: "t-long-diff",
            role: "tool",
            kind: "trace",
            content: "edit_file()",
            traces: ["edit_file()"],
            fileEdits: [{
              call_id: "call-long-edit",
              tool: "edit_file",
              path: "src/long.ts",
              phase: "end",
              added: lines.length,
              deleted: 0,
              approximate: false,
              status: "done",
              diff: unifiedFileDiff([
                "--- src/long.ts",
                "+++ src/long.ts",
                `@@ -0,0 +1,${lines.length} @@`,
                ...lines.map((line) => `+${line}`),
              ]),
            }],
            createdAt: 3,
          }]}
          isTurnStreaming={false}
          hasBodyBelow={false}
        />,
      );

      expect(screen.queryByTestId("file-edit-diff-toggle")).not.toBeInTheDocument();
      expect(screen.queryByTestId("file-edit-diff")).not.toBeInTheDocument();
      expect(screen.queryByText("line-1")).not.toBeInTheDocument();
      expect(screen.getByText("+165")).toBeInTheDocument();
    } finally {
      localStorage.removeItem("nanobot-webui.settings-preferences");
    }
  });

  it("ignores the legacy collapsed diff mode in the activity list", () => {
    localStorage.setItem(
      "nanobot-webui.settings-preferences",
      JSON.stringify({ fileEditDisplayMode: "collapsed_diff" }),
    );

    try {
      render(
        <AgentActivityCluster
          messages={[{
            id: "t-collapsed-diff",
            role: "tool",
            kind: "trace",
            content: "edit_file()",
            traces: ["edit_file()"],
            fileEdits: [{
              call_id: "call-collapsed-edit",
              tool: "edit_file",
              path: "src/app.tsx",
              phase: "end",
              added: 1,
              deleted: 1,
              approximate: false,
              status: "done",
              diff: unifiedFileDiff([
                "--- src/app.tsx",
                "+++ src/app.tsx",
                "@@ -10,2 +10,2 @@",
                " function App() {",
                "-  return <Old />;",
                "+  return <New />;",
              ]),
            }],
            createdAt: 3,
          }]}
          isTurnStreaming={false}
          hasBodyBelow={false}
        />,
      );

      expect(screen.queryByTestId("file-edit-diff-toggle")).not.toBeInTheDocument();
      expect(screen.queryByTestId("file-edit-diff")).not.toBeInTheDocument();
      expect(screen.queryByText("return <New />;")).not.toBeInTheDocument();
      expect(screen.getByTestId("activity-file-reference")).toHaveTextContent("src/app.tsx");
    } finally {
      localStorage.removeItem("nanobot-webui.settings-preferences");
    }
  });

  it("opens the edited file directly instead of expanding a truncated diff", () => {
    localStorage.setItem(
      "nanobot-webui.settings-preferences",
      JSON.stringify({ fileEditDisplayMode: "diff" }),
    );
    const onOpenFilePreview = vi.fn();

    try {
      render(
        <AgentActivityCluster
          messages={[{
            id: "t-truncated-diff",
            role: "tool",
            kind: "trace",
            content: "edit_file()",
            traces: ["edit_file()"],
            fileEdits: [{
              call_id: "call-truncated-edit",
              tool: "edit_file",
              path: "src/app.tsx",
              absolute_path: "/repo/src/app.tsx",
              phase: "end",
              added: 1,
              deleted: 0,
              approximate: false,
              status: "done",
              diff: unifiedFileDiff([
                "--- src/app.tsx",
                "+++ src/app.tsx",
                "@@ -9,0 +10,1 @@",
                "+export const value = 1;",
              ], true),
            }],
            createdAt: 3,
          }]}
          isTurnStreaming={false}
          hasBodyBelow={false}
          onOpenFilePreview={onOpenFilePreview}
        />,
      );

      expect(screen.queryByTestId("file-edit-diff-toggle")).not.toBeInTheDocument();
      expect(screen.queryByTestId("file-edit-diff-truncated")).not.toBeInTheDocument();
      fireEvent.click(screen.getByTestId("activity-file-reference"));

      expect(onOpenFilePreview).toHaveBeenCalledWith("/repo/src/app.tsx");
    } finally {
      localStorage.removeItem("nanobot-webui.settings-preferences");
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

    expect(screen.getByText("Deleted")).toBeInTheDocument();
    expect(screen.queryByText("Edited")).not.toBeInTheDocument();
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
    expect(screen.queryByTestId("activity-header-file-reference")).not.toBeInTheDocument();
    expect(screen.getByTestId("activity-file-reference")).toHaveTextContent("src/app.tsx");
    expect(screen.getByText("+12")).toBeInTheDocument();
    expect(screen.getByText("-3")).toBeInTheDocument();
  });

  it("renders every file from one apply_patch call", () => {
    render(
      <AgentActivityCluster
        messages={[{
          id: "t-file-many",
          role: "tool",
          kind: "trace",
          content: "apply_patch()",
          traces: ["apply_patch()"],
          fileEdits: [
            {
              call_id: "call-patch",
              tool: "apply_patch",
              path: "USER.md",
              phase: "end",
              added: 0,
              deleted: 3,
              approximate: false,
              status: "done",
            },
            {
              call_id: "call-patch",
              tool: "apply_patch",
              path: "MEMORY.md",
              phase: "end",
              added: 0,
              deleted: 4,
              approximate: false,
              status: "done",
            },
          ],
          createdAt: 3,
        }]}
        isTurnStreaming={false}
        hasBodyBelow={false}
      />,
    );

    const fileRefs = screen.getAllByTestId("activity-file-reference");
    expect(fileRefs).toHaveLength(2);
    expect(fileRefs[0]).toHaveTextContent("USER.md");
    expect(fileRefs[1]).toHaveTextContent("MEMORY.md");
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

    expect(screen.getByText("Using Blender · --json --background scene.blend")).toBeInTheDocument();
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

    const searchRow = screen.getByText("Searched nanobot architecture").closest('[data-testid="activity-step"]');
    const cliRow = screen.getByText("Used Blender · --json project new").closest('[data-testid="activity-step"]');
    const fetchRow = screen.getByText("example.com/diagram").closest('[data-testid="activity-step"]');

    expect(searchRow).not.toBeNull();
    expect(cliRow).not.toBeNull();
    expect(fetchRow).not.toBeNull();
    expect(searchRow!.compareDocumentPosition(cliRow!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(cliRow!.compareDocumentPosition(fetchRow!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("renders web search results as lightweight branded source rows", () => {
    const line = 'web_search({"query":"agent frameworks"})';
    render(
      <AgentActivityCluster
        messages={[{
          id: "t-web-search-results",
          role: "tool",
          kind: "trace",
          content: line,
          traces: [line],
          toolEvents: [{
            phase: "end",
            call_id: "call-web-search",
            name: "web_search",
            arguments: { query: "agent frameworks" },
            result: [
              "Results for: agent frameworks",
              "",
              "1. OpenAI Agents SDK",
              "   https://openai.com/index/new-tools-for-building-agents/?utm_source=test",
              "   Build and deploy agentic applications.",
              "2. Building effective agents",
              "   https://www.anthropic.com/engineering/building-effective-agents",
              "   Practical patterns for reliable agents.",
              "3. Internal dashboard",
              "   http://localhost:3000/search",
            ].join("\n"),
          }],
          createdAt: 1,
        }]}
        isTurnStreaming
        hasBodyBelow={false}
      />,
    );

    expect(screen.getByText("Searched agent frameworks")).toBeInTheDocument();
    expect(screen.queryByText("2 sources")).not.toBeInTheDocument();

    const openAiLink = screen.getByText("OpenAI Agents SDK").closest("a");
    const anthropicLink = screen.getByText("Building effective agents").closest("a");
    expect(openAiLink).toHaveAttribute(
      "href",
      "https://openai.com/index/new-tools-for-building-agents/",
    );
    expect(openAiLink).not.toHaveAttribute("title");
    expect(anthropicLink).toHaveAttribute(
      "href",
      "https://www.anthropic.com/engineering/building-effective-agents",
    );
    expect(screen.getByText("openai.com/index/new-tools-for-building-agents")).toBeInTheDocument();
    expect(screen.getByText("anthropic.com/engineering/building-effective-agents")).toBeInTheDocument();
    expect(screen.getByTestId("activity-web-favicon-openai.com")).toBeInTheDocument();
    expect(screen.getByTestId("activity-web-favicon-anthropic.com")).toBeInTheDocument();
    expect(screen.queryByText("Internal dashboard")).not.toBeInTheDocument();
    expect(screen.queryByText("Build and deploy agentic applications.")).not.toBeInTheDocument();
    const searchStep = screen.getByText("Searched agent frameworks").closest(
      '[data-testid="activity-step"]',
    );
    const openAiStep = openAiLink!.closest('[data-testid="activity-step"]');
    const anthropicStep = anthropicLink!.closest('[data-testid="activity-step"]');
    expect(openAiStep).toContainElement(
      screen.getByText("openai.com/index/new-tools-for-building-agents"),
    );
    expect(anthropicStep).toContainElement(
      screen.getByText("anthropic.com/engineering/building-effective-agents"),
    );
    expect(searchStep?.parentElement).toBe(openAiStep?.parentElement);
    expect(searchStep?.parentElement).toBe(anthropicStep?.parentElement);
    expect(searchStep?.parentElement?.querySelector("ul, li, section")).toBeNull();
    expect(screen.getAllByTestId("activity-step")).toHaveLength(3);
  });

  it("renders hosted X search as an explicit search activity", () => {
    const line = 'x_search({"query":"nanobot oauth"})';
    render(
      <AgentActivityCluster
        messages={[{
          id: "t-x-search",
          role: "tool",
          kind: "trace",
          content: line,
          traces: [line],
          toolEvents: [{
            phase: "end",
            call_id: "x-search-1",
            name: "x_search",
            arguments: { query: "nanobot oauth" },
            result: { name: "x_semantic_search" },
          }],
          createdAt: 1,
        }]}
        isTurnStreaming={false}
        hasBodyBelow={false}
      />,
    );

    expect(screen.getByText("Searched X · nanobot oauth")).toBeInTheDocument();
    expect(screen.queryByText(/Completed X search/i)).not.toBeInTheDocument();
    expect(screen.getAllByTestId("activity-step")).toHaveLength(1);
  });

  it("redacts credentials from web search queries, titles, and links", () => {
    const query = "release notes access_token=signed-secret";
    const line = `web_search(${JSON.stringify({ query })})`;
    render(
      <AgentActivityCluster
        messages={[{
          id: "t-web-search-secret",
          role: "tool",
          kind: "trace",
          content: line,
          traces: [line],
          toolEvents: [{
            phase: "end",
            call_id: "call-web-search-secret",
            name: "web_search",
            arguments: { query },
            result: [
              "1. Release sk-proj-secret1234",
              "   https://example.com/release?api_key=url-secret#details",
            ].join("\n"),
          }],
          createdAt: 1,
        }]}
        isTurnStreaming={false}
        hasBodyBelow={false}
      />,
    );

    expect(screen.queryByText(/signed-secret|secret1234|url-secret/)).not.toBeInTheDocument();
    expect(screen.getByText("Searched release notes access_token=<redacted>")).toBeInTheDocument();
    expect(screen.getByText("Release <redacted>")).toBeInTheDocument();
    expect(screen.getByText("Release <redacted>").closest("a")).toHaveAttribute(
      "href",
      "https://example.com/release",
    );
  });

  it("renders persisted search progress as one human-readable action", () => {
    const line = 'web_search({"query":"site:linkedin.com/company Evomap startup"})';
    render(
      <AgentActivityCluster
        messages={[
          {
            id: "search-start",
            role: "tool",
            kind: "trace",
            content: line,
            traces: [line],
            toolEvents: [{
              phase: "start",
              name: "web_search",
              arguments: { query: "site:linkedin.com/company Evomap startup" },
            }],
            createdAt: 1,
          },
          {
            id: "search-end",
            role: "tool",
            kind: "trace",
            content: line,
            traces: [line],
            toolEvents: [{
              phase: "error",
              name: "web_search",
              arguments: { query: "site:linkedin.com/company Evomap startup" },
              error: "Search provider rate limited the request",
            }],
            createdAt: 2,
          },
        ]}
        isTurnStreaming
        hasBodyBelow={false}
      />,
    );

    expect(screen.getAllByTestId("activity-step")).toHaveLength(1);
    expect(screen.getByText("Could not search LinkedIn · Evomap startup")).toBeInTheDocument();
    expect(screen.queryByText(/site:linkedin/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Web research")).not.toBeInTheDocument();
  });

  it("renders reasoning as a single flat activity row", () => {
    render(
      <AgentActivityCluster
        messages={[{
          id: "r-flat",
          role: "assistant",
          content: "",
          reasoning: "**Planning** a focused search\nfor official sources",
          reasoningStreaming: true,
          isStreaming: true,
          createdAt: 1,
        }]}
        isTurnStreaming
        hasBodyBelow={false}
      />,
    );

    expect(screen.getByText("Planning a focused search for official sources")).toBeInTheDocument();
    expect(screen.queryByText("Thinking…")).not.toBeInTheDocument();
    expect(screen.queryByText("Thinking")).not.toBeInTheDocument();
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

    fireEvent.click(screen.getByRole("button", { name: "Worked" }));

    const row = screen.getByText("Could not use GitHub · --json repo view").closest(
      '[data-testid="activity-step"]',
    );
    expect(row).toBeInTheDocument();
    expect(row).not.toHaveAttribute("title");
    expect(screen.queryByText("Error: CLI app 'github' not found")).not.toBeInTheDocument();
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

    expect(screen.getByText("Opening example.com · Browserbase")).toBeInTheDocument();
    expect(screen.queryByText("Using")).not.toBeInTheDocument();
    expect(screen.queryByText(/browser_navigate/)).not.toBeInTheDocument();
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
    expect(favicon).toHaveAttribute("src", expect.stringContaining("auth0.com"));
    const row = screen.getByText("auth0.com/blog/jwt-security-best-practices").closest(
      '[data-testid="activity-step"]',
    );
    expect(row).toHaveTextContent("Reading");
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
    const row = screen.getByText("auth0.com/blog/jwt-security-best-practices").closest(
      '[data-testid="activity-step"]',
    );
    expect(row).toHaveTextContent("Reading");
  });

  it("renders a completed fetch as one linked title and URL row", () => {
    const line = 'web_fetch({"url":"https://example.com/docs"})';
    render(
      <AgentActivityCluster
        messages={[{
          id: "t-web-fetch-title",
          role: "tool",
          kind: "trace",
          content: line,
          traces: [line],
          toolEvents: [{
            phase: "end",
            call_id: "fetch-title",
            name: "web_fetch",
            arguments: { url: "https://example.com/docs" },
            result: "# Example documentation\n\nPage body",
          }],
          createdAt: 1,
        }]}
        isTurnStreaming={false}
        hasBodyBelow={false}
      />,
    );

    const title = screen.getByText("Example documentation");
    const url = screen.getByText("example.com/docs");
    const row = title.closest('[data-testid="activity-step"]');
    expect(row).toContainElement(url);
    expect(title.closest("a")).toHaveAttribute("href", "https://example.com/docs");
    expect(screen.getAllByTestId("activity-step")).toHaveLength(1);
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
    expect(screen.getByText("Reading Private address")).toBeInTheDocument();
    expect(screen.queryByText("http://localhost:3000/dashboard")).not.toBeInTheDocument();
  });

  it("presents generic tool traces as one-line semantic actions", () => {
    render(
      <AgentActivityCluster
        messages={[{
          id: "t-generic-tools",
          role: "tool",
          kind: "trace",
          content: 'grep({"pattern":"dream_cursor"})',
          traces: [
            'find_files({"query":"thread","glob":"*.tsx"})',
            'list_dir({"path":"memory"})',
            'grep({"pattern":"dream_cursor"})',
          ],
          createdAt: 1,
        }]}
        isTurnStreaming
        hasBodyBelow={false}
      />,
    );

    expect(screen.getByText("Found files *.tsx")).toBeInTheDocument();
    expect(screen.getByText("Listed files memory")).toBeInTheDocument();
    expect(screen.getByText("Searching files “dream_cursor”")).toBeInTheDocument();
    expect(screen.queryByText("Technical details")).not.toBeInTheDocument();
    expect(document.querySelector("details")).not.toBeInTheDocument();
  });

  it("groups repeated searches over internal tool results without exposing raw paths", () => {
    const pattern = "Jul (1[0-7]), 2026|July (1[0-7]), 2026|2026-07-(1[0-7])";
    const secondPattern = "Anthropic|OpenAI|DeepMind";
    const firstPath = "/Users/test/.nanobot/workspace/.nanobot/tool-results/websocket_session/call_first-result.txt";
    const secondPath = "/Users/test/.nanobot/workspace/.nanobot/tool-results/websocket_session/call_second-result.txt";
    const traces = [
      `grep(${JSON.stringify({ pattern, path: firstPath })})`,
      `grep(${JSON.stringify({ pattern: secondPattern, path: secondPath })})`,
    ];

    render(
      <AgentActivityCluster
        messages={[{
          id: "t-grouped-grep",
          role: "tool",
          kind: "trace",
          content: traces.join("\n"),
          traces,
          createdAt: 1,
        }]}
        isTurnStreaming={false}
        hasBodyBelow={false}
      />,
    );

    const run = screen.getByText(/Reviewed sources.*2 files/).closest('[data-testid="activity-step"]');
    expect(run).toBeInTheDocument();
    expect(screen.queryByText(firstPath)).not.toBeInTheDocument();
    expect(screen.queryByText(secondPath)).not.toBeInTheDocument();

    expect(screen.queryByText(pattern)).not.toBeInTheDocument();
    expect(screen.queryByText(secondPattern)).not.toBeInTheDocument();
    expect(screen.queryByText("call_first-result.txt")).not.toBeInTheDocument();
    expect(screen.queryByText("call_second-result.txt")).not.toBeInTheDocument();
  });

  it("surfaces generic tool failures without dumping their arguments", () => {
    const args = { pattern: "needle", path: "workspace/file.txt" };
    const line = `grep(${JSON.stringify(args)})`;
    render(
      <AgentActivityCluster
        messages={[{
          id: "t-grep-error",
          role: "tool",
          kind: "trace",
          content: line,
          traces: [line],
          toolEvents: [{
            phase: "error",
            call_id: "call-grep-error",
            name: "grep",
            arguments: args,
            error: JSON.stringify({
              message: "Permission denied",
              headers: { Authorization: "Bearer sk-live-secret" },
              token: "super-secret",
            }),
          }],
          createdAt: 1,
        }]}
        isTurnStreaming={false}
        hasBodyBelow={false}
      />,
    );

    const row = screen.getByText("Could not search files “needle”").closest(
      '[data-testid="activity-step"]',
    );
    expect(row).toBeInTheDocument();
    expect(row).not.toHaveAttribute("title");
    expect(screen.queryByText(/Permission denied/)).not.toBeInTheDocument();
    expect(screen.queryByText(/super-secret/)).not.toBeInTheDocument();
    expect(screen.queryByText(/sk-live-secret/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Authorization/)).not.toBeInTheDocument();
  });

  it("redacts credentials from generic tool URL details", () => {
    const line = 'download_asset({"url":"https://user:password@example.com/file?access_token=signed-secret&format=png"})';
    render(
      <AgentActivityCluster
        messages={[{
          id: "t-generic-url-secret",
          role: "tool",
          kind: "trace",
          content: line,
          traces: [line],
          createdAt: 1,
        }]}
        isTurnStreaming={false}
        hasBodyBelow={false}
      />,
    );

    expect(screen.queryByText(/password|signed-secret/)).not.toBeInTheDocument();
    expect(screen.getByText("Completed Download asset")).toBeInTheDocument();
    expect(screen.queryByText(/example\.com/)).not.toBeInTheDocument();
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

    fireEvent.click(screen.getByRole("button", { name: "Worked" }));

    expect(screen.getByText("Ran command cat << 'EOF' | bash · script, 6 lines")).toBeInTheDocument();
    expect(screen.queryByText(/SECRET_TOKEN/)).not.toBeInTheDocument();
    expect(screen.queryByText(/for id in/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Done$/)).not.toBeInTheDocument();
  });

  it("presents time checks as an intent instead of a raw command", () => {
    const line = `exec(${JSON.stringify({ command: "date '+%Y-%m-%d %H:%M:%S %Z'" })})`;
    render(
      <AgentActivityCluster
        messages={[{
          id: "t-date",
          role: "tool",
          kind: "trace",
          content: line,
          traces: [line],
          createdAt: 1,
        }]}
        isTurnStreaming
        hasBodyBelow={false}
      />,
    );

    expect(screen.getByText("Checking current time")).toBeInTheDocument();
    expect(screen.queryByText(/%Y-%m-%d/)).not.toBeInTheDocument();
    expect(screen.queryByText("Web")).not.toBeInTheDocument();
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

    expect(screen.getByText("Edited")).toBeInTheDocument();
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

    const row = screen.getByText("Could not edit").closest('[data-testid="activity-step"]');
    expect(row).toBeInTheDocument();
    expect(row).not.toHaveAttribute("title");
    expect(screen.queryByText("Target text was not found in angry-birds.html.")).not.toBeInTheDocument();
  });

  it("keeps permission errors readable for failed file edits", () => {
    render(
      <AgentActivityCluster
        messages={activityMessages("", {
          id: "t2",
          role: "tool",
          kind: "trace",
          content: "write_file()",
          traces: ["write_file()"],
          fileEdits: [{
            call_id: "call-write",
            tool: "write_file",
            path: "/Users/renxubin/.nanobot/workspace/agent-research-video/composition.html",
            phase: "error",
            added: 0,
            deleted: 0,
            approximate: false,
            status: "error",
            error: "Error writing file: [Errno 13] Permission denied: '/Users/renxubin'",
          }],
          createdAt: 3,
        })}
        isTurnStreaming={false}
        hasBodyBelow={false}
      />,
    );

    const row = screen.getByText("Could not edit").closest('[data-testid="activity-step"]');
    expect(row).toBeInTheDocument();
    expect(row).not.toHaveAttribute("title");
    expect(screen.queryByText("No permission to change this location.")).not.toBeInTheDocument();
    expect(screen.queryByText(/\[Errno 13\]/)).not.toBeInTheDocument();
  });

  it("renders repeated edits for the same path as separate actions", () => {
    localStorage.setItem(
      "nanobot-webui.settings-preferences",
      JSON.stringify({ fileEditDisplayMode: "diff" }),
    );
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
                diff: unifiedFileDiff([
                  "--- minecraft-fps/index.html",
                  "+++ minecraft-fps/index.html",
                  "@@ -1,1 +1,2 @@",
                  " <main>",
                  "+  <canvas />",
                ]),
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
                diff: unifiedFileDiff([
                  "--- minecraft-fps/index.html",
                  "+++ minecraft-fps/index.html",
                  "@@ -8,2 +8,2 @@",
                  "-const fps = 30;",
                  "+const fps = 60;",
                  " start();",
                ]),
              },
            ],
            createdAt: 3,
          })}
          isTurnStreaming={false}
          hasBodyBelow={false}
        />,
      );

      const fileRefs = screen.getAllByTestId("activity-file-reference");
      expect(fileRefs).toHaveLength(3);
      expect(fileRefs.every((ref) => ref.textContent?.includes("minecraft-fps/index.html"))).toBe(true);
      const failedRow = screen.getByText("Could not edit").closest(
        '[data-testid="activity-step"]',
      );
      expect(failedRow).toBeInTheDocument();
      expect(failedRow).not.toHaveAttribute("title");
      expect(screen.queryByText("patch failed")).not.toBeInTheDocument();
      expect(screen.queryByTestId("file-edit-diff")).not.toBeInTheDocument();
      expect(screen.queryByText("<canvas />")).not.toBeInTheDocument();
      expect(screen.queryByText("const fps = 60;")).not.toBeInTheDocument();
      expect(screen.getAllByText("+2").length).toBeGreaterThan(0);
      expect(screen.getAllByText("-1").length).toBeGreaterThan(0);
      expect(screen.getAllByText("+6").length).toBeGreaterThan(0);
      expect(screen.getAllByText("-6").length).toBeGreaterThan(0);
    } finally {
      localStorage.removeItem("nanobot-webui.settings-preferences");
    }
  });

  it("keeps tool event embeds out of the flat activity list", () => {
    render(
      <AgentActivityCluster
        messages={[{
          id: "t-evidence",
          role: "tool",
          kind: "trace",
          content: 'web_fetch({"url":"https://example.com"})',
          traces: ['web_fetch({"url":"https://example.com"})'],
          toolEvents: [{
            phase: "end",
            call_id: "call-fetch",
            name: "web_fetch",
            arguments: { url: "https://example.com" },
            embeds: [{
              url: "/api/media/signed/screenshot.png",
              name: "Homepage screenshot",
              type: "image/png",
            }],
          }],
          createdAt: 1,
        }]}
        isTurnStreaming
        hasBodyBelow={false}
      />,
    );

    expect(screen.queryByText("Web")).not.toBeInTheDocument();
    const row = screen.getByText("example.com").closest('[data-testid="activity-step"]');
    expect(row).toHaveTextContent("Read");
    expect(screen.queryByTestId("activity-evidence-preview")).not.toBeInTheDocument();
    expect(screen.queryByText(/Found image/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "Homepage screenshot" })).not.toBeInTheDocument();
  });

  it("keeps image generation status to one activity line", () => {
    const message: UIMessage = {
      id: "image-run",
      role: "tool",
      kind: "trace",
      content: 'generate_image({"prompt":"an orange nanobot on a desk","aspect_ratio":"4:3"})',
      traces: ['generate_image({"prompt":"an orange nanobot on a desk","aspect_ratio":"4:3"})'],
      toolEvents: [{
        phase: "start",
        call_id: "image-call",
        name: "generate_image",
        arguments: { prompt: "an orange nanobot on a desk", aspect_ratio: "4:3" },
      }],
      createdAt: 1,
    };
    const { rerender } = render(
      <AgentActivityCluster messages={[message]} isTurnStreaming hasBodyBelow={false} />,
    );

    expect(screen.getByText("Generating image")).toBeInTheDocument();

    rerender(
      <AgentActivityCluster
        messages={[{
          ...message,
          toolEvents: [{
            ...message.toolEvents![0],
            phase: "end",
            files: [{
              url: "/api/media/signed/generated.png",
              name: "generated.png",
              type: "image/png",
            }],
          }],
        }]}
        isTurnStreaming={false}
        hasBodyBelow={false}
      />,
    );

    expect(screen.getByText("Generated image")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "generated.png" })).not.toBeInTheDocument();
  });

  it("keeps image-generation failures visible and actionable", () => {
    render(
      <AgentActivityCluster
        messages={[{
          id: "image-error",
          role: "tool",
          kind: "trace",
          content: 'generate_image({"prompt":"a launch poster"})',
          traces: ['generate_image({"prompt":"a launch poster"})'],
          toolEvents: [{
            phase: "error",
            call_id: "image-error-call",
            name: "generate_image",
            arguments: { prompt: "a launch poster" },
            error: "Image provider quota exceeded",
          }],
          createdAt: 1,
        }]}
        isTurnStreaming={false}
        hasBodyBelow={false}
      />,
    );

    expect(screen.getByText("Could not generate image")).toBeInTheDocument();
    const row = screen.getByText("Could not generate image").closest(
      '[data-testid="activity-step"]',
    );
    expect(row).toBeInTheDocument();
    expect(row).not.toHaveAttribute("title");
    expect(screen.queryByText("Image provider quota exceeded")).not.toBeInTheDocument();
  });

  it("does not add a secondary evidence row when evidence is missing", () => {
    render(
      <AgentActivityCluster
        messages={[{
          id: "t-missing-evidence",
          role: "tool",
          kind: "trace",
          content: 'screenshot({"path":"missing.png"})',
          traces: ['screenshot({"path":"missing.png"})'],
          toolEvents: [{
            phase: "end",
            call_id: "call-shot",
            name: "screenshot",
            arguments: { path: "missing.png" },
            files: [{ name: "missing.png", type: "image/png" }],
          }],
          createdAt: 1,
        }]}
        isTurnStreaming
        hasBodyBelow={false}
      />,
    );

    expect(screen.queryByText("Vision")).not.toBeInTheDocument();
    expect(screen.getByText("Captured screenshot")).toBeInTheDocument();
    expect(screen.queryByTestId("activity-evidence-preview")).not.toBeInTheDocument();
    expect(screen.queryByText("missing.png")).not.toBeInTheDocument();
  });

  it("keeps every default activity action on one structural line", () => {
    render(
      <AgentActivityCluster
        messages={[
          {
            id: "reasoning-line",
            role: "assistant",
            content: "",
            reasoning: "**Planning** the next step\nwithout a nested title",
            reasoningStreaming: false,
            createdAt: 1,
          },
          {
            id: "tool-line",
            role: "tool",
            kind: "trace",
            content: 'grep({"pattern":"needle","path":"workspace/file.txt"})',
            traces: ['grep({"pattern":"needle","path":"workspace/file.txt"})'],
            createdAt: 2,
          },
          {
            id: "fetch-line",
            role: "tool",
            kind: "trace",
            content: 'web_fetch({"url":"https://example.com/docs"})',
            traces: ['web_fetch({"url":"https://example.com/docs"})'],
            createdAt: 3,
          },
        ]}
        isTurnStreaming={false}
        hasBodyBelow={false}
      />,
    );

    const steps = screen.getAllByTestId("activity-step");
    expect(steps.length).toBeGreaterThanOrEqual(3);
    for (const step of steps) {
      expect(step).toHaveClass("grid-cols-[1.125rem_minmax(0,1fr)]");
      const line = step.children[1]?.firstElementChild;
      expect(line).toHaveClass("overflow-hidden");
      expect(line).toHaveClass("whitespace-nowrap");
      expect(step.querySelector("br")).not.toBeInTheDocument();
      expect(step.querySelector('[data-testid="activity-evidence-preview"]')).not.toBeInTheDocument();
    }
    expect(document.querySelector("details")).not.toBeInTheDocument();
    expect(document.querySelector("ul, li, section")).not.toBeInTheDocument();
  });

  it("does not expose tool inputs or credentials in the activity surface", () => {
    const cliLine = 'run_cli_app({"name":"blender","args":["--token","xoxb-1234567890-secret","render"],"json":true})';
    const mcpLine = 'mcp_browserbase_browser_fill({"element":"Password","text":"mcp-private-value"})';
    const genericLine = 'third_party_sync({"token":"sk-proj-1234567890-secret","payload":"private-payload"})';
    const { container } = render(
      <AgentActivityCluster
        messages={[
          {
            id: "private-cli",
            role: "tool",
            kind: "trace",
            content: cliLine,
            traces: [cliLine],
            createdAt: 1,
          },
          {
            id: "private-mcp",
            role: "tool",
            kind: "trace",
            content: mcpLine,
            traces: [mcpLine],
            createdAt: 2,
          },
          {
            id: "private-generic",
            role: "tool",
            kind: "trace",
            content: genericLine,
            traces: [genericLine],
            createdAt: 3,
          },
        ]}
        isTurnStreaming
        hasBodyBelow={false}
        cliApps={[BLENDER_CLI_APP]}
        mcpPresets={[BROWSERBASE_MCP]}
      />,
    );

    expect(container.innerHTML).not.toContain("xoxb-1234567890-secret");
    expect(container.innerHTML).not.toContain("mcp-private-value");
    expect(container.innerHTML).not.toContain("sk-proj-1234567890-secret");
    expect(container.innerHTML).not.toContain("private-payload");
    expect(container.textContent).not.toMatch(/run_cli_app\(|browser_fill\(|third_party_sync\(/);
    expect(container.textContent).toMatch(/<redacted>|••••/);
  });
});
