import { describe, expect, it } from "vitest";

import { describeTraceLine } from "@/components/thread/activity/trace-activity-model";
import type { GenericToolStatus } from "@/components/thread/activity/generic-tool-model";

function describeTrace(line: string, status: GenericToolStatus = "done") {
  return describeTraceLine(line, status);
}

describe("trace activity semantics", () => {
  it.each([
    ['web_search({"query":"nanobot latest release"})', "done", "Searched nanobot latest release", ""],
    ['web_fetch({"url":"https://example.com/docs?token=private"})', "done", "Read", "example.com/docs"],
    ['read_file({"path":"/Users/alice/project/README.md"})', "done", "Read", "~/project/README.md"],
    ['exec({"command":"date +%Y-%m-%d"})', "done", "Checked current time", ""],
    ['exec_command({"cmd":"API_KEY=secret npm test"})', "running", "Running command", "API_KEY=•••• npm test"],
    ['write_file({"path":"/home/alice/project/output.txt"})', "done", "Wrote file", "~/project/output.txt"],
    ['apply_patch({"file_path":"src/app.tsx","patch":"private"})', "error", "Could not edit file", "src/app.tsx"],
    ['third_party_sync({"token":"secret","payload":"private"})', "done", "Completed Third party sync", ""],
    ["Finished collecting results", "done", "Completed step", "Finished collecting results"],
  ] as const)("describes %s as one safe activity line", (line, status, label, detail) => {
    const result = describeTrace(line, status);
    expect(result).toMatchObject({ label, detail });
    expect(`${result.label} ${result.detail}`).not.toMatch(/[{}]|private|\/Users\/alice|\/home\/alice/);
  });

  it.each([
    ["running", "Searching status test"],
    ["done", "Searched status test"],
    ["error", "Could not search status test"],
  ] as const)("uses status-aware search copy for %s", (status, label) => {
    expect(describeTrace('web_search({"query":"status test"})', status).label).toBe(label);
  });

  it.each([
    ["running", "Searching X · status test"],
    ["done", "Searched X · status test"],
    ["error", "Could not search X · status test"],
  ] as const)("identifies hosted X search activity for %s", (status, label) => {
    expect(describeTrace('x_search({"query":"status test"})', status).label).toBe(label);
  });

  it("never exposes URL credentials, query secrets, or private-network links", () => {
    const publicResult = describeTrace(
      'web_fetch({"url":"https://user:password@example.com/docs?api_key=secret#section"})',
    );
    expect(publicResult).toMatchObject({ detail: "example.com/docs", host: "example.com" });
    expect(JSON.stringify(publicResult)).not.toMatch(/password|api_key|secret/);

    const privateResult = describeTrace('web_fetch({"url":"http://127.0.0.1:8765/private"})');
    expect(privateResult.url).toBeUndefined();
    expect(privateResult.detail).not.toContain("127.0.0.1");
  });

  it("summarizes multi-line commands without exposing every script line", () => {
    const result = describeTrace(
      'exec({"command":"npm test\\necho second-secret-line\\necho third-line"})',
    );
    expect(result).toMatchObject({
      label: "Ran command",
      detail: "npm test · script, 3 lines",
    });
    expect(result.detail).not.toContain("second-secret-line");
  });
});
