import { AsyncLocalStorage } from "node:async_hooks";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import readline from "node:readline";

const PROTOCOL = 1;
const invocations = new AsyncLocalStorage();
const state = {
  runtime: null,
  identity: null,
  workspace: process.cwd(),
  config: {},
  tools: new Map(),
  commands: new Map(),
  hooks: new Map(),
  registrations: [],
  diagnostics: [],
};

const writeError = (...parts) => process.stderr.write(`${parts.map(String).join(" ")}\n`);
console.log = writeError;
console.info = writeError;
console.warn = writeError;
console.error = writeError;

function sanitize(value, depth = 0, seen = new WeakSet()) {
  if (depth > 12) return "[max depth]";
  if (value === null || ["string", "number", "boolean"].includes(typeof value)) return value;
  if (typeof value === "bigint") return String(value);
  if (typeof value === "function" || typeof value === "undefined") return undefined;
  if (typeof value !== "object") return String(value);
  if (seen.has(value)) return "[circular]";
  seen.add(value);
  if (Array.isArray(value)) return value.map((item) => sanitize(item, depth + 1, seen));
  return Object.fromEntries(
    Object.entries(value)
      .map(([key, item]) => [key, sanitize(item, depth + 1, seen)])
      .filter(([, item]) => item !== undefined),
  );
}

function addRegistration(kind, name, options = {}) {
  const registration = {
    kind,
    name: String(name),
    description: String(options.description || ""),
    ...(options.schema ? { schema: sanitize(options.schema) } : {}),
    ...(options.metadata ? { metadata: sanitize(options.metadata) } : {}),
  };
  const index = state.registrations.findIndex(
    (item) => item.kind === registration.kind && item.name === registration.name,
  );
  if (index >= 0) state.registrations[index] = registration;
  else state.registrations.push(registration);
}

function unsupported(name) {
  if (!state.diagnostics.includes(`Unsupported compatibility API: ${name}`)) {
    state.diagnostics.push(`Unsupported compatibility API: ${name}`);
  }
}

function unsupportedFacade(path) {
  const fn = () => {
    throw new Error(`${path} is not available in the nanobot compatibility host`);
  };
  return new Proxy(fn, {
    get: (_, key) => unsupportedFacade(`${path}.${String(key)}`),
  });
}

function addHook(name, handler, flavor) {
  const names = Array.isArray(name) ? name : [name];
  for (const item of names) {
    const key = String(item);
    const handlers = state.hooks.get(key) || [];
    handlers.push({ handler, flavor });
    state.hooks.set(key, handlers);
    addRegistration("hook", key);
  }
}

function addTool(tool, flavor, options = {}) {
  if (typeof tool === "function") {
    const resolved = tool({
      config: state.config,
      runtimeConfig: state.config,
      getRuntimeConfig: () => state.config,
      workspaceDir: state.workspace,
      sandboxed: false,
    });
    for (const item of Array.isArray(resolved) ? resolved : [resolved]) {
      if (item) addTool(item, flavor, options);
    }
    return;
  }
  if (!tool || typeof tool !== "object" || typeof tool.name !== "string") {
    throw new Error("registered tool must define a name");
  }
  if (state.tools.has(tool.name)) {
    throw new Error(`tool '${tool.name}' is already registered by this extension`);
  }
  state.tools.set(tool.name, { tool, flavor });
  addRegistration("tool", tool.name, {
    description: tool.description,
    schema: tool.parameters || { type: "object", properties: {} },
    metadata: {
      label: tool.label,
      optional: options.optional === true,
      readOnly: tool.readOnly === true,
    },
  });
}

function invocationOutput(value) {
  const context = invocations.getStore();
  if (context) context.outputs.push(value);
}

function addCommand(name, command, flavor) {
  const normalized = String(name);
  if (state.commands.has(normalized)) {
    throw new Error(`command '${normalized}' is already registered by this extension`);
  }
  state.commands.set(normalized, { command, flavor });
  addRegistration("command", normalized, { description: command?.description });
}

function eventBus() {
  return {
    on: (name, handler) => addHook(`event:${name}`, handler, "pi-event"),
    emit: async (name, data) => emitEvent(`event:${name}`, data),
  };
}

function piApi() {
  const api = {
    on: (name, handler) => addHook(name, handler, "pi"),
    registerTool: (tool) => addTool(tool, "pi"),
    registerCommand: (name, options) => addCommand(name, options, "pi"),
    registerProvider: (nameOrProvider, config) => {
      const provider =
        typeof nameOrProvider === "string"
          ? { id: nameOrProvider, ...config }
          : nameOrProvider;
      addRegistration("llm_provider", provider.id || provider.name, {
        description: provider.name,
        metadata: provider,
      });
    },
    unregisterProvider: () => {},
    sendMessage: (message) => invocationOutput(message?.content || message),
    sendUserMessage: (message) => invocationOutput(message),
    appendEntry: () => unsupported("pi.appendEntry"),
    setSessionName: () => unsupported("pi.setSessionName"),
    getSessionName: () => undefined,
    setLabel: () => unsupported("pi.setLabel"),
    getActiveTools: () => [],
    getAllTools: () => [],
    setActiveTools: () => unsupported("pi.setActiveTools"),
    getCommands: () => [],
    registerShortcut: () => unsupported("pi.registerShortcut"),
    registerFlag: () => unsupported("pi.registerFlag"),
    getFlag: () => undefined,
    registerMessageRenderer: () => unsupported("pi.registerMessageRenderer"),
    registerEntryRenderer: () => unsupported("pi.registerEntryRenderer"),
    exec: unsupportedFacade("pi.exec"),
    setModel: async () => false,
    getThinkingLevel: () => "off",
    setThinkingLevel: () => unsupported("pi.setThinkingLevel"),
    events: eventBus(),
  };
  return new Proxy(api, {
    get(target, key) {
      if (key in target) return target[key];
      unsupported(`pi.${String(key)}`);
      return unsupportedFacade(`pi.${String(key)}`);
    },
  });
}

function openClawApi() {
  const identity = state.identity;
  const api = {
    id: identity.id,
    name: identity.name,
    version: identity.version,
    source: state.entries[0],
    rootDir: state.rootDir,
    registrationMode: "activate",
    config: state.config,
    pluginConfig: state.config,
    runtime: unsupportedFacade("openclaw.runtime"),
    logger: {
      debug: writeError,
      info: writeError,
      warn: writeError,
      error: writeError,
    },
    registerTool: (tool, options) => addTool(tool, "openclaw", options),
    registerCommand: (command) => addCommand(command.name, command, "openclaw"),
    registerHook: (names, handler) => addHook(names, handler, "openclaw"),
    on: (name, handler) => addHook(name, handler, "openclaw"),
    registerProvider: (provider) =>
      addRegistration("llm_provider", provider.id, {
        description: provider.label,
        metadata: provider,
      }),
    registerRealtimeTranscriptionProvider: (provider) =>
      addRegistration("transcription_provider", provider.id, {
        description: provider.label,
        metadata: provider,
      }),
    registerImageGenerationProvider: (provider) =>
      addRegistration("image_generation_provider", provider.id, {
        description: provider.label,
        metadata: provider,
      }),
    registerWebSearchProvider: (provider) =>
      addRegistration("web_search_provider", provider.id, {
        description: provider.label,
        metadata: provider,
      }),
    resolvePath: (value) => new URL(value, pathToFileURL(`${state.rootDir}/`)).pathname,
  };
  const grouped = unsupportedFacade("openclaw");
  api.session = grouped.session;
  api.agent = grouped.agent;
  api.runContext = grouped.runContext;
  api.lifecycle = grouped.lifecycle;
  return new Proxy(api, {
    get(target, key) {
      if (key in target) return target[key];
      if (String(key).startsWith("register")) unsupported(`openclaw.${String(key)}`);
      return (..._args) => unsupported(`openclaw.${String(key)}`);
    },
  });
}

function unwrapModule(value) {
  const seen = new Set();
  let current = value;
  for (let index = 0; index < 12 && current && !seen.has(current); index += 1) {
    seen.add(current);
    if (typeof current === "function" || typeof current?.register === "function") return current;
    current = current.default ?? current.module;
  }
  return current;
}

async function importModule(entry) {
  try {
    return await import(`${pathToFileURL(entry).href}?nanobot=${Date.now()}`);
  } catch (error) {
    if (![".ts", ".tsx", ".cts", ".mts"].some((suffix) => entry.endsWith(suffix))) throw error;
    try {
      const imported = createRequire(pathToFileURL(entry))("jiti");
      const createJiti = imported.createJiti || imported.default || imported;
      return await createJiti(import.meta.url, { interopDefault: true }).import(entry);
    } catch (jitiError) {
      throw new Error(
        `Could not load TypeScript extension. Use Node.js with type stripping or install jiti. ${jitiError.message}`,
        { cause: error },
      );
    }
  }
}

async function loadExtension(params) {
  if (!["pi", "openclaw"].includes(params.runtime)) {
    throw new Error(`unsupported Node extension runtime: ${params.runtime}`);
  }
  state.runtime = params.runtime;
  state.identity = params.identity;
  state.workspace = params.workspace;
  state.config = params.config || {};
  state.entries = params.entries;
  state.rootDir = params.root;
  state.tools.clear();
  state.commands.clear();
  state.hooks.clear();
  state.registrations.length = 0;
  state.diagnostics.length = 0;

  for (const entry of params.entries) {
    const loaded = unwrapModule(await importModule(entry));
    const factory =
      params.runtime === "openclaw" && typeof loaded?.register === "function"
        ? loaded.register
        : loaded;
    if (typeof factory !== "function") {
      throw new Error(`extension entry does not export a factory: ${entry}`);
    }
    const result = factory(params.runtime === "pi" ? piApi() : openClawApi());
    if (params.runtime === "openclaw" && result?.then) {
      throw new Error("OpenClaw plugin register must be synchronous");
    }
    if (params.runtime === "pi") await result;
  }
  return {
    registrations: state.registrations,
    diagnostics: state.diagnostics,
  };
}

function contextApi() {
  return {
    mode: "rpc",
    hasUI: false,
    cwd: state.workspace,
    signal: undefined,
    ui: new Proxy(
      { notify: (message) => invocationOutput(message) },
      { get: (target, key) => target[key] || unsupportedFacade(`pi.ui.${String(key)}`) },
    ),
    isIdle: () => true,
    isProjectTrusted: () => true,
    hasPendingMessages: () => false,
    getContextUsage: () => undefined,
    getSystemPrompt: () => "",
  };
}

function resultText(result, outputs = []) {
  const values = [...outputs];
  if (result !== undefined) values.push(result);
  const text = [];
  for (const value of values) {
    if (typeof value === "string") text.push(value);
    else if (typeof value?.text === "string") text.push(value.text);
    else if (typeof value?.content === "string") text.push(value.content);
    else if (Array.isArray(value?.content)) {
      for (const item of value.content) {
        if (typeof item === "string") text.push(item);
        else if (typeof item?.text === "string") text.push(item.text);
      }
    } else if (value !== undefined) text.push(JSON.stringify(sanitize(value)));
  }
  return text.filter(Boolean).join("\n");
}

async function callExtension(params) {
  const context = { outputs: [] };
  return invocations.run(context, async () => {
    if (params.kind === "tool") {
      const record = state.tools.get(params.name);
      if (!record) throw new Error(`unknown tool: ${params.name}`);
      const result = await record.tool.execute(
        params.callId || "nanobot",
        params.input || {},
        undefined,
        undefined,
        ...(record.flavor === "pi" ? [contextApi()] : []),
      );
      return { text: resultText(result, context.outputs), raw: sanitize(result) };
    }
    if (params.kind === "command") {
      const record = state.commands.get(params.name);
      if (!record) throw new Error(`unknown command: ${params.name}`);
      const input = params.input || {};
      const result =
        record.flavor === "pi"
          ? await record.command.handler(input.args || "", contextApi())
          : await record.command.handler({
              args: input.args || "",
              commandBody: input.raw || `/${params.name}`,
              channel: input.channel || "websocket",
              senderId: input.senderId,
              isAuthorizedSender: true,
              config: state.config,
              sessionKey: input.sessionKey,
              requestConversationBinding: async () => ({ ok: false }),
              detachConversationBinding: async () => ({ removed: false }),
              getCurrentConversationBinding: async () => null,
            });
      return { text: resultText(result, context.outputs), raw: sanitize(result) };
    }
    throw new Error(`unsupported callable kind: ${params.kind}`);
  });
}

async function emitEvent(name, event) {
  const handlers = state.hooks.get(name) || [];
  const results = [];
  for (const { handler, flavor } of handlers) {
    results.push(
      await handler(event, flavor === "pi" ? contextApi() : { config: state.config }),
    );
  }
  return { results: sanitize(results) };
}

async function dispatch(method, params) {
  if (method === "hello") {
    return { protocol: PROTOCOL, node: process.version };
  }
  if (method === "extension.load") return loadExtension(params);
  if (method === "extension.call") return callExtension(params);
  if (method === "extension.event") return emitEvent(params.name, params.event);
  if (method === "shutdown") {
    queueMicrotask(() => process.exit(0));
    return {};
  }
  throw new Error(`unknown method: ${method}`);
}

let queue = Promise.resolve();
const lines = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
lines.on("line", (line) => {
  queue = queue.then(async () => {
    let request;
    try {
      request = JSON.parse(line);
      if (request.protocol !== PROTOCOL) throw new Error("protocol version mismatch");
      const result = await dispatch(request.method, request.params || {});
      process.stdout.write(`${JSON.stringify({ id: request.id, result: sanitize(result) })}\n`);
    } catch (error) {
      process.stdout.write(
        `${JSON.stringify({
          id: request?.id ?? null,
          error: { code: "extension_error", message: String(error?.message || error) },
        })}\n`,
      );
    }
  });
});
