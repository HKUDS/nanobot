export const RUNTIME_CONTROLS_CAPABILITY = "webui.runtime-controls.v1";

export interface RuntimeControlsReady {
  gateway_id?: string;
  capabilities?: string[];
}

export interface ModelSelectionResult {
  model_preset: string | null;
  model_name: string;
  context_window_tokens: number;
}

export interface StopResult {
  status: "stopped" | "idle" | "stale";
  stopped_tasks: number;
  turn_id: string | null;
}

export interface RestartResult {
  status: "accepted";
  gateway_id: string;
}

export class RuntimeControlError extends Error {
  constructor(public status: number, message: string, public outcomeUnknown = false) {
    super(message);
    this.name = "RuntimeControlError";
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function gatewayIdFromReady(value: unknown): string | null {
  return record(value) && value.event === "ready" && typeof value.chat_id === "string"
    && typeof value.client_id === "string" && typeof value.gateway_id === "string" && value.gateway_id.trim()
    ? value.gateway_id : null;
}

/** Only the current socket's ready frame can authorize a runtime control. */
export function runtimeControlsGateway(value: unknown): string | null {
  return record(value) && Array.isArray(value.capabilities) && value.capabilities.every((item) => typeof item === "string")
    && value.capabilities.includes(RUNTIME_CONTROLS_CAPABILITY) ? gatewayIdFromReady(value) : null;
}

export function parseModelSelection(value: unknown): ModelSelectionResult {
  if (!record(value) || !(value.model_preset === null || typeof value.model_preset === "string")
    || typeof value.model_name !== "string" || typeof value.context_window_tokens !== "number"
    || !Number.isFinite(value.context_window_tokens) || value.context_window_tokens < 0) {
    throw new RuntimeControlError(502, "Model selection result is unconfirmed", true);
  }
  return { model_preset: value.model_preset, model_name: value.model_name,
    context_window_tokens: value.context_window_tokens };
}

export function parseStopResult(value: unknown): StopResult {
  if (!record(value) || !(value.status === "stopped" || value.status === "idle" || value.status === "stale")
    || typeof value.stopped_tasks !== "number" || !Number.isInteger(value.stopped_tasks) || value.stopped_tasks < 0
    || !(value.turn_id === null || typeof value.turn_id === "string")) {
    throw new RuntimeControlError(502, "Stop result is unconfirmed", true);
  }
  return { status: value.status, stopped_tasks: value.stopped_tasks, turn_id: value.turn_id };
}

export function parseRestartResult(value: unknown): RestartResult {
  if (!record(value) || value.status !== "accepted" || typeof value.gateway_id !== "string" || !value.gateway_id.trim()) {
    throw new RuntimeControlError(502, "Restart result is unconfirmed", true);
  }
  return { status: value.status, gateway_id: value.gateway_id };
}
