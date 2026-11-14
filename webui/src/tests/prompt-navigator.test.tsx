import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { PromptNavigator } from "@/components/thread/PromptNavigator";
import { mockBrowserFocus } from "./browser-focus";

let restoreBrowserFocus: () => void;
beforeEach(() => {
  restoreBrowserFocus = mockBrowserFocus();
});

afterEach(() => restoreBrowserFocus());

it("opens Ctrl+F only in the active pane and selects a filtered message with Enter", async () => {
  const user = userEvent.setup();
  const jump = vi.fn();
  const props = { messages: [{ id: "one", role: "user" as const, content: "alpha", createdAt: 1 }], onJumpToPrompt: jump };
  const view = render(<PromptNavigator {...props} shortcutEnabled={false} />);
  fireEvent.keyDown(window, { key: "f", ctrlKey: true });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  view.rerender(<PromptNavigator {...props} shortcutEnabled />);
  fireEvent.keyDown(window, { key: "f", ctrlKey: true });
  const input = await screen.findByRole("textbox", { name: "Search messages" });
  await waitFor(() => expect(input).toHaveFocus());
  await user.keyboard("alpha{Enter}");
  expect(jump).toHaveBeenCalledWith("one");
});

it("keeps a long searchable index windowed and keyboard-reachable", async () => {
  const user = userEvent.setup();
  const jump = vi.fn();
  render(<PromptNavigator messages={Array.from({ length: 2000 }, (_, index) => ({
    id: String(index), role: "user", content: `Question ${index}`, createdAt: index + 1,
  }))} onJumpToPrompt={jump} />);
  await user.click(screen.getByRole("button", { name: "Message navigation" }));
  expect(screen.getAllByRole("button", { name: /Jump to message:/ }).length).toBeLessThan(25);
  await user.tab();
  await user.keyboard("{End}");
  await waitFor(() => expect(screen.getByRole("button", { name: "Jump to message: Question 1999" })).toHaveFocus());
  await user.keyboard("{Enter}");
  expect(jump).toHaveBeenCalledWith("1999");
});

it("lets users type into prompt search immediately after opening it", async () => {
  const user = userEvent.setup();
  const onJumpToPrompt = vi.fn();
  render(<PromptNavigator messages={[
    { id: "one", role: "user", content: "alpha", createdAt: Date.parse("2026-09-21T00:00:00Z") },
    { id: "two", role: "user", content: "beta", createdAt: Date.parse("2026-09-21T00:01:00Z") },
  ]} onJumpToPrompt={onJumpToPrompt} />);

  await user.tab();
  expect(screen.getByRole("button", { name: "Message navigation" })).toHaveFocus();
  await user.keyboard("{Enter}");
  const search = await screen.findByRole("textbox", { name: "Search messages" });
  await waitFor(() => expect(search).toHaveFocus());
  await user.keyboard("beta");
  expect(search).toHaveValue("beta");
  expect(screen.queryByRole("button", { name: "Jump to message: alpha" })).not.toBeInTheDocument();

  await user.tab();
  expect(screen.getByRole("button", { name: "Jump to message: beta" })).toHaveFocus();
  await user.keyboard("{Enter}");
  expect(onJumpToPrompt).toHaveBeenCalledWith("two");
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});


it("keeps an unknown recovered time blank while the prompt remains navigable", async () => {
  const user = userEvent.setup();
  const onJumpToPrompt = vi.fn();
  render(<PromptNavigator messages={[
    { id: "undated", role: "user", content: "Undated recovered input", createdAt: 0 },
  ]} onJumpToPrompt={onJumpToPrompt} />);
  await user.click(screen.getByRole("button", { name: "Message navigation" }));
  const prompt = screen.getByRole("button", { name: "Jump to message: Undated recovered input" });
  expect(prompt.textContent).toBe("Undated recovered input");
  await user.click(prompt);
  expect(onJumpToPrompt).toHaveBeenCalledWith("undated");
});

it("returns shortcut-opened search to the interrupted editor", async () => {
  const user = userEvent.setup();
  render(<><input aria-label="Draft" /><PromptNavigator messages={[
    { id: "one", role: "user", content: "alpha", createdAt: 1 },
  ]} onJumpToPrompt={vi.fn()} /></>);
  const editor = screen.getByRole("textbox", { name: "Draft" });
  await user.click(editor);
  await user.keyboard("{Control>}f{/Control}");
  await waitFor(() => expect(screen.getByRole("textbox", { name: "Search messages" })).toHaveFocus());
  await user.keyboard("{Escape}");
  await waitFor(() => expect(editor).toHaveFocus());
});
