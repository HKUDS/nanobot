import { useEffect, useState } from "react";

import { ThreadMessages } from "@/components/thread/ThreadMessages";
import { Button } from "@/components/ui/button";
import { formatToolCallTrace } from "@/lib/tool-traces";
import type { ToolProgressEvent, UIMessage } from "@/lib/types";

const turnId = "activity-wheel-demo";
const read: ToolProgressEvent = {
  phase: "start", call_id: "read-brief", name: "read_file", arguments: { path: "workspace/research/brief.md" },
};
const search: ToolProgressEvent = {
  phase: "start", call_id: "search", name: "web_search", arguments: { query: "夜间列车旅行指南" },
};
const results: ToolProgressEvent = {
  ...search,
  phase: "end",
  result: [
    { title: "Night train routes across Europe", url: "https://www.seat61.com/night-trains.htm" },
    { title: "A field guide to sleeper trains", url: "https://www.bbc.com/travel/train-guide" },
    { title: "Planning an overnight rail trip", url: "https://www.nationalgeographic.com/travel/rail" },
  ],
};
const updates = [
  { ...read, phase: "end" },
  search,
  results,
  ...["www.bbc.com", "www.nationalgeographic.com", "www.theguardian.com"].map((host, index): ToolProgressEvent => ({
    phase: "end", call_id: `page-${index}`, name: "web_fetch", arguments: { url: `https://${host}/travel/trains` },
    result: { title: ["How to book a sleeper cabin", "The best overnight rail journeys", "A better way to travel overnight"][index] },
  })),
];

export function ActivityWheelFixture() {
  const [step, setStep] = useState(0);
  const [cadence, setCadence] = useState<number>();
  const [dark, setDark] = useState(false);
  const [startedAt] = useState(Date.now);

  useEffect(() => {
    if (cadence === undefined || step >= updates.length) return;
    const timer = window.setTimeout(() => setStep(step + 1), cadence);
    return () => window.clearTimeout(timer);
  }, [cadence, step]);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  const tools = new Map([read, ...updates.slice(0, step)].map((event) => [event.call_id, event]));
  const toolEvents = [...tools.values()];
  const traces = toolEvents.map((event) => formatToolCallTrace(event)!);
  const messages: UIMessage[] = [
    { id: "question", role: "user", content: "帮我搜几条夜间列车的旅行路线", createdAt: startedAt, turnId },
    { id: "trace", role: "tool", kind: "trace", content: traces.at(-1)!, traces, toolEvents, createdAt: startedAt + 1, turnId },
  ];

  function play(interval: number) {
    setStep(0);
    setCadence(interval);
  }

  return <main className="mx-auto space-y-8 px-5 py-8" style={{ maxWidth: 760 }}>
    <header className="space-y-3">
      <p className="text-xs text-muted-foreground">nanobot · 组件预览 / 模拟活动</p>
      <h1 className="text-xl font-semibold">折叠活动滚轮</h1>
      <p className="text-sm text-muted-foreground">试试慢速或快速播放。点开「处理中」可以看全部记录。</p>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={() => play(850)}>慢速播放</Button>
        <Button variant="outline" size="sm" onClick={() => play(110)}>快速播放</Button>
        <Button variant="outline" size="sm" onClick={() => { setCadence(undefined); setStep((value) => Math.min(value + 1, updates.length)); }}>下一条</Button>
        <Button variant="ghost" size="sm" onClick={() => setDark(!dark)}>切换主题</Button>
      </div>
    </header>
    <ThreadMessages messages={messages} isStreaming activeTurnId={turnId} runStartedAt={startedAt} />
  </main>;
}
