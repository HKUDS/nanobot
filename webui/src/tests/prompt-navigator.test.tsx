import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { PromptNavigator } from "@/components/thread/PromptNavigator";
import { mockBrowserFocus } from "./browser-focus";

let restoreBrowserFocus: () => void;
beforeEach(() => {
  restoreBrowserFocus = mockBrowserFocus();
});

afterEach(() => restoreBrowserFocus());

it("lets users type into prompt search immediately after opening it", async () => {
  const user = userEvent.setup();
  const onJumpToPrompt = vi.fn();
  render(<PromptNavigator messages={[
    { id: "one", role: "user", content: "alpha", createdAt: Date.parse("2026-09-21T00:00:00Z") },
    { id: "two", role: "user", content: "beta", createdAt: Date.parse("2026-09-21T00:01:00Z") },
  ]} onJumpToPrompt={onJumpToPrompt} />);

  await user.tab();
  expect(screen.getByRole("button", { name: "Open prompt navigator" })).toHaveFocus();
  await user.keyboard("{Enter}");
  const search = await screen.findByRole("textbox", { name: "Search prompts" });
  await waitFor(() => expect(search).toHaveFocus());
  await user.keyboard("beta");
  expect(search).toHaveValue("beta");
  expect(screen.queryByRole("button", { name: "Jump to prompt: alpha" })).not.toBeInTheDocument();

  await user.tab();
  expect(screen.getByRole("button", { name: "Jump to prompt: beta" })).toHaveFocus();
  await user.keyboard("{Enter}");
  expect(onJumpToPrompt).toHaveBeenCalledWith("two");
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});
