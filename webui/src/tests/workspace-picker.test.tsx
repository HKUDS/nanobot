import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { WorkspaceProjectPicker } from "@/components/thread/WorkspaceControls";
import type { WorkspaceDirectoriesPayload, WorkspacesPayload } from "@/lib/types";
import { workspaceBreadcrumbs, type BrowseWorkspaceDirectories } from "@/lib/workspace";

const scope = { project_path: "/srv/workspace", access_mode: "restricted" as const };
const catalog: WorkspacesPayload = {
  schema_version: 1,
  default_access_mode: "default",
  default_scope: scope,
  recent_projects: [{ name: "alpha", path: "/srv/alpha" }, { name: "beta", path: "/srv/beta" }],
  host: { name: "dev-server", platform: "Linux" },
  controls: { can_change_project: true, can_use_full_access: false, can_browse_directories: true },
};
const directory: WorkspaceDirectoriesPayload = {
  path: "/srv/workspace", parent: "/srv", entries: [{ name: "alpha", path: "/srv/workspace/alpha" }],
  truncated: false, host: "dev-server", platform: "Linux",
};

describe("Workspace project picker", () => {
  it.each([
    ["/srv/中文 项目/src", ["/", "/srv", "/srv/中文 项目", "/srv/中文 项目/src"]],
    ["C:\\Projects\\alpha", ["C:\\", "C:\\Projects", "C:\\Projects\\alpha"]],
    ["\\\\server\\share\\alpha", ["\\\\server\\share\\", "\\\\server\\share\\alpha"]],
  ])("keeps host breadcrumb roots intact: %s", (path, expected) => {
    expect(workspaceBreadcrumbs(path).map(crumb => crumb.path)).toEqual(expected);
  });

  it("separates navigation history from parent navigation and only applies on confirmation", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const browse = vi.fn((raw: string) => {
      const path = raw.replace(/\/$/, "") || "/";
      return Promise.resolve({ ...directory, path, parent: path === "/" ? null : path.slice(0, path.lastIndexOf("/")) || "/", entries: [] });
    });
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls} onLoadProjects={vi.fn().mockResolvedValue(catalog)} onBrowseDirectories={browse} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    await user.click(await screen.findByRole("button", { name: "/srv/beta" }));
    await screen.findByRole("listbox", { name: "/srv/beta" });
    await user.click(screen.getByRole("button", { name: "Back", exact: true }));
    await screen.findByRole("listbox", { name: scope.project_path });
    await user.click(screen.getByRole("button", { name: "Forward", exact: true }));
    await screen.findByRole("listbox", { name: "/srv/beta" });
    await user.click(within(screen.getByRole("navigation", { name: "Current location" })).getByRole("button", { name: "srv", exact: true }));
    await screen.findByRole("listbox", { name: "/srv" });
    await user.click(within(screen.getByRole("navigation", { name: "Current location" })).getByRole("button", { name: "/", exact: true }));
    await screen.findByRole("listbox", { name: "/", exact: true });
    expect(screen.queryByRole("button", { name: "Parent folder" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Forward", exact: true })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Cancel", exact: true }));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("returns directly to the last visited folder after backward and branching navigation", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const browse = vi.fn((raw: string) => Promise.resolve({ ...directory, path: raw.replace(/\/$/, ""), entries: [] }));
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls} onLoadProjects={vi.fn().mockResolvedValue(catalog)} onBrowseDirectories={browse} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    const lastVisited = screen.getByRole("button", { name: "Last visited folder" });
    expect(lastVisited).toBeDisabled();
    await user.click(await screen.findByRole("button", { name: "/srv/alpha" }));
    await screen.findByRole("listbox", { name: "/srv/alpha" });
    await user.click(screen.getByRole("button", { name: "Back", exact: true }));
    await screen.findByRole("listbox", { name: scope.project_path });
    await user.click(lastVisited);
    await screen.findByRole("listbox", { name: "/srv/alpha" });
    await user.click(screen.getByRole("button", { name: "/srv/beta" }));
    await screen.findByRole("listbox", { name: "/srv/beta" });
    await user.click(lastVisited);
    await screen.findByRole("listbox", { name: "/srv/alpha" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Cancel", exact: true }));
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    expect(screen.getByRole("button", { name: "Last visited folder" })).toBeDisabled();
  });

  it("restores the directory columns and their selection when returning to a sibling visit", async () => {
    const user = userEvent.setup();
    let rootChanged = false;
    const browse = vi.fn((raw: string) => {
      const path = raw.replace(/\/$/, "");
      const names = path === scope.project_path ? ["memory", "prompts"] : path.endsWith("/memory") ? ["reference"] : [];
      if (rootChanged && path === scope.project_path) names.push("new-folder");
      return Promise.resolve({ ...directory, path, entries: names.map(name => ({ name, path: `${path}/${name}` })) });
    });
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls} onBrowseDirectories={browse} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    await user.click(await screen.findByRole("option", { name: "/srv/workspace/memory" }));
    await screen.findByRole("option", { name: "/srv/workspace/memory/reference" });
    const parent = screen.getByRole("listbox", { name: scope.project_path });
    parent.scrollTop = 44;
    fireEvent.scroll(parent);
    await user.click(screen.getByRole("option", { name: "/srv/workspace/prompts" }));
    await screen.findByText("No subfolders");
    await user.click(screen.getByRole("button", { name: "Last visited folder" }));
    await screen.findByRole("option", { name: "/srv/workspace/memory/reference" });
    expect(screen.getAllByRole("listbox")).toHaveLength(2);
    expect(screen.getByRole("option", { name: "/srv/workspace/memory" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("listbox", { name: scope.project_path }).scrollTop).toBe(44);
    await user.click(screen.getByRole("button", { name: "Back", exact: true }));
    await screen.findByRole("listbox", { name: "/srv/workspace/prompts" });
    expect(screen.getAllByRole("listbox")).toHaveLength(2);
    expect(screen.getByRole("option", { name: "/srv/workspace/prompts" })).toHaveAttribute("aria-selected", "true");
    await user.click(screen.getByRole("button", { name: "Forward", exact: true }));
    await screen.findByRole("option", { name: "/srv/workspace/memory/reference" });
    expect(screen.getAllByRole("listbox")).toHaveLength(2);
    await user.click(within(screen.getByRole("navigation", { name: "Current location" })).getByRole("button", { name: "workspace", exact: true }));
    await screen.findByRole("listbox", { name: scope.project_path });
    rootChanged = true;
    const systemNow = Date.now;
    const clock = vi.spyOn(Date, "now").mockImplementation(() => systemNow() + 31_000);
    try {
      await user.click(screen.getByRole("button", { name: "Back", exact: true }));
      await screen.findByRole("option", { name: "/srv/workspace/new-folder" });
      expect(screen.getByRole("option", { name: "/srv/workspace/memory" })).toHaveAttribute("aria-selected", "true");
      expect(screen.getAllByRole("listbox")).toHaveLength(2);
    } finally {
      clock.mockRestore();
    }
  });

  it("does not let address editing or text arrows silently change the working folder", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const browse = vi.fn((path: string) => Promise.resolve({ ...directory, path: path.replace(/\/$/, ""), entries: [] }));
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls} onBrowseDirectories={browse} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    await screen.findByText("No subfolders");
    await user.click(screen.getByRole("button", { name: `Edit path: ${scope.project_path}` }));
    const input = screen.getByRole("combobox") as HTMLInputElement;
    await waitFor(() => expect(input).toHaveFocus());
    expect(input).toHaveValue(`${scope.project_path}/`);
    expect(input.selectionStart).toBe(0);
    expect(input.selectionEnd).toBe(`${scope.project_path}/`.length);
    await user.clear(input);
    await user.type(input, "/srv/alpha");
    expect(fireEvent.keyDown(input, { key: "ArrowRight" })).toBe(true);
    expect(fireEvent.keyDown(input, { key: "ArrowLeft" })).toBe(true);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    await screen.findByRole("listbox", { name: scope.project_path });
    act(() => screen.getByRole("button", { name: `Edit path: ${scope.project_path}` }).focus());
    await user.keyboard("{Enter}");
    await waitFor(() => expect(screen.getByRole("combobox")).toHaveFocus());
    await user.keyboard("{Escape}");
    await user.keyboard("{Meta>}{Shift>}g{/Shift}{/Meta}");
    await user.clear(screen.getByRole("combobox"));
    await user.type(screen.getByRole("combobox"), "/srv/alpha{Enter}");
    await screen.findByRole("listbox", { name: "/srv/alpha" });
    expect(onChange).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ project_path: "/srv/alpha" }));
  });

  it("distinguishes a folder without subfolders, a failed listing, and a filter with no matches", async () => {
    const user = userEvent.setup();
    const browse = vi.fn().mockRejectedValueOnce(new Error("Permission denied"))
      .mockResolvedValue({ ...directory, entries: [] });
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls} onBrowseDirectories={browse} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Permission denied");
    expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByText("No subfolders");
    expect(screen.getByRole("button", { name: "Confirm" })).toBeEnabled();
    await user.type(screen.getByRole("textbox", { name: "Filter this folder" }), "missing");
    await screen.findByText("No matching folders.");
    expect(screen.getByRole("button", { name: "Confirm" })).toBeEnabled();
  });

  it("keeps the chosen folder selectable while its contents are loading", async () => {
    const user = userEvent.setup();
    const project = { name: "alpha", path: "/srv/workspace/alpha" };
    let finish!: (result: WorkspaceDirectoriesPayload) => void;
    const browse = vi.fn((path: string) => path === scope.project_path
      ? Promise.resolve(directory)
      : new Promise<WorkspaceDirectoriesPayload>(resolve => { finish = resolve; }));
    const resolve = vi.fn().mockResolvedValue(project);
    const onChange = vi.fn();
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={{ ...catalog.controls, can_resolve_project: true }} onBrowseDirectories={browse} onResolveProject={resolve} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    await user.click(await screen.findByRole("option", { name: project.path }));
    await waitFor(() => expect(screen.getByRole("listbox", { name: project.path })).toHaveAttribute("aria-busy", "true"));
    expect(screen.getByRole("button", { name: "Confirm" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(resolve).toHaveBeenCalledWith(project.path);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ project_path: project.path }));
    await act(async () => { finish({ ...directory, path: project.path, entries: [] }); });
  });

  it("confirms the edited address when clicking Confirm", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const browse = vi.fn((path: string) => Promise.resolve({ ...directory, path: path.replace(/\/$/, ""), entries: [] }));
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls} onBrowseDirectories={browse} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    await screen.findByText("No subfolders");
    await user.click(screen.getByRole("button", { name: /^Edit path:/ }));
    await user.clear(screen.getByRole("combobox"));
    await user.type(screen.getByRole("combobox"), "/srv/beta/");
    await screen.findByRole("listbox", { name: "/srv/beta" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Confirm" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ project_path: "/srv/beta" }));
  });

  it("uses one directory at a time on narrow screens and keeps saved locations reachable", async () => {
    const media = vi.spyOn(window, "matchMedia").mockImplementation(query => ({
      matches: query === "(max-width: 639px)", media: query, onchange: null,
      addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
    }));
    try {
      const user = userEvent.setup();
      const browse = vi.fn((raw: string) => Promise.resolve(raw.replace(/\/$/, "") === scope.project_path ? directory : { ...directory, path: raw.replace(/\/$/, ""), entries: [] }));
      render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls} onLoadProjects={vi.fn().mockResolvedValue(catalog)} onBrowseDirectories={browse} onChange={vi.fn()} />);
      await user.click(screen.getByRole("button", { name: "Switch working directory" }));
      await user.click(await screen.findByRole("option", { name: "/srv/workspace/alpha" }));
      expect(screen.getAllByRole("listbox")).toHaveLength(1);
      await screen.findByText("No subfolders");
      await user.click(screen.getByRole("button", { name: "Saved locations" }));
      await user.click(await screen.findByRole("button", { name: "/srv/beta" }));
      await screen.findByRole("listbox", { name: "/srv/beta" });
      expect(screen.getAllByRole("listbox")).toHaveLength(1);
      expect(screen.getByRole("button", { name: "Saved locations" })).toHaveAttribute("aria-expanded", "false");
      expect(screen.getByRole("button", { name: "Confirm" })).toBeEnabled();
    } finally { media.mockRestore(); }
  });
  it.each([
    ["/srv/alpha/", "/srv/beta/"],
    ["C:\\Projects\\alpha\\", "C:\\Projects\\beta\\"],
  ])("distinguishes saved folders with the same name by their parent paths: %s", async (firstParent, secondParent) => {
    const user = userEvent.setup();
    const firstPath = `${firstParent}src`;
    const secondPath = `${secondParent}src`;
    const onChange = vi.fn();
    const onBrowse = vi.fn((path: string) => Promise.resolve({ ...directory, path: path.replace(/[\\/]$/, ""), entries: [] }));
    const onLoadProjects = vi.fn().mockResolvedValue({ ...catalog, recent_projects: [
      { name: "src", path: firstPath }, { name: "src", path: secondPath },
    ] });
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls} onLoadProjects={onLoadProjects} onBrowseDirectories={onBrowse} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    const first = await screen.findByRole("button", { name: firstPath });
    const second = screen.getByRole("button", { name: secondPath });
    expect(within(first).getByText("src", { exact: true })).toBeInTheDocument();
    expect(within(first).getByText(firstParent, { exact: true })).toBeInTheDocument();
    expect(within(second).getByText("src", { exact: true })).toBeInTheDocument();
    expect(within(second).getByText(secondParent, { exact: true })).toBeInTheDocument();
    act(() => first.focus());
    expect(first).toHaveFocus();
    await user.click(second);
    await waitFor(() => expect(screen.getByRole("button", { name: "Confirm" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ project_path: secondPath }));
  });

  it("keeps saved locations separate from directory filtering", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const onBrowse = vi.fn().mockResolvedValue(directory);
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls} onLoadProjects={vi.fn().mockResolvedValue(catalog)} onBrowseDirectories={onBrowse} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    const shortcut = await screen.findByRole("button", { name: "/srv/beta" });
    await user.type(screen.getByRole("textbox", { name: "Filter this folder" }), "al");
    await waitFor(() => expect(onBrowse).toHaveBeenLastCalledWith("/srv/workspace", "al", false, true));
    expect(shortcut).toBeInTheDocument();
    expect(screen.getAllByRole("listbox")).toHaveLength(1);
    onBrowse.mockResolvedValue({ ...directory, path: "/srv/beta", entries: [] });
    await user.click(shortcut);
    await waitFor(() => expect(screen.getByRole("button", { name: "Confirm" })).toBeEnabled());
    expect(screen.getAllByRole("listbox")).toHaveLength(1);
    expect(screen.getByRole("textbox", { name: "Filter this folder" })).toHaveValue("");
    expect(onChange).not.toHaveBeenCalled();
    await user.type(screen.getByRole("textbox", { name: "Filter this folder" }), "oth");
    await waitFor(() => expect(onBrowse).toHaveBeenLastCalledWith("/srv/beta", "oth", false, true));
    expect(shortcut).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Confirm" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ project_path: "/srv/beta", access_mode: "restricted" }));
  });

  it("shows cached directories without loading again when revisiting or reopening", async () => {
    const user = userEvent.setup();
    const onBrowse = vi.fn((path: string) => Promise.resolve(path.replace(/\/$/, "") === scope.project_path
      ? directory : { ...directory, path: "/srv/workspace/alpha", entries: [] }));
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls} onBrowseDirectories={onBrowse} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    await user.click(await screen.findByRole("option", { name: "/srv/workspace/alpha" }));
    await screen.findByText("No subfolders");
    expect(onBrowse).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole("button", { name: "/srv/workspace" }));
    expect(screen.getByRole("option", { name: "/srv/workspace/alpha" })).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(onBrowse).toHaveBeenCalledTimes(2);
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    expect(screen.getByRole("option", { name: "/srv/workspace/alpha" })).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(onBrowse).toHaveBeenCalledTimes(2);
  });

  it("scrolls deep directory columns horizontally with Shift and preserves ordinary wheel events", async () => {
    const user = userEvent.setup();
    const onBrowse = vi.fn((path: string) => Promise.resolve(path.replace(/\/$/, "") === scope.project_path
      ? directory : { ...directory, path: "/srv/workspace/alpha", entries: [] }));
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls} onBrowseDirectories={onBrowse} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    await user.click(await screen.findByRole("option", { name: "/srv/workspace/alpha" }));
    await screen.findByText("No subfolders");
    const viewport = screen.getAllByRole("listbox")[0].closest("[data-workspace-columns]") as HTMLElement;
    Object.defineProperties(viewport, { clientWidth: { value: 300 }, scrollWidth: { value: 600 } });
    viewport.scrollLeft = 0;
    const wheel = (options: WheelEventInit) => fireEvent(viewport, Object.assign(
      new Event("wheel", { bubbles: true, cancelable: true }),
      { deltaX: 0, deltaY: 0, deltaMode: 0, shiftKey: false, ctrlKey: false, metaKey: false, ...options },
    ));
    expect(wheel({ deltaY: 120, shiftKey: true })).toBe(false);
    expect(viewport.scrollLeft).toBe(120);
    expect(wheel({ deltaY: -2, deltaMode: 1, shiftKey: true })).toBe(false);
    expect(viewport.scrollLeft).toBe(88);
    wheel({ deltaY: 120 });
    expect(viewport.scrollLeft).toBe(88);
    wheel({ deltaY: 120, shiftKey: true, ctrlKey: true });
    expect(viewport.scrollLeft).toBe(88);
  });

  it("keeps a wide directory bounded while scrolling and completing an offscreen keyboard result", async () => {
    const user = userEvent.setup();
    const entries = Array.from({ length: 500 }, (_, index) => ({ name: `folder-${index}`, path: `/srv/workspace/folder-${index}` }));
    const onBrowse = vi.fn((rawPath: string) => {
      const path = rawPath.replace(/\/$/, "");
      return Promise.resolve({ ...directory, path, entries: path === scope.project_path ? entries : [{ name: "child", path: `${path}/child` }] });
    });
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls} onBrowseDirectories={onBrowse} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    const first = await screen.findByRole("option", { name: entries[0].path });
    expect(first).toHaveAttribute("aria-setsize", "500");
    expect(first).toHaveAttribute("aria-posinset", "1");
    const viewport = screen.getByRole("listbox");
    Object.defineProperty(viewport, "clientHeight", { configurable: true, value: 220 });
    expect(within(viewport).getAllByRole("option").length).toBeLessThan(20);
    viewport.scrollTop = 250 * 44;
    fireEvent.scroll(viewport);
    expect(await screen.findByRole("option", { name: entries[250].path })).toHaveAttribute("aria-posinset", "251");
    act(() => viewport.focus());
    await user.keyboard("{End}");
    const last = await screen.findByRole("option", { name: entries[499].path });
    expect(viewport).toHaveAttribute("aria-activedescendant", last.id);
    expect(within(viewport).getAllByRole("option").length).toBeLessThan(20);
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("option", { name: `${entries[499].path}/child` })).toBeInTheDocument();
  });

  it("browses folders immediately, toggles hidden entries, and selects the resolved directory", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const onBrowse = vi.fn().mockResolvedValue(directory);
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls} onBrowseDirectories={onBrowse} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    await screen.findByRole("option", { name: "/srv/workspace/alpha" });
    expect(onBrowse).toHaveBeenLastCalledWith("/srv/workspace", "", false, true);
    await user.click(screen.getByRole("switch", { name: "Show hidden folders" }));
    await waitFor(() => expect(onBrowse).toHaveBeenLastCalledWith("/srv/workspace", "", true, true));
    onBrowse.mockResolvedValue({ ...directory, path: "/srv/workspace/alpha", entries: [] });
    await user.click(screen.getByRole("option", { name: "/srv/workspace/alpha" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Confirm" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ project_path: "/srv/workspace/alpha" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Switch working directory" })).not.toHaveFocus());
  });

  it("keeps invalid paths editable and validates the project before closing", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const onResolve = vi.fn().mockRejectedValueOnce(new Error("project_path must be an existing directory"))
      .mockResolvedValueOnce({ name: "alpha", path: "/srv/alpha" });
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={{ ...catalog.controls, can_resolve_project: true }} onResolveProject={onResolve} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    await user.clear(screen.getByRole("combobox"));
    await user.type(screen.getByRole("combobox"), "/srv/missing");
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("existing directory");
    expect(screen.getByRole("combobox")).toHaveValue("/srv/missing");
    await waitFor(() => expect(screen.getByRole("combobox")).toHaveFocus());
    expect(onChange).not.toHaveBeenCalled();
    await user.clear(screen.getByRole("combobox"));
    await user.type(screen.getByRole("combobox"), "/srv/alpha");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ project_path: "/srv/alpha" })));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("uses manual paths without new requests on a host missing optional capabilities", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const onBrowse = vi.fn();
    const onResolve = vi.fn();
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={{ can_change_project: true, can_use_full_access: false }} onBrowseDirectories={onBrowse} onResolveProject={onResolve} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    expect(screen.queryByRole("option", { name: "Browse folders…" })).not.toBeInTheDocument();
    await user.type(screen.getByRole("combobox"), "relative-path");
    expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled();
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter an absolute folder path");
    expect(onChange).not.toHaveBeenCalled();
    await user.clear(screen.getByRole("combobox"));
    await user.type(screen.getByRole("combobox"), "/srv/alpha");
    await user.keyboard("{Enter}");
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ project_path: "/srv/alpha" }));
    expect(onBrowse).not.toHaveBeenCalled();
    expect(onResolve).not.toHaveBeenCalled();
  });

  it("does not apply a directory response after closing the dialog", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    let finish!: (value: WorkspaceDirectoriesPayload) => void;
    const onBrowse = vi.fn(() => new Promise<WorkspaceDirectoriesPayload>((resolve) => { finish = resolve; }));
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls} onBrowseDirectories={onBrowse} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    await waitFor(() => expect(onBrowse).toHaveBeenCalled());
    await user.keyboard("{Escape}");
    finish(directory);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });
  it("pins folders without selecting and keeps favorites ahead of recent projects", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const favorites = [{ name: "beta", path: "/srv/beta" }];
    const onFavorite = vi.fn().mockResolvedValueOnce(favorites).mockRejectedValueOnce(new Error("disk full")).mockResolvedValueOnce([]);
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls} onLoadProjects={vi.fn().mockResolvedValue({ ...catalog, controls: { ...catalog.controls, can_manage_favorites: true } })} onFavoriteProject={onFavorite} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    await user.click(await screen.findByRole("button", { name: "Pin beta" }));
    expect(onFavorite).toHaveBeenLastCalledWith("/srv/beta", true);
    await screen.findByRole("button", { name: "Unpin beta" });
    const favoriteSection = screen.getByRole("heading", { name: "Favorites" }).closest("section")!;
    expect(within(favoriteSection).getByRole("button", { name: "/srv/beta" })).toBeInTheDocument();
    const recentSection = screen.getByRole("heading", { name: "Recent projects" }).closest("section")!;
    expect(within(recentSection).queryByRole("button", { name: "/srv/beta" })).not.toBeInTheDocument();
    expect(screen.getByRole("combobox")).toHaveFocus();
    expect(onChange).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Unpin beta" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("disk full");
    await user.click(screen.getByRole("button", { name: "Unpin beta" }));
    expect(await screen.findByRole("button", { name: "Pin beta" })).toHaveAttribute("aria-pressed", "false");
    expect(onFavorite).toHaveBeenLastCalledWith("/srv/beta", false);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("stars a directory with the keyboard without navigating or selecting it", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const onFavorite = vi.fn().mockResolvedValue([{ name: "alpha", path: "/srv/workspace/alpha" }]);
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls}
      onLoadProjects={vi.fn().mockResolvedValue({ ...catalog, controls: { ...catalog.controls, can_manage_favorites: true } })}
      onBrowseDirectories={vi.fn().mockResolvedValue(directory)} onFavoriteProject={onFavorite} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    const option = await screen.findByRole("option", { name: "/srv/workspace/alpha" });
    const star = await within(option.parentElement!).findByRole("button", { name: "Pin alpha" });
    act(() => star.focus());
    await user.keyboard("{Enter}");
    expect(onFavorite).toHaveBeenCalledWith("/srv/workspace/alpha", true);
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Unpin alpha" })).toHaveLength(2));
    expect(option).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("listbox")).toHaveAccessibleName("/srv/workspace");
    expect(onChange).not.toHaveBeenCalled();
  });

  it.each([
    ["/srv/al", "/srv/alpha", "/srv/alpha/"],
    ["C:\\Projects\\al", "C:\\Projects\\alpha", "C:\\Projects\\alpha\\"],
    ["\\\\server\\share\\al", "\\\\server\\share\\alpha", "\\\\server\\share\\alpha\\"],
  ])("completes paths in the same input: %s", async (draft, completed, expected) => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const onBrowse = vi.fn((path: string) => Promise.resolve({ ...directory, path: completed, partial: path === draft, entries: path === draft ? [{ name: "alpha", path: completed }] : [] }));
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls} onBrowseDirectories={onBrowse} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    await user.click(screen.getByRole("button", { name: /^Edit path:/ }));
    const input = screen.getByRole("combobox");
    await user.clear(input);
    await user.type(input, draft);
    await screen.findByRole("option", { name: completed });
    await user.keyboard("{Tab}");
    expect(input).toHaveValue(expected);
    expect(input).toHaveFocus();
    expect(screen.getByRole("combobox")).toBe(input);
    expect(onChange).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByRole("button", { name: "Confirm" })).toBeEnabled());
    expect(fireEvent.keyDown(input, { key: "Tab", shiftKey: true })).toBe(true);
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ project_path: completed }));
  });

  it("uses one list for partial paths and keyboard completion", async () => {
    const user = userEvent.setup();
    const onBrowse = vi.fn((path: string) => Promise.resolve({ ...directory, path: path === "/srv/al" ? "/srv" : path, parent: "/srv", partial: path === "/srv/al", entries: path === "/srv/al" ? [{ name: "alpha", path: "/srv/alpha" }, { name: "alpine", path: "/srv/alpine" }] : [] }));
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls} onBrowseDirectories={onBrowse} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    await user.click(screen.getByRole("button", { name: /^Edit path:/ }));
    const input = screen.getByRole("combobox");
    await user.clear(input);
    await user.type(input, "/srv/al");
    await screen.findByRole("option", { name: "/srv/alpine" });
    expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await user.keyboard("{ArrowDown}{ArrowDown}{Tab}");
    expect(input).toHaveValue("/srv/alpine/");
    expect(screen.getAllByRole("combobox")).toHaveLength(1);
    expect(screen.getAllByRole("listbox")).toHaveLength(1);
    await waitFor(() => expect(screen.getByRole("button", { name: "Confirm" })).toBeEnabled());
    expect(input).toHaveFocus();
  });

  it.each([false, true])("completes an exact directory without entering a child when loaded=%s", async (loaded) => {
    const user = userEvent.setup();
    const onBrowse = vi.fn((rawPath: string) => {
      const path = rawPath.replace(/\/$/, "");
      return Promise.resolve({ ...directory, path, partial: false, entries: [{ name: "docs", path: `${path}/docs` }] });
    });
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls} onBrowseDirectories={onBrowse} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    await screen.findByRole("option", { name: "/srv/workspace/docs" });
    await user.click(screen.getByRole("button", { name: /^Edit path:/ }));
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "/srv/alpha" } });
    if (loaded) await screen.findByRole("option", { name: "/srv/alpha/docs" });
    fireEvent.keyDown(input, { key: "Tab" });
    await waitFor(() => expect(input).toHaveValue("/srv/alpha/"));
    expect(screen.getAllByRole("listbox")).toHaveLength(1);
    await screen.findByRole("option", { name: "/srv/alpha/docs" });
    // Once the address is complete, Tab leaves the input instead of entering docs.
    await user.tab();
    expect(input).not.toHaveFocus();
    expect(input).toHaveValue("/srv/alpha/");
    await user.click(input);
    await user.keyboard("{ArrowUp}{Tab}");
    expect(input).toHaveValue("/srv/alpha/docs/");
  });

  it("ignores a Tab completion after the user changes the path", async () => {
    const user = userEvent.setup();
    let finish!: (value: WorkspaceDirectoriesPayload) => void;
    const onBrowse = vi.fn((path: string) => path === "/srv/al" ? new Promise<WorkspaceDirectoriesPayload>(resolve => { finish = resolve; }) : Promise.resolve({ ...directory, entries: [] }));
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls} onBrowseDirectories={onBrowse} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    await user.click(screen.getByRole("button", { name: /^Edit path:/ }));
    const input = screen.getByRole("combobox");
    await user.clear(input);
    await user.type(input, "/srv/al");
    await user.keyboard("{Tab}");
    await user.type(input, "ternative");
    finish({ ...directory, entries: [{ name: "alpha", path: "/srv/alpha" }] });
    await waitFor(() => expect(input).toHaveValue("/srv/alternative"));
    expect(input).toHaveFocus();
  });

  it("reuses an in-flight partial-path listing when Tab completes it", async () => {
    const user = userEvent.setup();
    let finish!: (value: WorkspaceDirectoriesPayload) => void;
    const onBrowse = vi.fn<BrowseWorkspaceDirectories>((path: string) => path === "/srv/al"
      ? new Promise<WorkspaceDirectoriesPayload>(resolve => { finish = resolve; })
      : Promise.resolve({ ...directory, path, entries: [] }));
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls} onBrowseDirectories={onBrowse} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    await user.click(screen.getByRole("button", { name: /^Edit path:/ }));
    const input = screen.getByRole("combobox");
    await user.clear(input);
    await user.type(input, "/srv/al");
    await user.keyboard("{Tab}");
    await waitFor(() => expect(onBrowse).toHaveBeenCalledWith("/srv/al", "", false, true));
    await new Promise(resolve => setTimeout(resolve, 200));
    act(() => finish({ ...directory, path: "/srv", partial: true, entries: [{ name: "alpha", path: "/srv/alpha" }] }));
    await waitFor(() => expect(input).toHaveValue("/srv/alpha/"));
    expect(onBrowse.mock.calls.filter(call => call[0] === "/srv/al" || call[0] === "/srv/" && call[1] === "al")).toHaveLength(1);
  });

  it("updates folders while typing and ignores results from older paths", async () => {
    const user = userEvent.setup();
    let finishOld!: (value: WorkspaceDirectoriesPayload) => void;
    const onBrowse = vi.fn((path: string) => path === "/srv/old/" ? new Promise<WorkspaceDirectoriesPayload>(resolve => { finishOld = resolve; }) : Promise.resolve({ ...directory, path, entries: [{ name: path === "/srv/new/" ? "new-child" : "initial-child", path: `${path.replace(/\/$/, "")}/child` }] }));
    const onChange = vi.fn();
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls} onBrowseDirectories={onBrowse} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    await screen.findByRole("option", { name: "/srv/workspace/child" });
    await user.click(screen.getByRole("button", { name: /^Edit path:/ }));
    const input = screen.getByRole("combobox");
    await user.clear(input);
    await user.type(input, "/srv/old/");
    expect(screen.queryByRole("option", { name: "/srv/workspace/child" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled();
    await waitFor(() => expect(onBrowse).toHaveBeenCalledWith("/srv/old/", "", false, true));
    await user.clear(input);
    await user.type(input, "/srv/new/");
    await screen.findByRole("option", { name: "/srv/new/child" });
    finishOld({ ...directory, path: "/srv/old/", entries: [{ name: "stale-child", path: "/srv/old/child" }] });
    await waitFor(() => expect(screen.queryByRole("option", { name: "/srv/old/child" })).not.toBeInTheDocument());
    expect(screen.getByRole("combobox")).toBe(input);
    expect(input).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ project_path: "/srv/new/" }));
  });

  it.each(["Escape", "outside"])("preserves directory filtering when path editing is canceled with %s", async (cancel) => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const onBrowse = vi.fn((raw: string, query: string) => {
      const path = raw.replace(/\/$/, "");
      const names = path === scope.project_path ? ["alpha", "beta"] : ["child"];
      return Promise.resolve({ ...directory, path, entries: names.filter(name => name.includes(query)).map(name => ({ name, path: `${path}/${name}` })) });
    });
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls} onBrowseDirectories={onBrowse} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    await screen.findByRole("option", { name: "/srv/workspace/alpha" });
    const input = screen.getByRole("textbox", { name: "Filter this folder" });
    await user.type(input, "alp");
    await waitFor(() => expect(onBrowse).toHaveBeenLastCalledWith("/srv/workspace", "alp", false, true));
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Edit path:/ }));
    expect(input).toBeDisabled();
    expect(screen.getByRole("combobox")).toHaveValue("/srv/workspace/");
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "/srv/other/" } });
    await screen.findByRole("option", { name: "/srv/other/child" });
    if (cancel === "Escape") await user.keyboard("{Escape}");
    else await user.click(screen.getByRole("listbox", { name: "/srv/other" }));
    expect(input).toBeEnabled();
    expect(input).toHaveValue("alp");
    await screen.findByRole("option", { name: "/srv/workspace/alpha" });
    expect(screen.queryByRole("option", { name: "/srv/workspace/beta" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "/srv/other/child" })).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });
  it("moves to the focused column's parent with the left arrow", async () => {
    const user = userEvent.setup();
    const browse = vi.fn((raw: string) => {
      const path = raw.replace(/\/$/, "");
      return Promise.resolve({ ...directory, path, parent: path.slice(0, path.lastIndexOf("/")) || "/",
        entries: [{ name: "child", path: `${path}/child` }] });
    });
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls} onBrowseDirectories={browse} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    await user.click(await screen.findByRole("option", { name: "/srv/workspace/child" }));
    await user.click(await screen.findByRole("option", { name: "/srv/workspace/child/child" }));
    const ancestor = screen.getByRole("listbox", { name: "/srv/workspace", exact: true });
    act(() => ancestor.focus());
    await user.keyboard("{ArrowLeft}");
    await screen.findByRole("listbox", { name: "/srv", exact: true });
    expect(screen.getAllByRole("listbox")).toHaveLength(1);
  });

  it("keeps ancestor columns and replaces descendants when another folder is opened", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const onBrowse = vi.fn((rawPath: string, _query: string, showHidden: boolean) => {
      const path = rawPath.replace(/\/$/, "");
      const names = path === scope.project_path ? ["alpha", "beta"] : path.endsWith("/alpha") ? ["child"] : path.endsWith("/beta") ? ["other"] : [];
      if (showHidden) names.push(".hidden");
      return Promise.resolve({ ...directory, path, entries: names.map(name => ({ name, path: `${path}/${name}` })) });
    });
    render(<WorkspaceProjectPicker isHero scope={scope} defaultScope={scope} controls={catalog.controls} onBrowseDirectories={onBrowse} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Switch working directory" }));
    await user.click(await screen.findByRole("option", { name: "/srv/workspace/alpha" }));
    await user.click(await screen.findByRole("option", { name: "/srv/workspace/alpha/child" }));
    expect(screen.getAllByRole("listbox")).toHaveLength(3);
    await user.click(screen.getByRole("button", { name: /^Edit path:/ }));
    expect(screen.getAllByRole("listbox")).toHaveLength(3);
    await user.click(screen.getByRole("listbox", { name: "/srv/workspace/alpha/child" }));
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.getAllByRole("listbox")).toHaveLength(3);
    await user.click(screen.getByRole("button", { name: /^Edit path:/ }));
    await user.clear(screen.getByRole("combobox"));
    await user.type(screen.getByRole("combobox"), "/srv/workspace/beta/");
    await screen.findByRole("option", { name: "/srv/workspace/beta/other" });
    await user.keyboard("{Escape}");
    expect(screen.getAllByRole("listbox")).toHaveLength(3);
    expect(screen.queryByRole("option", { name: "/srv/workspace/beta/other" })).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: "/srv/workspace/alpha" })).toHaveAttribute("aria-selected", "true");
    expect(onChange).not.toHaveBeenCalled();
    expect(onBrowse.mock.calls.filter(call => call[0].replace(/\/$/, "") === scope.project_path)).toHaveLength(1);
    await user.click(screen.getByRole("switch", { name: "Show hidden folders" }));
    await screen.findByRole("option", { name: "/srv/workspace/.hidden" });
    await screen.findByRole("option", { name: "/srv/workspace/alpha/.hidden" });
    await screen.findByRole("option", { name: "/srv/workspace/alpha/child/.hidden" });
    await user.click(screen.getByRole("option", { name: "/srv/workspace/beta" }));
    await screen.findByRole("option", { name: "/srv/workspace/beta/other" });
    expect(screen.getAllByRole("listbox")).toHaveLength(2);
    expect(screen.queryByRole("option", { name: "/srv/workspace/alpha/child" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ project_path: "/srv/workspace/beta" }));
  });

});
