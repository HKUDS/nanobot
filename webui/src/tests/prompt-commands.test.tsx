import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PromptCommandsSettings } from "@/components/settings/PromptCommandsSettings";
import { ClientProvider } from "@/providers/ClientProvider";
import { NanobotClient } from "@/lib/nanobot-client";
import { listSlashCommands, type PromptCommand } from "@/lib/api";

const entry: PromptCommand = { name: "review", source: "user", description: "Review changes",
  argument_hint: "[files]", body: "Review $ARGUMENTS", enabled: true, revision: "abc" };
let client: NanobotClient;
beforeEach(() => {
  client = new NanobotClient({ url: "ws://fixture", reconnect: false });
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ commands: [entry], invalid: 0 })));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const mount = () => render(<ClientProvider client={client} token="test"><PromptCommandsSettings /></ClientProvider>);

it("loads, edits and saves through the authenticated mutation transport", async () => {
  const mutate = vi.spyOn(client, "requestMutation").mockResolvedValue({ commands: [{ ...entry, body: "Explain" }], invalid: 0 });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: /\/review/ }));
  expect(screen.getByLabelText("Name")).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Prompt"), { target: { value: "Explain" } });
  fireEvent.click(screen.getByRole("button", { name: "Save", exact: true }));
  await waitFor(() => expect(mutate).toHaveBeenCalledWith("prompt.save", expect.objectContaining({ body: "Explain", revision: "abc" }), expect.any(Number)));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});

it("keeps a conflicting draft and confirms before discarding it", async () => {
  vi.spyOn(client, "requestMutation").mockRejectedValue(new Error("command changed; reload"));
  mount();
  fireEvent.click(await screen.findByRole("button", { name: /\/review/ }));
  fireEvent.change(screen.getByLabelText("Prompt"), { target: { value: "Unsaved" } });
  fireEvent.click(screen.getByRole("button", { name: "Save", exact: true }));
  expect(await screen.findByRole("alert")).toHaveTextContent("changed");
  expect(screen.getByLabelText("Prompt")).toHaveValue("Unsaved");
  fireEvent.click(screen.getByRole("button", { name: "Cancel", exact: true }));
  expect(screen.getByRole("alertdialog")).toHaveTextContent("Discard changes?");
  fireEvent.click(screen.getByRole("button", { name: "Confirm", exact: true }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});

it("requires confirmation for delete and preserves scope/revision", async () => {
  const mutate = vi.spyOn(client, "requestMutation").mockResolvedValue({ commands: [], invalid: 0 });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: /\/review/ }));
  fireEvent.click(screen.getByRole("button", { name: "Delete", exact: true }));
  expect(mutate).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Confirm", exact: true }));
  await waitFor(() => expect(mutate).toHaveBeenCalledWith("prompt.delete", entry, expect.any(Number)));
});

it("retains source and normal-turn lifecycle in the slash palette", async () => {
  vi.mocked(fetch).mockResolvedValue(Response.json({ commands: [{ command: "/review", title: "review", description: "Review", icon: "file-text", source: "workspace", lifecycle: "agent_turn", accepts_args: true }] }));
  expect(await listSlashCommands("test", "", "websocket:chat")).toEqual([expect.objectContaining({ source: "workspace", lifecycle: "agent_turn", acceptsArgs: true })]);
  expect(fetch).toHaveBeenCalledWith("/api/commands?session_key=websocket%3Achat", expect.anything());
});
