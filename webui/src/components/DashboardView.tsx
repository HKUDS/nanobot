import { useEffect, useState } from "react";
import { 
  BarChart3, 
  ChevronLeft, 
  Coins, 
  Cpu, 
  MessageSquare, 
  Server, 
  TrendingUp,
  Activity,
  History
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { useClient } from "@/providers/ClientProvider";

interface Stats {
  total: {
    prompt_tokens: number;
    completion_tokens: number;
    cached_tokens: number;
    cost: number;
    messages: number;
  };
  by_model: Record<string, {
    prompt_tokens: number;
    completion_tokens: number;
    cost: number;
    messages: number;
  }>;
  by_day: Record<string, {
    prompt_tokens: number;
    completion_tokens: number;
    cost: number;
    messages: number;
  }>;
}

interface MCPStatus {
  servers: Array<{
    name: string;
    type: string;
    enabled_tools: string[];
  }>;
}

export function DashboardView({ onBackToChat }: { onBackToChat: () => void }) {
  const { t } = useTranslation();
  const { token } = useClient();
  const [stats, setStats] = useState<Stats | null>(null);
  const [mcp, setMcp] = useState<MCPStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [statsRes, mcpRes] = await Promise.all([
          fetch(`/api/usage?token=${token}`),
          fetch(`/api/mcp/status?token=${token}`)
        ]);
        if (statsRes.ok) setStats(await statsRes.json());
        if (mcpRes.ok) setMcp(await mcpRes.json());
      } catch (e) {
        console.error("Failed to fetch dashboard data", e);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [token]);

  if (loading) {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <Activity className="h-8 w-8 animate-pulse text-muted-foreground" />
          <span className="text-sm text-muted-foreground">Loading dashboard...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col bg-background">
      <header className="flex h-14 shrink-0 items-center gap-4 border-b px-6">
        <Button variant="ghost" size="icon" onClick={onBackToChat} className="-ml-2 h-9 w-9">
          <ChevronLeft className="h-5 w-5" />
        </Button>
        <div className="flex items-center gap-2">
          <TrendingUp className="h-5 w-5 text-primary" />
          <h1 className="text-lg font-semibold tracking-tight">Dashboard</h1>
        </div>
      </header>

      <ScrollArea className="flex-1">
        <div className="mx-auto flex max-w-5xl flex-col gap-8 p-8 pb-16">
          
          {/* Overview Cards */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard 
              label="Total Cost" 
              value={`$${stats?.total.cost.toFixed(4) || "0.0000"}`} 
              icon={<Coins className="h-4 w-4" />}
              color="text-emerald-500"
            />
            <StatCard 
              label="Messages Sent" 
              value={stats?.total.messages.toLocaleString() || "0"} 
              icon={<MessageSquare className="h-4 w-4" />}
              color="text-blue-500"
            />
            <StatCard 
              label="Total Tokens" 
              value={((stats?.total.prompt_tokens || 0) + (stats?.total.completion_tokens || 0)).toLocaleString()} 
              icon={<Cpu className="h-4 w-4" />}
              color="text-orange-500"
            />
            <StatCard 
              label="MCP Servers" 
              value={mcp?.servers.length.toString() || "0"} 
              icon={<Server className="h-4 w-4" />}
              color="text-purple-500"
            />
          </div>

          <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
            {/* Model Usage Breakdown */}
            <section className="flex flex-col gap-4">
              <div className="flex items-center gap-2">
                <BarChart3 className="h-4 w-4 text-muted-foreground" />
                <h2 className="text-sm font-medium">Model Usage Breakdown</h2>
              </div>
              <div className="rounded-xl border bg-card/30 p-1 shadow-sm">
                <div className="flex flex-col">
                  {stats && Object.entries(stats.by_model).length > 0 ? (
                    Object.entries(stats.by_model).map(([model, data], i) => (
                      <div key={model} className="group">
                        <div className="flex items-center justify-between p-4 transition-colors group-hover:bg-accent/50">
                          <div className="flex flex-col gap-1">
                            <span className="text-sm font-medium">{model}</span>
                            <span className="text-xs text-muted-foreground">
                              {data.messages} messages · {data.prompt_tokens + data.completion_tokens} tokens
                            </span>
                          </div>
                          <div className="text-right">
                            <div className="text-sm font-mono font-medium">${data.cost.toFixed(4)}</div>
                            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Total Cost</div>
                          </div>
                        </div>
                        {i < Object.entries(stats.by_model).length - 1 && <Separator className="mx-4 opacity-50" />}
                      </div>
                    ))
                  ) : (
                    <div className="py-8 text-center text-sm text-muted-foreground">No model usage data recorded yet.</div>
                  )}
                </div>
              </div>
            </section>

            {/* MCP Servers */}
            <section className="flex flex-col gap-4">
              <div className="flex items-center gap-2">
                <Server className="h-4 w-4 text-muted-foreground" />
                <h2 className="text-sm font-medium">Connected MCP Servers</h2>
              </div>
              <div className="flex flex-col gap-3">
                {mcp && mcp.servers.length > 0 ? (
                  mcp.servers.map((server) => (
                    <div key={server.name} className="flex items-center justify-between rounded-xl border bg-card/30 p-4 shadow-sm">
                      <div className="flex items-center gap-3">
                        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                          <Server className="h-5 w-5" />
                        </div>
                        <div className="flex flex-col gap-0.5">
                          <span className="text-sm font-medium">{server.name}</span>
                          <span className="text-xs text-muted-foreground">Type: {server.type}</span>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
                          Connected
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {server.enabled_tools.length === 1 && server.enabled_tools[0] === "*" 
                            ? "All tools enabled" 
                            : `${server.enabled_tools.length} tools enabled`}
                        </span>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">
                    No MCP servers configured. Add them to your environment variables to extend nanobot's capabilities.
                  </div>
                )}
              </div>
            </section>
          </div>

          {/* Activity Feed (placeholder for daily stats) */}
          <section className="flex flex-col gap-4">
            <div className="flex items-center gap-2">
              <History className="h-4 w-4 text-muted-foreground" />
              <h2 className="text-sm font-medium">Daily Activity</h2>
            </div>
            <div className="rounded-xl border bg-card/30 p-1 shadow-sm">
              <div className="flex flex-col">
                {stats && Object.entries(stats.by_day).length > 0 ? (
                  Object.entries(stats.by_day)
                    .sort((a, b) => b[0].localeCompare(a[0]))
                    .map(([day, data], i) => (
                      <div key={day} className="group">
                        <div className="flex items-center justify-between p-4 transition-colors group-hover:bg-accent/50">
                          <span className="text-sm font-medium">{day}</span>
                          <div className="flex items-center gap-8">
                            <div className="flex flex-col items-end gap-0.5">
                              <span className="text-xs font-medium">{data.messages} msg</span>
                              <span className="text-[10px] text-muted-foreground lowercase">Messages</span>
                            </div>
                            <div className="flex flex-col items-end gap-0.5">
                              <span className="text-xs font-medium">{(data.prompt_tokens + data.completion_tokens).toLocaleString()}</span>
                              <span className="text-[10px] text-muted-foreground lowercase">Tokens</span>
                            </div>
                            <div className="w-20 text-right">
                              <div className="text-sm font-mono font-semibold">${data.cost.toFixed(4)}</div>
                            </div>
                          </div>
                        </div>
                        {i < Object.entries(stats.by_day).length - 1 && <Separator className="mx-4 opacity-50" />}
                      </div>
                    ))
                ) : (
                  <div className="py-8 text-center text-sm text-muted-foreground">No activity recorded yet.</div>
                )}
              </div>
            </div>
          </section>

        </div>
      </ScrollArea>
    </div>
  );
}

function StatCard({ label, value, icon, color }: { label: string; value: string; icon: React.ReactNode, color: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-xl border bg-card/30 p-5 shadow-sm transition-all hover:bg-card/50">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          {label}
        </span>
        <div className={color}>{icon}</div>
      </div>
      <div className="text-2xl font-bold tracking-tight">{value}</div>
    </div>
  );
}
