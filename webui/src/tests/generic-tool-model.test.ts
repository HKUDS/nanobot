import { describe, expect, it } from "vitest";

import { redactActivityText } from "@/components/thread/activity/activity-text";
import {
  describeGenericToolRun,
  parseGenericToolTrace,
  type GenericToolStatus,
} from "@/components/thread/activity/generic-tool-model";

function describeRun(line: string, status: GenericToolStatus = "done") {
  const trace = parseGenericToolTrace(line);
  expect(trace).not.toBeNull();
  return describeGenericToolRun([{ trace: trace!, status }]);
}

describe("generic tool activity semantics", () => {
  it.each([
    ['find_files({"glob":"*.tsx"})', "Found files", "*.tsx"],
    ['grep({"pattern":"dream_cursor"})', "Searched files", "“dream_cursor”"],
    ['list_dir({"path":"memory"})', "Listed files", "memory"],
    ['read_file({"path":"docs/guide.md"})', "Read file", "docs/guide.md"],
    ['memory_search({"query":"launch date"})', "Searched memory", "“launch date”"],
    ['generate_image({"prompt":"private launch art"})', "Generated image", ""],
    ['spawn({"label":"Research competitors","task":"private task"})', "Delegated task", "Research competitors"],
    ['message({"channel":"telegram","content":"private message"})', "Sent message", "telegram"],
    ['my({"action":"check","key":"context_window_tokens"})', "Checked agent settings", "context_window_tokens"],
    ['my({"action":"set","key":"model","value":"private-model"})', "Updated agent settings", "model"],
    ['cron({"action":"add","name":"Daily digest","message":"private prompt"})', "Scheduled automation", "Daily digest"],
    ['cron({"action":"remove","name":"Daily digest"})', "Removed automation", "Daily digest"],
    ['create_goal({"objective":"private objective","ui_summary":"Benchmark memory"})', "Started long task", "Benchmark memory"],
    ['update_goal({"action":"complete","recap":"private recap"})', "Updated long task", "complete"],
    ['write_stdin({"session_id":"session-1234567890-secret","chars":"private input"})', "Continued command", "session…ecret"],
    ['list_exec_sessions({})', "Checked running commands", ""],
    ['screenshot({"path":"artifacts/home.png"})', "Captured screenshot", ""],
    ['third_party_sync({"token":"secret","payload":"private payload"})', "Completed Third party sync", ""],
  ])("describes %s without exposing implementation syntax", (line, label, detail) => {
    const presentation = describeRun(line);
    expect(presentation.label).toBe(label);
    expect(presentation.detail).toBe(detail);
    expect(`${presentation.label} ${presentation.detail}`).not.toMatch(/[{}]|private|tool-results/);
  });

  it.each([
    ["running", "Generating image"],
    ["done", "Generated image"],
    ["error", "Could not generate image"],
  ] as const)("uses human status copy for %s tools", (status, label) => {
    expect(describeRun('generate_image({"prompt":"private"})', status).label).toBe(label);
  });

  it("groups searches over collected sources without exposing absolute paths", () => {
    const first = parseGenericToolTrace(
      'grep({"pattern":"July","path":"/Users/test/.nanobot/tool-results/session/call_first.txt"})',
    )!;
    const second = parseGenericToolTrace(
      'grep({"pattern":"OpenAI","path":"/Users/test/.nanobot/tool-results/session/call_second.txt"})',
    )!;
    const presentation = describeGenericToolRun([
      { trace: first, status: "done" },
      { trace: second, status: "done" },
    ]);

    expect(presentation).toMatchObject({ label: "Reviewed sources", detail: "", aside: "2 files" });
    expect(JSON.stringify(presentation)).not.toContain("/Users/test");
  });

  it("leaves specialized tools to their dedicated activity surfaces", () => {
    for (const line of [
      'web_search({"query":"nanobot"})',
      'web_fetch({"url":"https://example.com"})',
      'exec({"command":"date"})',
      'write_file({"path":"README.md"})',
      'edit_file({"path":"README.md"})',
      'apply_patch({"patch":"private"})',
      'run_cli_app({"name":"github"})',
      'mcp_browser_click({"text":"private"})',
    ]) {
      expect(parseGenericToolTrace(line)).toBeNull();
    }
  });

  it.each([
    ["Authorization: Bearer top-secret-token", "Authorization: <redacted>"],
    ["API_KEY=sk-proj-1234567890abcdef", "API_KEY=<redacted>"],
    ["--token xoxb-1234567890-secret", "--token <redacted>"],
    ["https://user:password@example.com/file?access_token=signed-secret", "https://<redacted>@example.com/file?access_token=<redacted>"],
    ["github ghp_1234567890abcdefghijkl", "github <redacted>"],
    ["aws AKIA1234567890ABCDEF", "aws <redacted>"],
    ["telegram 123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcd", "telegram <redacted>"],
  ])("redacts activity text before rendering: %s", (input, expected) => {
    expect(redactActivityText(input)).toBe(expected);
  });
});
