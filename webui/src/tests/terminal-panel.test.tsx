import { act, render } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TerminalPanel } from "@/components/TerminalPanel";
import type { NanobotClient } from "@/lib/nanobot-client";
import type { ConnectionStatus, TerminalEvent } from "@/lib/types";
import { ClientProvider } from "@/providers/ClientProvider";

let terminalInstances: Array<{
  rows: number;
  cols: number;
  options: { windowsPty?: { backend: string; buildNumber?: number } };
}> = [];
let fitCols = 100;
let resizeObserverCallbacks: ResizeObserverCallback[] = [];

vi.mock("@xterm/xterm", () => ({
  Terminal: class MockTerminal {
    rows = 30;
    cols = 100;
    options = {};

    constructor() {
      terminalInstances.push(this);
    }

    loadAddon(addon: { activate?: (terminal: MockTerminal) => void }) {
      addon.activate?.(this);
    }
    open(container: HTMLElement) {
      Object.defineProperty(container, "clientWidth", { configurable: true, value: 560 });
      Object.defineProperty(container, "clientHeight", { configurable: true, value: 500 });
    }
    reset() {}
    write(_data: string, callback?: () => void) {
      callback?.();
    }
    focus() {}
    dispose() {}
    onData() {
      return { dispose() {} };
    }
  },
}));

vi.mock("@xterm/addon-fit", () => ({
  FitAddon: class MockFitAddon {
    terminal?: { cols: number };
    activate(terminal: { cols: number }) {
      this.terminal = terminal;
    }
    fit() {
      if (this.terminal) this.terminal.cols = fitCols;
    }
  },
}));

class MockResizeObserver {
  constructor(callback: ResizeObserverCallback) {
    resizeObserverCallbacks.push(callback);
  }
  observe() {}
  disconnect() {}
  unobserve() {}
}

function makeClient(initialStatus: ConnectionStatus) {
  let status = initialStatus;
  const statusHandlers = new Set<(value: ConnectionStatus) => void>();
  const terminalHandlers = new Set<(event: TerminalEvent) => void>();
  const client = {
    get status() {
      return status;
    },
    openTerminal: vi.fn(),
    resizeTerminal: vi.fn(),
    writeTerminal: vi.fn(),
    detachTerminal: vi.fn(),
    killTerminal: vi.fn(),
    attach: vi.fn(),
    onStatus(handler: (value: ConnectionStatus) => void) {
      statusHandlers.add(handler);
      handler(status);
      return () => statusHandlers.delete(handler);
    },
    onTerminal(_chatId: string, handler: (event: TerminalEvent) => void) {
      terminalHandlers.add(handler);
      return () => terminalHandlers.delete(handler);
    },
    emitStatus(value: ConnectionStatus) {
      status = value;
      for (const handler of statusHandlers) handler(value);
    },
    emitTerminal(event: TerminalEvent) {
      for (const handler of terminalHandlers) handler(event);
    },
  };
  return client;
}

function wrap(client: ReturnType<typeof makeClient>, children: ReactNode) {
  return (
    <ClientProvider client={client as unknown as NanobotClient} token="token">
      {children}
    </ClientProvider>
  );
}

describe("TerminalPanel", () => {
  beforeEach(() => {
    terminalInstances = [];
    fitCols = 100;
    resizeObserverCallbacks = [];
    vi.stubGlobal("ResizeObserver", MockResizeObserver);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("opens once when an initially connecting client becomes ready and once per reconnect", async () => {
    const client = makeClient("connecting");
    const view = render(wrap(
      client,
      <TerminalPanel
        chatId="chat-1"
        projectPath="/projects/nanobot"
        onClose={() => {}}
      />,
    ));
    await act(async () => {
      await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
    });
    expect(client.openTerminal).not.toHaveBeenCalled();

    act(() => client.emitStatus("open"));
    expect(client.openTerminal).toHaveBeenCalledTimes(1);

    act(() => client.emitStatus("reconnecting"));
    act(() => client.emitStatus("open"));
    expect(client.openTerminal).toHaveBeenCalledTimes(2);

    view.unmount();
  });

  it("applies Windows PTY compatibility and resizes after both drag directions", async () => {
    const client = makeClient("open");
    const view = render(wrap(
      client,
      <TerminalPanel
        chatId="chat-1"
        projectPath="C:\\projects\\nanobot"
        onClose={() => {}}
      />,
    ));
    await act(async () => {
      await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
    });

    act(() => client.emitTerminal({
      event: "terminal_ready",
      chat_id: "chat-1",
      terminal_id: "term-1",
      project_path: "C:\\projects\\nanobot",
      rows: 30,
      cols: 100,
      data: "old output\r\n",
      seq: 1,
      running: true,
      exit_code: null,
      pty_backend: "conpty",
      windows_build: 26100,
    }));
    await act(async () => {
      await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
    });

    expect(terminalInstances[0].options.windowsPty).toEqual({
      backend: "conpty",
      buildNumber: 26100,
    });
    expect(client.resizeTerminal).toHaveBeenCalledWith("chat-1", "term-1", 30, 100);

    fitCols = 48;
    act(() => resizeObserverCallbacks[0]?.([], {} as ResizeObserver));
    await act(async () => {
      await new Promise<void>((resolve) => requestAnimationFrame(() => {
        requestAnimationFrame(() => resolve());
      }));
    });
    expect(client.resizeTerminal).toHaveBeenCalledWith("chat-1", "term-1", 30, 48);

    fitCols = 132;
    act(() => resizeObserverCallbacks[0]?.([], {} as ResizeObserver));
    await act(async () => {
      await new Promise<void>((resolve) => requestAnimationFrame(() => {
        requestAnimationFrame(() => resolve());
      }));
    });
    expect(client.resizeTerminal).toHaveBeenCalledWith("chat-1", "term-1", 30, 132);

    view.unmount();
  });
});
