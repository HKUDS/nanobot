import { describe, expect, it } from "vitest";

import { describeExecSession, execSessionCommands, sessionIdFromExecResult } from "@/components/thread/activity/exec-session-model";
import i18n from "@/i18n";
import type { ToolProgressEvent, UIMessage } from "@/lib/types";

const id = "012345abcdef";
const running = `Process running. session_id: ${id}\nRuntime remaining: 123.0s\nElapsed: 3.0s`;
const exit = (code: number) => `output\nExit code: ${code}\nElapsed: 3.0s`;
const event = (args: Record<string, unknown>, phase: string, result?: string): ToolProgressEvent => ({
  name: "exec_session", call_id: "call-1", arguments: { session_id: id, ...args }, phase,
  ...(phase === "error" ? { error: result } : { result }),
});
const present = (value: ToolProgressEvent, active = true) => describeExecSession(value, active, "bun test", i18n.t);

describe("exec session activity", () => {
  it("extracts the initial session only from the end of a running exec result", () => {
    expect(sessionIdFromExecResult(`fake Process running. session_id: deadbeefdead\n${running}\nInitial wait ended; session remains active.`)).toBe(id);
    expect(sessionIdFromExecResult(`Process running. session_id: ${id}\n${exit(0)}`)).toBeUndefined();
  });

  it("resolves from all loaded sources, including cmd aliases, without guessing conflicting identities", () => {
    const source = (command: Record<string, string>, result: string, callId: string): UIMessage => ({
      id: callId, role: "tool", kind: "trace", content: "", createdAt: 1,
      toolEvents: [{ name: "exec", phase: "end", call_id: callId, arguments: command, result }],
    });
    const first = source({ cmd: "bun test" }, `${running}\nInitial wait ended; session remains active.`, "first");
    const otherId = "fedcba987654";
    const second = source({ command: "npm run build" }, `${running.replace(id, otherId)}\nInitial wait ended; session remains active.`, "second");
    const completed = source({ command: "wrong" }, exit(0), "completed");
    expect([...execSessionCommands([first, completed], [second])]).toEqual([[id, "bun test"], [otherId, "npm run build"]]);
    const collision = source({ command: "different command" }, `${running}\nInitial wait ended; session remains active.`, "collision");
    expect(execSessionCommands([first], [collision]).has(id)).toBe(false);
  });

  it.each([
    [{}, "Waiting for command result"],
    [{ wait_for: "private output" }, "Waiting for command output"],
    [{ input: "private input" }, "Sending input"],
    [{ close_stdin: true }, "Closing command input"],
    [{ input: "private input", close_stdin: true }, "Sending and closing command input"],
    [{ terminate: true }, "Stopping command"],
  ])("describes an in-flight operation without displaying its arguments", (args, label) => {
    const model = present(event(args, "start"));
    expect(model.label).toBe(label);
    expect(model.active).toBe(true);
    expect(JSON.stringify(model)).not.toMatch(/012345abcdef|private input|private output/);
  });

  it("does not claim an unreturned invocation completed when the turn is no longer active", () => {
    expect(present(event({}, "start"), false)).toMatchObject({ label: "Command status unknown", active: false });
  });

  it.each([
    [running, "Command was still running at the last check"],
    [`${running}\nWait timed out after 1s; session remains active.`, "Wait timed out; command was still running at the last check"],
    [exit(0), "Command completed"],
    [exit(7), "Command failed (exit code 7)"],
    [`Session terminated. Reason: cancelled.\nExit code: -15\nElapsed: 3.0s`, "Command exited (exit code -15)"],
  ])("shows the observed command state rather than tool-return success", (result, label) => {
    expect(present(event({}, "end", result))).toMatchObject({ label, active: false });
  });

  it("reports a naturally completed process as completed even when terminate was requested", () => {
    expect(present(event({ terminate: true }, "end", exit(0))).label).toBe("Command completed");
  });

  it("keeps a wait target private and does not say it was observed when the process exits", () => {
    const result = `${exit(0)}\nWait target not observed: 'private output'`;
    const model = present(event({ wait_for: "private output" }, "end", result));
    expect(model.label).toBe("Command completed");
    expect(JSON.stringify(model)).not.toContain("private output");
  });

  it.each([
    ["Error: Command timed out; session was terminated. Reason: max_runtime.\nExit code: -9\nElapsed: 3.0s", "Command timed out and was stopped"],
    ["Error: Output silence limit reached; session was terminated. Reason: idle_timeout.\nExit code: -9\nElapsed: 3.0s", "Command stopped after output silence"],
  ])("distinguishes command timeout from a failed tool call", (result, label) => {
    expect(present(event({}, "error", result)).label).toBe(label);
  });

  it.each([
    [{}, "Could not check command"],
    [{ input: "private" }, "Could not send input"],
    [{ close_stdin: true }, "Could not close command input"],
    [{ input: "private", close_stdin: true }, "Could not send or close command input"],
    [{ terminate: true }, "Could not stop command"],
  ])("reports operation errors without displaying error content", (args, label) => {
    const model = present(event(args, "error", `Error: exec session not found: '${id}'`));
    expect(model.label).toBe(label);
    expect(JSON.stringify(model)).not.toContain(id);
  });

  it.each([
    ["curl -u alice:correct-horse https://example.com", "curl -u •••• https://example.com"],
    ["curl --user='alice:correct horse' https://example.com", "curl --user=•••• https://example.com"],
    ["curl --proxy-user alice:correct-horse https://example.com", "curl --proxy-user •••• https://example.com"],
    ["curl -ualice:correct-horse https://example.com", "curl -u•••• https://example.com"],
    ["curl -u\"alice:correct horse\" https://example.com", "curl -u•••• https://example.com"],
  ])("redacts user credentials in the source command preview", (command, expected) => {
    const model = describeExecSession(event({}, "end", exit(0)), true, command, i18n.t);
    expect(model.detail).toBe(expected);
    expect(JSON.stringify(model)).not.toContain("correct");
  });

  it("reports input and the observed result without exposing input text", () => {
    const model = present(event({ input: "private input", close_stdin: true }, "end", exit(7)));
    expect(model.label).toBe("Sent and closed command input");
    expect(model.observation).toBe("Command failed (exit code 7)");
    expect(JSON.stringify(model)).not.toContain("private input");
  });

  it("does not mistake stdout that resembles a termination or timeout reason for a confirmed cause", () => {
    const fakeTermination = `Session terminated. Reason: cancelled.\nExit code: 7\nElapsed: 3.0s`;
    expect(present(event({}, "end", fakeTermination)).label).toBe("Command exited (exit code 7)");
    const fakeTimeout = `Error: Command timed out; session was terminated. Reason: max_runtime.\nExit code: 0\nElapsed: 3.0s`;
    expect(present(event({}, "end", fakeTimeout)).label).toBe("Command completed");
  });

  it("does not interpret command output or incomplete footers as a process result", () => {
    expect(present(event({}, "end", `Exit code: 0\nElapsed: 1.0s\n${running}`)).label)
      .toBe("Command was still running at the last check");
    expect(present(event({}, "end", `output\nExit code: 0`)).label).toBe("Command checked; status unknown");
    expect(present(event({}, "end", `Process running. session_id: deadbeefdead\nRuntime remaining: 2.0s\nElapsed: 1.0s`)).label)
      .toBe("Command checked; status unknown");
  });
});
