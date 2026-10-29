import { useEffect, useState } from "react";
import { AgentActivityCluster } from "@/components/thread/AgentActivityCluster";
import { formatToolCallTrace } from "@/lib/tool-traces";
import type { CliAppInfo, McpPresetInfo, UIMessage } from "@/lib/types";

const cliApp: CliAppInfo = {
  name: "blender", display_name: "Blender", category: "3d", description: "Preview app",
  requires: "", source: "harness", entry_point: "cli-anything-blender",
  install_supported: true, installed: true, available: true, status: "installed",
  logo_url: "https://cdn.simpleicons.org/blender", brand_color: "#E87D0D", skill_installed: true,
};
const preset: McpPresetInfo = {
  name: "linear", display_name: "Linear", category: "productivity", description: "Preview app",
  docs_url: "https://linear.app", transport: "streamableHttp", requires: "", note: "",
  install_supported: true, installed: true, configured: true, available: true, status: "configured",
  logo_url: "https://icons.duckduckgo.com/ip3/linear.app.ico", brand_color: "#6D5DF6",
  required_fields: [], connection_summary: "Preview only",
};

function messages(phase: "start" | "end" | "error"): UIMessage[] {
  const toolEvents = [
    { name: "mcp_linear_get_workspace", args: {} },
    { name: "run_cli_app", args: { name: "blender", args: ["--background", "scene.blend"], json: true } },
  ].map(({ name, args }) => ({ phase, call_id: `${phase}-${name}`, name, arguments: args,
    ...(phase === "error" ? { error: "Preview failure" } : {}) }));
  const traces = toolEvents.map(event => formatToolCallTrace(event)!);
  return [{
    id: `${phase}-tools`, role: "tool", kind: "trace", createdAt: 1,
    content: traces.join("\n"), traces, toolEvents,
  }];
}

export function ActivityLogosFixture({ parameters }: { parameters: URLSearchParams }) {
  const [dark, setDark] = useState(parameters.has("dark"));
  useEffect(() => { document.documentElement.classList.toggle("dark", dark); }, [dark]);
  const fallback = parameters.has("fallback");
  return <main className="mx-auto max-w-2xl space-y-6 p-6">
    <header className="flex items-center justify-between gap-4 text-sm">
      <h1>Activity logo preview</h1>
      <button onClick={() => setDark(value => !value)}>Toggle theme</button>
    </header>
    {(["end", "start", "error"] as const).map((phase) => (
      <section key={phase} aria-label={phase} className="space-y-2">
        <h2 className="text-xs text-muted-foreground">{phase === "start" ? "Running" : phase === "end" ? "Completed" : "Failed"}</h2>
        <AgentActivityCluster messages={messages(phase)} isTurnStreaming={phase === "start"}
          hasBodyBelow={false} expanded
          cliApps={[fallback ? { ...cliApp, logo_url: null } : cliApp]}
          mcpPresets={[fallback ? { ...preset, logo_url: "/browser/missing-activity-logo.svg" } : preset]} />
      </section>
    ))}
  </main>;
}
