import type { TFunction } from "i18next";

import type { ToolProgressEvent, UIMessage } from "@/lib/types";
import { summarizeShellCommand } from "./activity-text";
import type { ActivityStepTone } from "./ActivityStep";

interface SessionObservation {
  kind: "running" | "stopping" | "exited" | "terminated" | "timeout" | "idle-timeout" | "unknown";
  exitCode?: number;
  waitTimedOut?: boolean;
}

export interface ExecSessionPresentation {
  label: string;
  detail: string;
  aside?: string;
  observation?: string;
  active: boolean;
  tone: ActivityStepTone;
}

const ERROR_HINT = "\n\n[Consider this result in the context of the user's goal and decide whether and how to proceed.]";
const INITIAL_WAIT = "\nInitial wait ended; session remains active.";
const WAIT_TIMEOUT = /\nWait timed out after [\d.]+s; session remains active\.$/;
const WAIT_NOT_OBSERVED = /\nWait target not observed: [^\n]*$/;
const ELAPSED = /\nElapsed: \d+(?:\.\d+)?s$/;

export function toolEventArguments(event: ToolProgressEvent): Record<string, unknown> {
  const functionArgs = (event as { function?: { arguments?: unknown } }).function?.arguments;
  let args = functionArgs ?? event.arguments;
  if (typeof args === "string") {
    try {
      args = JSON.parse(args) as unknown;
    } catch {
      return {};
    }
  }
  return args && typeof args === "object" && !Array.isArray(args) ? args as Record<string, unknown> : {};
}

export function toolEventName(event: ToolProgressEvent): string {
  const functionName = (event as { function?: { name?: unknown } }).function?.name;
  return typeof functionName === "string" ? functionName : typeof event.name === "string" ? event.name : "";
}

/** Only examine the formatter's final lines, never status-like text earlier in output. */
function parseSessionObservation(value: unknown, expectedId?: string): SessionObservation {
  if (typeof value !== "string") return { kind: "unknown" };
  let tail = value.slice(-16_384);
  if (tail.endsWith(ERROR_HINT)) tail = tail.slice(0, -ERROR_HINT.length);
  if (tail.endsWith(INITIAL_WAIT)) tail = tail.slice(0, -INITIAL_WAIT.length);
  const waitTimedOut = WAIT_TIMEOUT.test(tail);
  tail = tail.replace(WAIT_TIMEOUT, "").replace(WAIT_NOT_OBSERVED, "");
  if (!ELAPSED.test(tail)) return { kind: "unknown" };
  tail = tail.replace(ELAPSED, "");

  const running = /(?:^|\n)Process (running|stopping)\. session_id: ([a-f0-9]{12})\n(?:Output silent for \d+(?:\.\d+)?s; no stdout\/stderr bytes observed\. This does not establish a stall\.\n)?Runtime remaining: (?:unlimited|\d+(?:\.\d+)?s)$/.exec(tail);
  if (running && (!expectedId || running[2] === expectedId)) {
    return { kind: running[1] === "running" ? "running" : "stopping", waitTimedOut };
  }

  const exit = /(?:^|\n)Exit code: (-?\d+)$/.exec(tail);
  if (!exit || waitTimedOut) return { kind: "unknown" };
  const exitCode = Number(exit[1]);
  let beforeExit = tail.slice(0, exit.index);
  beforeExit = beforeExit.replace(/(?:^|\n)Stdin closed\.$/, "");
  beforeExit = beforeExit.replace(/(?:^|\n)Output collection ended before EOF; output may be incomplete\.$/, "");
  if (/(?:^|\n)Error: Command timed out; session was terminated\. Reason: max_runtime\.$/.test(beforeExit)) {
    return { kind: "timeout", exitCode };
  }
  if (/(?:^|\n)Error: Output silence limit reached; session was terminated\. Reason: idle_timeout\.$/.test(beforeExit)) {
    return { kind: "idle-timeout", exitCode };
  }
  if (/(?:^|\n)Session terminated\. Reason: (?:cancelled|owner_closed|shutdown)\.$/.test(beforeExit)) {
    return { kind: "terminated", exitCode };
  }
  return { kind: "exited", exitCode };
}

/** Only routine, successful running checks can be folded without hiding another action. */
export function passiveRunningCheckSessionId(event: ToolProgressEvent): string | undefined {
  if (event.phase !== "end") return undefined;
  const args = toolEventArguments(event);
  if (typeof args.session_id !== "string" || args.input != null || args.close_stdin || args.terminate || args.wait_for) return undefined;
  return parseSessionObservation(event.result, args.session_id).kind === "running" ? args.session_id : undefined;
}

export function sessionIdFromExecResult(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const tail = value.slice(-16_384);
  if (!tail.endsWith(INITIAL_WAIT)) return undefined;
  const match = /(?:^|\n)Process (?:running|stopping)\. session_id: ([a-f0-9]{12})\n(?:Output silent for \d+(?:\.\d+)?s; no stdout\/stderr bytes observed\. This does not establish a stall\.\n)?Runtime remaining: (?:unlimited|\d+(?:\.\d+)?s)\nElapsed: \d+(?:\.\d+)?s\nInitial wait ended; session remains active\.$/.exec(tail);
  return match?.[1];
}

/** Build from loaded transcript sources, not the currently visible activity slice. */
export function execSessionCommands(...groups: readonly UIMessage[][]): ReadonlyMap<string, string> {
  const commands = new Map<string, string>();
  const ambiguous = new Set<string>();
  for (const messages of groups) {
    for (const message of messages) {
      for (const event of message.toolEvents ?? []) {
        if (toolEventName(event) !== "exec" || event.phase !== "end") continue;
        const id = sessionIdFromExecResult(event.result);
        if (!id || ambiguous.has(id)) continue;
        const args = toolEventArguments(event);
        const command = typeof args.command === "string" && args.command.trim()
          ? args.command : typeof args.cmd === "string" ? args.cmd : "";
        if (!command.trim()) continue;
        const previous = commands.get(id);
        if (previous !== undefined && previous !== command) {
          commands.delete(id);
          ambiguous.add(id);
        } else {
          commands.set(id, command);
        }
      }
    }
  }
  return commands;
}

function observationLabel(observation: SessionObservation, t: TFunction): { label: string; tone: ActivityStepTone } | undefined {
  const text = (key: string, options?: Record<string, unknown>) => t(`message.agentActivity.${key}`, options);
  switch (observation.kind) {
    case "running":
      return { label: text(observation.waitTimedOut ? "commandWaitTimedOut" : "commandWasRunning"), tone: "neutral" };
    case "stopping":
      return { label: text("commandWasStopping"), tone: "neutral" };
    case "exited":
      return observation.exitCode === 0
        ? { label: text("commandCompleted"), tone: "success" }
        : { label: text("commandExitFailed", { code: observation.exitCode }), tone: "error" };
    case "terminated":
      // This optional line can also be the last line of stdout; only the exit is certain.
      return { label: text("commandExited", { code: observation.exitCode }), tone: "neutral" };
    case "timeout":
      return { label: text("commandTimedOut"), tone: "error" };
    case "idle-timeout":
      return { label: text("commandIdleTimedOut"), tone: "error" };
    default:
      return undefined;
  }
}

export function describeExecSession(
  event: ToolProgressEvent,
  turnActive: boolean,
  command: string | undefined,
  t: TFunction,
): ExecSessionPresentation {
  const args = toolEventArguments(event);
  const hasInput = typeof args.input === "string" && args.input.length > 0;
  const closeInput = args.close_stdin === true;
  const stop = args.terminate === true;
  const action = stop ? "stop" : hasInput && closeInput ? "sendClose" : hasInput ? "send" : closeInput ? "close" : "check";
  const copy = (key: string) => t(`message.agentActivity.${key}`);
  const preview = command ? summarizeShellCommand(command, t) : { detail: "" };

  if (event.phase === "start" || !event.phase) {
    const labels = {
      stop: "stoppingCommand", sendClose: "sendingClosingInput", send: "sendingCommandInput",
      close: "closingCommandInput", check: args.wait_for ? "waitingCommandOutput" : "waitingCommandResult",
    };
    return {
      ...preview,
      label: copy(turnActive ? labels[action] : "commandStatusUnknown"),
      active: turnActive,
      tone: turnActive ? "active" : "neutral",
    };
  }

  if (event.phase !== "end" && event.phase !== "error") {
    return { ...preview, label: copy("commandStatusUnknown"), active: false, tone: "neutral" };
  }

  let observation = parseSessionObservation(
    event.phase === "error" ? event.error : event.result,
    typeof args.session_id === "string" ? args.session_id : undefined,
  );
  // A successful tool return cannot be a runtime timeout. Its stdout may end
  // with text that resembles the optional timeout reason line.
  if (event.phase !== "error" && (observation.kind === "timeout" || observation.kind === "idle-timeout")) {
    observation = { kind: "exited", exitCode: observation.exitCode };
  }
  const observed = observationLabel(observation, t);
  if (event.phase === "error" && observation.kind !== "timeout" && observation.kind !== "idle-timeout") {
    const errors = {
      stop: "stopCommandError", sendClose: "sendCloseInputError", send: "sendInputError",
      close: "closeInputError", check: "checkCommandError",
    };
    return { ...preview, label: copy(errors[action]), active: false, tone: "error" };
  }

  const completed = {
    sendClose: "sentClosedInput", send: "sentCommandInput", close: "closedCommandInput",
  };
  if (action === "send" || action === "close" || action === "sendClose") {
    return {
      ...preview,
      label: copy(completed[action]),
      observation: observed?.label ?? copy("commandStatusUnknown"),
      active: false,
      tone: observed?.tone ?? "neutral",
    };
  }
  return {
    ...preview,
    label: observed?.label ?? copy("commandCheckedUnknown"),
    active: false,
    tone: observed?.tone ?? "neutral",
  };
}
