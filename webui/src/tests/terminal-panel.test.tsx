import { act, render } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TerminalPanel } from "@/components/TerminalPanel";
import type { NanobotClient } from "@/lib/nanobot-client";
import type { ConnectionStatus, TerminalEvent } from "@/lib/types";
import { ClientProvider } from "@/providers/ClientProvider";

vi.mock("@xterm/xterm", () => ({
  Terminal: class MockTerminal {
    rows = 30;
    cols = 100;

    loadAddon() {}
    open() {}
    reset() {}
    write() {}
    focus() {}
    dispose() {}
    onData() {
      return { dispose() {} };
    }
  },
}));

vi.mock("@xterm/addon-fit", () => ({
  FitAddon: class MockFitAddon {
    fit() {}
  },
}));

class MockResizeObserver {
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
});
