import { act, render, screen } from "@testing-library/react";
import { createInstance } from "i18next";
import { describe, expect, it } from "vitest";

import { AgentActivityCluster } from "@/components/thread/AgentActivityCluster";
import { describeGenericToolRun, parseGenericToolTrace } from "@/components/thread/activity/generic-tool-model";
import { describeMcpActivity } from "@/components/thread/activity/mcp-activity-model";
import { describeTraceLine } from "@/components/thread/activity/trace-activity-model";
import { presentWebSearchAction } from "@/components/thread/activity/web-search-model";
import i18n, { resources, setAppLanguage } from "@/i18n";
import { supportedLocales } from "@/i18n/config";
import type { UIMessage } from "@/lib/types";

function placeholders(value: string): string[] {
  return [...value.matchAll(/{{\s*(\w+)\s*}}/g)].map((match) => match[1]).sort();
}

describe("localized agent activity contracts", () => {
  it.each(supportedLocales.map(({ code }) => code))("keeps complete activity resources and interpolation in %s", async (locale) => {
    const english = resources.en.common.message.agentActivity;
    const translated = resources[locale].common.message.agentActivity;
    expect(Object.keys(translated).sort()).toEqual(Object.keys(english).sort());
    for (const key of Object.keys(english) as (keyof typeof english)[]) {
      expect(translated[key].trim(), key).not.toBe("");
      expect(placeholders(translated[key]), key).toEqual(placeholders(english[key]));
    }
    expect(translated.actionTargetRich).toContain("<action>{{action}}</action>");
    expect(translated.actionTargetRich).toContain("<target></target>");

    await setAppLanguage(locale);
    const trace = parseGenericToolTrace('read_file({"path":"src/app.tsx"})')!;
    for (const status of ["running", "done", "error"] as const) {
      const generic = describeGenericToolRun([{ trace, status }], i18n.t);
      const command = describeTraceLine('exec({"command":"bun run test"})', status, i18n.t);
      const browser = describeMcpActivity("browser_press_key", { key: "Enter" }, status, i18n.t);
      const search = presentWebSearchAction("release notes", status, "web", i18n.t);
      expect(generic.detail).toBe("src/app.tsx");
      expect(command.detail).toBe("bun run test");
      expect(browser.target).toBe("Enter");
      expect(search).toContain("release notes");
      expect([generic.label, command.label, browser.action, search].join(" "))
        .not.toMatch(/message\.agentActivity|{{/);
    }
    for (const count of [0, 1, 2]) {
      for (const key of ["files", "searches", "actions", "scriptLines"]) {
        const result = i18n.t(`message.agentActivity.${key}`, { count });
        expect(result).toContain(String(count));
        expect(result).not.toMatch(/message\.agentActivity|{{/);
      }
    }
  });

  it("falls back to English for a missing localized activity key", async () => {
    const instance = createInstance();
    await instance.init({
      lng: "zh-CN",
      fallbackLng: "en",
      defaultNS: "common",
      resources: { en: { common: resources.en.common }, "zh-CN": { common: {} } },
    });
    const trace = parseGenericToolTrace('read_file({"path":"src/app.tsx"})')!;
    expect(describeGenericToolRun([{ trace, status: "done" }], instance.t))
      .toMatchObject({ label: "Read file", detail: "src/app.tsx" });
  });

  it("relocalizes completed replay and failed searches without mutating the recorded data", async () => {
    const messages: UIMessage[] = [{
      id: "activity-replay",
      role: "tool",
      kind: "trace",
      content: 'exec({"command":"bun run test"})',
      traces: ['exec({"command":"bun run test"})', 'web_search({"query":"release notes"})'],
      toolEvents: [{
        phase: "error",
        call_id: "failed-search",
        name: "web_search",
        arguments: { query: "release notes" },
        error: "upstream search unavailable",
      }],
      createdAt: 1,
    }];
    const original = JSON.stringify(messages);
    render(<AgentActivityCluster messages={messages} isTurnStreaming={false} hasBodyBelow expanded />);
    expect(screen.getByText("Ran command bun run test")).toBeInTheDocument();
    expect(screen.getByText("Could not search release notes")).toBeInTheDocument();

    await act(async () => setAppLanguage("zh-CN"));
    expect(screen.getByText("已运行命令 bun run test")).toBeInTheDocument();
    expect(screen.getByText("无法搜索 release notes")).toBeInTheDocument();
    await act(async () => setAppLanguage("en"));
    expect(screen.getByText("Could not search release notes")).toBeInTheDocument();
    expect(JSON.stringify(messages)).toBe(original);
  });
});
