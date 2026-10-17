import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CredentialRequestCard } from "@/components/thread/CredentialRequestCard";
import { NanobotClient } from "@/lib/nanobot-client";
import type { CredentialRequestUIData } from "@/lib/types";

/** Minimal fake WebSocket: enough for NanobotClient's send path. */
class FakeSocket {
  static instances: FakeSocket[] = [];
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.readyState = 3;
    this.onclose?.();
  }

  fakeOpen() {
    this.readyState = 1;
    this.onopen?.();
  }
}

const { clientRef } = vi.hoisted(() => ({
  clientRef: { current: null as NanobotClient | null },
}));

vi.mock("@/providers/ClientProvider", () => ({
  useClient: () => ({ client: clientRef.current }),
}));

function renderCard(data: Partial<CredentialRequestUIData> = {}) {
  const full: CredentialRequestUIData = {
    request_id: "req-1",
    chat_id: "chat-1",
    service: "LinkedIn",
    reason: "Needed to sign in",
    fields: [
      { key: "LINKEDIN_EMAIL", label: "Email", sensitive: false, required: true },
      { key: "LINKEDIN_PASSWORD", label: "Password", sensitive: true, required: true },
    ],
    expires_at: Date.now() / 1000 + 300,
    ...data,
  };
  return render(<CredentialRequestCard data={full} />);
}

function sentEnvelopes(): Array<Record<string, unknown>> {
  const socket = FakeSocket.instances.at(-1);
  if (!socket) throw new Error("no socket created yet");
  return socket.sent.map((raw) => JSON.parse(raw));
}

beforeEach(() => {
  FakeSocket.instances = [];
  const client = new NanobotClient({
    url: "ws://test",
    reconnect: false,
    socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
  });
  client.connect();
  FakeSocket.instances.at(-1)?.fakeOpen();
  clientRef.current = client;
});

afterEach(() => {
  cleanup();
  clientRef.current?.close();
  clientRef.current = null;
});

describe("CredentialRequestCard", () => {
  it("submits values over the dedicated credential envelope, not as a chat message", async () => {
    const user = userEvent.setup();
    renderCard();

    const passwordInput = screen.getByLabelText(/Password/);
    expect(passwordInput).toHaveAttribute("type", "password");
    await user.type(screen.getByLabelText(/Email/), "me@example.com");
    await user.type(passwordInput, "s3cr3t");
    await user.click(screen.getByRole("button", { name: "Submit" }));

    const envelopes = sentEnvelopes();
    const submit = envelopes.find((env) => env.type === "credential_submit");
    expect(submit).toEqual({
      type: "credential_submit",
      chat_id: "chat-1",
      request_id: "req-1",
      values: {
        LINKEDIN_EMAIL: "me@example.com",
        LINKEDIN_PASSWORD: "s3cr3t",
      },
    });
    // Nothing resembling a normal chat message was sent for the values.
    expect(envelopes.every((env) => env.type !== "message")).toBe(true);
  });

  it("sends credential_cancel and settles the form", async () => {
    const user = userEvent.setup();
    renderCard();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(sentEnvelopes()).toContainEqual({
      type: "credential_cancel",
      chat_id: "chat-1",
      request_id: "req-1",
    });
  });

  it("keeps Submit disabled until required fields are filled", async () => {
    const user = userEvent.setup();
    renderCard();

    const submit = screen.getByRole("button", { name: "Submit" });
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText(/Email/), "me@example.com");
    await user.type(screen.getByLabelText(/Password/), "s3cr3t");
    expect(submit).toBeEnabled();
  });

  it("renders a terminal status instead of the form once resolved", () => {
    renderCard({ status: "submitted" });
    expect(screen.queryByLabelText(/Password/)).not.toBeInTheDocument();
    expect(screen.getByText(/submitted securely/i)).toBeInTheDocument();
  });

  it("renders the expired state when the request deadline has passed", () => {
    renderCard({ expires_at: Date.now() / 1000 - 10 });
    expect(screen.queryByLabelText(/Password/)).not.toBeInTheDocument();
    expect(screen.getByText(/expired/i)).toBeInTheDocument();
  });
});
