import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HostNavigationContext, HostSwitcher, RemoteHostMenu, type HostPicker } from "@/components/remote/HostSwitcher";
import { readRecentRemotes, rememberRecentRemote } from "@/lib/remote-instances";

vi.mock("@/providers/ClientProvider", () => ({ useClient: () => ({ client: {
  status: "open", onStatus: () => () => {},
} }) }));

function picker(count: number): HostPicker {
  return {
    kind: "shell", name: "Local", hostname: "My-Mac", localName: "My-Mac",
    currentId: null, recentIds: [], pending: null, error: "", offline: false,
    profiles: Array.from({ length: count }, (_, index) => ({
      id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
      name: index === 1 ? "研发服务器" : `Server ${index + 1}`,
      host: `ubuntu@host-${index + 1}.test`, state: "closed",
    })),
    select: vi.fn(), manage: vi.fn(), cancel: vi.fn(), clearError: vi.fn(), restoreFocus: vi.fn(),
  };
}

async function openMenu(value: HostPicker) {
  const view = render(<HostNavigationContext.Provider value={value}><HostSwitcher /></HostNavigationContext.Provider>);
  await userEvent.click(screen.getByRole("button", { name: "Switch host" }));
  await screen.findByRole("menu");
  return view;
}

beforeEach(() => window.localStorage.clear());
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("host switcher", () => {
  it("announces the host only once when its display name is the hostname", async () => {
    const value = { ...picker(1), name: "team-host", hostname: "team-host" };
    render(<HostNavigationContext.Provider value={value}><HostSwitcher /></HostNavigationContext.Provider>);
    expect(screen.getByRole("status").textContent).toBe("team-host · Connected");
    const trigger = screen.getByRole("button", { name: "Switch host" });
    expect(trigger).not.toHaveAttribute("title");
    await userEvent.hover(trigger);
    expect(await screen.findByRole("tooltip")).toHaveTextContent("team-host · Connected");
  });

  it("does not borrow the local socket's Connected status while restoring a remote", () => {
    const value = picker(1);
    value.currentId = value.profiles[0].id;
    value.name = value.profiles[0].name;
    value.profiles[0].state = "connecting";
    value.pending = value.profiles[0];
    render(<HostNavigationContext.Provider value={value}><HostSwitcher /></HostNavigationContext.Provider>);
    expect(screen.getByRole("status")).not.toHaveTextContent("Connected");
    expect(screen.getByRole("status")).toHaveTextContent("Connecting");
  });

  it("keeps the current host identity visible until a pending switch is ready", async () => {
    const value = picker(2);
    value.pending = value.profiles[0];
    render(<HostNavigationContext.Provider value={value}><HostSwitcher /></HostNavigationContext.Provider>);
    const trigger = screen.getByRole("button", { name: "Switch host" });
    expect(within(trigger).getByText("Local", { exact: true })).toBeVisible();
    await userEvent.hover(trigger);
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Connecting to Server 1");
    expect(within(trigger).getByRole("status")).toHaveTextContent("Local · My-Mac · Connected · Connecting to Server 1");
    await userEvent.click(trigger);
    expect(screen.getByRole("menuitem", { name: "Local nanobot My-Mac" })).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("menuitem", { name: "Server 1 ubuntu@host-1.test" })).not.toHaveAttribute("aria-current");
  });

  it("does not label a healthy host offline when switching to another host fails", async () => {
    const value = { ...picker(2), error: "Destination SSH is unreachable" };
    render(<HostNavigationContext.Provider value={value}><HostSwitcher /></HostNavigationContext.Provider>);
    const trigger = screen.getByRole("button", { name: "Switch host" });
    expect(within(trigger).getByRole("status")).toHaveTextContent("Local · My-Mac · Connected");
    await userEvent.hover(trigger);
    expect(await screen.findByRole("tooltip")).toHaveTextContent(value.error);
    expect(trigger).not.toHaveTextContent("Offline");
    await userEvent.click(trigger);
    expect(screen.getByRole("alert")).toHaveTextContent(value.error);
  });

  it("keeps a truly disconnected host offline independently of switch errors", () => {
    const value = { ...picker(2), offline: true, name: "Team server", hostname: "team-host" };
    render(<HostNavigationContext.Provider value={value}><HostSwitcher /></HostNavigationContext.Provider>);
    expect(screen.getByRole("status")).toHaveTextContent("Team server · team-host · Server connection lost");
  });

  it("keeps remote sidebar identity and connection status separate from pending or failed switches", async () => {
    const value = { kind: "embedded" as const, name: "Team server", hostname: "team-host", pendingName: "Another server", open: vi.fn() };
    const view = render(<HostNavigationContext.Provider value={value}><HostSwitcher /></HostNavigationContext.Provider>);
    const trigger = screen.getByRole("button", { name: "Switch host" });
    expect(within(trigger).getByText("Team server", { exact: true })).toBeVisible();
    expect(within(trigger).getByRole("status")).toHaveTextContent("Team server · team-host · Connected · Connecting to Another server");
    view.rerender(<HostNavigationContext.Provider value={{ ...value, pendingName: undefined, error: "Destination SSH is unreachable" }}><HostSwitcher /></HostNavigationContext.Provider>);
    expect(within(trigger).getByRole("status")).toHaveTextContent("Team server · team-host · Connected");
    await userEvent.hover(trigger);
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Destination SSH is unreachable");
  });
  it.each([0, 1, 5])("keeps %i saved hosts simple without search", async (count) => {
    await openMenu(picker(count));
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getAllByRole("menuitem")).toHaveLength(count + 2);
  });

  it.each([6, 10, 20])("searches %i saved hosts, with management outside the scroll area", async (count) => {
    await openMenu(picker(count));
    const input = screen.getByRole("textbox", { name: "Search hosts…" });
    await waitFor(() => expect(input).toHaveFocus());
    const group = screen.getByRole("group", { name: "Switch host" });
    expect(within(group).getAllByRole("menuitem")).toHaveLength(count + 1);
    expect(group).toHaveClass("overflow-y-auto", "min-h-0");
    expect(group).not.toContainElement(screen.getByRole("menuitem", { name: "Manage connections…" }));
    await userEvent.type(input, "HOST-6.TEST");
    expect(within(group).getAllByRole("menuitem")).toHaveLength(1);
    expect(within(group).getByText("Server 6")).toBeVisible();
    expect(input).toHaveFocus();
  });

  it("finds names with spaces, non-Latin names and the local machine", async () => {
    await openMenu(picker(20));
    const input = screen.getByRole("textbox");
    await userEvent.type(input, "Server 20");
    expect(screen.getByRole("menuitem", { name: "Server 20 ubuntu@host-20.test" })).toBeVisible();
    fireEvent.change(input, { target: { value: "研发" } });
    expect(screen.getByRole("menuitem", { name: "研发服务器 ubuntu@host-2.test" })).toBeVisible();
    fireEvent.change(input, { target: { value: "My-Mac" } });
    expect(screen.getByRole("menuitem", { name: "Local nanobot My-Mac" })).toBeVisible();
    expect(screen.queryByText("Server 20")).not.toBeInTheDocument();
  });

  it("keeps search focused while the pointer crosses results", async () => {
    await openMenu(picker(10));
    const input = screen.getByRole("textbox");
    await waitFor(() => expect(input).toHaveFocus());
    const row = screen.getByRole("menuitem", { name: "Server 1 ubuntu@host-1.test" });
    fireEvent.pointerMove(row, { pointerType: "mouse", clientX: 25 });
    fireEvent.pointerOut(row, { pointerType: "mouse" });
    expect(input).toHaveFocus();
    await userEvent.type(input, "Server 10");
    expect(screen.getByRole("menuitem", { name: "Server 10 ubuntu@host-10.test" })).toBeVisible();
  });

  it("supports arrow navigation back to search, then Enter selection", async () => {
    const value = picker(10);
    await openMenu(value);
    const input = screen.getByRole("textbox");
    await userEvent.type(input, "host-10");
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Server 10 ubuntu@host-10.test" })).toHaveFocus();
    await userEvent.keyboard("{ArrowUp}");
    expect(input).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(value.select).toHaveBeenCalledWith(value.profiles[9].id);
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
  });

  it("does not connect or close when confirming IME input", async () => {
    const value = picker(10);
    await openMenu(value);
    const input = screen.getByRole("textbox");
    fireEvent.compositionStart(input);
    fireEvent.change(input, { target: { value: "研发" } });
    fireEvent.keyDown(input, { key: "Enter", isComposing: true });
    fireEvent.keyDown(input, { key: "Escape", isComposing: true });
    expect(value.select).not.toHaveBeenCalled();
    expect(screen.getByRole("menu")).toBeVisible();
    fireEvent.compositionEnd(input);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(value.select).toHaveBeenCalledWith(value.profiles[1].id);
  });

  it("does not select a host on empty search Enter", async () => {
    const value = picker(10);
    await openMenu(value);
    await waitFor(() => expect(screen.getByRole("textbox")).toHaveFocus());
    await userEvent.keyboard("{Enter}");
    expect(value.select).not.toHaveBeenCalled();
  });

  it("shows an empty result without hiding management or selecting it on Enter", async () => {
    const value = picker(10);
    await openMenu(value);
    await userEvent.type(screen.getByRole("textbox"), "missing");
    expect(screen.getByRole("status", { name: "" })).toHaveTextContent("No matching hosts");
    await userEvent.keyboard("{Enter}");
    expect(value.select).not.toHaveBeenCalled();
    expect(value.manage).not.toHaveBeenCalled();
    await userEvent.keyboard("{ArrowDown}{Enter}");
    expect(value.manage).toHaveBeenCalledOnce();
  });

  it("clears search on reopen and restores focus on Escape", async () => {
    const value = picker(10);
    await openMenu(value);
    await userEvent.type(screen.getByRole("textbox"), "Server 10");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(value.restoreFocus).toHaveBeenCalled());
    await userEvent.click(screen.getByRole("button", { name: "Switch host" }));
    expect(await screen.findByRole("textbox")).toHaveValue("");
    expect(screen.getAllByRole("menuitem")).toHaveLength(12);
  });

  it("pins local, then current and recent hosts, without live reordering or duplicates", async () => {
    const value = picker(20);
    value.currentId = value.profiles[19].id;
    value.recentIds = [value.profiles[8].id, value.currentId, "deleted-id"];
    const rendered = await openMenu(value);
    const names = () => within(screen.getByRole("group")).getAllByRole("menuitem").map((item) => item.getAttribute("aria-label") || item.textContent);
    expect(names().slice(0, 4)).toEqual(["Local nanobotMy-Mac", "Server 20 ubuntu@host-20.test", "Server 9 ubuntu@host-9.test", "Server 1 ubuntu@host-1.test"]);
    const before = names();
    rendered.rerender(<HostNavigationContext.Provider value={{ ...value, recentIds: [value.profiles[5].id] }}><HostSwitcher /></HostNavigationContext.Provider>);
    expect(names()).toEqual(before);
  });

  it("uses the same searchable menu for the parent-owned remote sidebar", async () => {
    const value = picker(20);
    render(<RemoteHostMenu picker={value} anchor={{ left: 48, top: 540, width: 160, height: 32 }} onClose={vi.fn()} />);
    const input = await screen.findByRole("textbox");
    await userEvent.type(input, "host-20");
    await userEvent.click(screen.getByRole("menuitem", { name: "Server 20 ubuntu@host-20.test" }));
    expect(value.select).toHaveBeenCalledWith(value.profiles[19].id);
  });

  it("keeps search available if the directory shrinks while filtering", async () => {
    const value = picker(10);
    const rendered = await openMenu(value);
    await userEvent.type(screen.getByRole("textbox"), "host-10");
    rendered.rerender(<HostNavigationContext.Provider value={{ ...value, profiles: value.profiles.slice(0, 5) }}><HostSwitcher /></HostNavigationContext.Provider>);
    const input = screen.getByRole("textbox");
    expect(input).toHaveValue("host-10");
    await userEvent.clear(input);
    expect(within(screen.getByRole("group")).getAllByRole("menuitem")).toHaveLength(6);
  });

  it("does not autofocus search and summon the keyboard on touch devices", async () => {
    const original = window.matchMedia.bind(window);
    vi.spyOn(window, "matchMedia").mockImplementation((query) => ({ ...original(query), matches: query === "(pointer: coarse)" }));
    await openMenu(picker(20));
    expect(screen.getByRole("menu")).toHaveFocus();
    expect(screen.getByRole("textbox")).not.toHaveFocus();
    await userEvent.click(screen.getByRole("menuitem", { name: "Server 20 ubuntu@host-20.test" }));
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
  });

  it("keeps cancel and errors accessible even when no hosts match", async () => {
    const value = picker(20);
    value.pending = value.profiles[3]; value.error = "Try again";
    await openMenu(value);
    await userEvent.type(screen.getByRole("textbox"), "missing");
    expect(screen.getByRole("alert")).toHaveTextContent("Try again");
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(value.clearError).toHaveBeenCalledOnce();
    await userEvent.click(screen.getByRole("menuitem", { name: "Cancel switch" }));
    expect(value.cancel).toHaveBeenCalledOnce();
  });
});

describe("recent host preferences", () => {
  it("keeps only bounded, unique profile IDs and ignores malformed storage", () => {
    window.localStorage.setItem("nanobot.recent-remote-instances", "not json");
    expect(readRecentRemotes()).toEqual([]);
    const ids = picker(25).profiles.map(({ id }) => id);
    window.localStorage.setItem("nanobot.recent-remote-instances", JSON.stringify([null, "http://secret", ids[0], ...ids]));
    expect(readRecentRemotes()).toEqual(ids.slice(0, 20));
    const next = rememberRecentRemote(ids[5], readRecentRemotes());
    expect(next).toHaveLength(20);
    expect(next[0]).toBe(ids[5]);
    expect(readRecentRemotes()).toEqual(next);
  });

  it("keeps switching available when browser storage is disabled", () => {
    vi.spyOn(window.localStorage, "getItem").mockImplementation(() => { throw new Error("disabled"); });
    vi.spyOn(window.localStorage, "setItem").mockImplementation(() => { throw new Error("disabled"); });
    expect(readRecentRemotes()).toEqual([]);
    expect(rememberRecentRemote(picker(1).profiles[0].id, [])).toEqual([picker(1).profiles[0].id]);
  });
});
