import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ModelPresetBadge } from "@/components/thread/ModelPresetBadge";

const presets = [
  { name: "zhipu", model: "glm-5", provider: "zhipu" },
  { name: "codex", model: "openai-codex/gpt-5.5", provider: "openai_codex" },
];

describe("ModelPresetBadge setup tooltip", () => {
  it.each([true, false])("keeps setup actionable without repeating its prompt in a tooltip (hero: %s)", async (isHero) => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <ModelPresetBadge
        label="Choose your AI"
        modelDetail="claude-opus-4-5"
        provider="anthropic"
        providerLabel="Anthropic"
        needsSetup
        onClick={onClick}
        isHero={isHero}
      />,
    );

    const trigger = screen.getByRole("button", { name: "Choose your AI" });
    await user.hover(trigger);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    await user.unhover(trigger);
    fireEvent.keyDown(trigger, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("tooltip")).not.toBeInTheDocument());
    fireEvent.focus(trigger);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    await user.click(trigger);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it(
    "keeps the localized setup prompt instead of an available preset",
    async () => {
      render(
        <ModelPresetBadge
          label="选择你的 AI"
          modelDetail="claude-opus-4-5"
          providerLabel="Anthropic"
          modelPresets={presets}
          needsSetup
          onClick={vi.fn()}
          isHero={false}
        />,
      );

      const trigger = screen.getByRole("button", { name: "选择你的 AI" });
      expect(trigger).toHaveTextContent("选择你的 AI");
      expect(trigger.querySelector("[data-fallback]")).toBeNull();
      fireEvent.focus(trigger);
      expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    },
  );
});

describe("ModelPresetBadge selected preset tooltip", () => {
  it.each([true, false])("keeps the single-preset menu and management reachable (hero: %s)", async (isHero) => {
    const user = userEvent.setup();
    const onPresetChange = vi.fn();
    const onManageModels = vi.fn();
    render(
      <ModelPresetBadge
        label="deepseek-flash"
        modelPreset="deepseek-flash"
        modelDetail="deepseek/deepseek-v4-flash"
        modelPresets={[{ name: "deepseek-flash", provider: "deepseek" }]}
        onPresetChange={onPresetChange}
        onManageModels={onManageModels}
        isHero={isHero}
      />,
    );
    const trigger = screen.getByRole("button", { name: "deepseek-flash" });
    expect(trigger).not.toHaveClass("cursor-grab");
    await user.tab();
    expect(trigger).toHaveFocus();
    await user.keyboard("{Enter}");
    const selected = await screen.findByRole("option", { name: "deepseek-flash" });
    expect(selected).toHaveAttribute("aria-selected", "true");
    expect(selected).toHaveFocus();
    expect(screen.getAllByRole("option")).toHaveLength(1);
    await user.click(selected);
    expect(onPresetChange).not.toHaveBeenCalled();
    await user.click(trigger);
    await user.tab();
    expect(screen.getByRole("button", { name: "Manage models" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(onManageModels).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("does not start drag switching with only one preset", () => {
    vi.useFakeTimers();
    try {
      render(<ModelPresetBadge label="only" modelPreset="only" onPresetChange={vi.fn()} onManageModels={vi.fn()} isHero />);
      const trigger = screen.getByRole("button", { name: "only" });
      fireEvent.pointerDown(trigger, { pointerId: 1, pointerType: "touch", clientY: 100 });
      act(() => vi.advanceTimersByTime(500));
      expect(screen.queryByTestId("composer-model-pill-viewport")).not.toBeInTheDocument();
      fireEvent.pointerUp(trigger, { pointerId: 1, pointerType: "touch", clientY: 100 });
      fireEvent.click(trigger);
      expect(screen.getByRole("button", { name: "Manage models" })).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("offers management for an implicit default without inventing a named preset", async () => {
    const onPresetChange = vi.fn();
    const onManageModels = vi.fn();
    render(<ModelPresetBadge label="deepseek-chat" provider="deepseek" onPresetChange={onPresetChange} onManageModels={onManageModels} isHero />);
    fireEvent.click(screen.getByRole("button", { name: "deepseek-chat" }));
    const current = screen.getByRole("option", { name: "deepseek-chat" });
    expect(current).toHaveAttribute("aria-selected", "true");
    fireEvent.click(current);
    expect(onPresetChange).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "deepseek-chat" }));
    fireEvent.click(screen.getByRole("button", { name: "Manage models" }));
    expect(onManageModels).toHaveBeenCalledTimes(1);
  });

  it("moves focus within an open picker without changing the model until selection", async () => {
    const user = userEvent.setup();
    const onPresetChange = vi.fn();
    render(<ModelPresetBadge label="zhipu" modelPreset="zhipu" modelPresets={presets} onPresetChange={onPresetChange} isHero />);
    await user.click(screen.getByRole("button", { name: "zhipu" }));
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("option", { name: "codex" })).toHaveFocus();
    expect(onPresetChange).not.toHaveBeenCalled();
    await user.keyboard("{Enter}");
    expect(onPresetChange).toHaveBeenCalledWith("codex");
  });

  it("shows the selected preset on hover and preserves the preset picker", async () => {
    const user = userEvent.setup();
    const onPresetChange = vi.fn();
    const { container } = render(
      <ModelPresetBadge
        label="zhipu"
        modelPreset="zhipu"
        modelDetail="glm-5"
        provider="zhipu"
        modelPresets={presets}
        onPresetChange={onPresetChange}
        isHero={false}
      />,
    );

    const trigger = screen.getByRole("button", { name: "zhipu" });
    expect(container.querySelector("[title]")).toBeNull();
    await user.hover(trigger);
    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent("zhipu · glm-5");
    expect(tooltip).not.toHaveTextContent("codex");
    await user.click(trigger);
    expect(await screen.findByRole("listbox")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("tooltip")).not.toBeInTheDocument());
    await user.click(screen.getByRole("option", { name: "codex" }));
    expect(onPresetChange).toHaveBeenCalledWith("codex");
  });

  it("exposes the current preset to keyboard focus without a picker", async () => {
    render(
      <ModelPresetBadge
        label="zhipu"
        modelDetail="glm-5"
        modelPresets={presets}
        isHero
      />,
    );
    const trigger = screen.getByLabelText("zhipu");
    expect(trigger).toHaveAttribute("tabindex", "0");
    fireEvent.focus(trigger);
    expect(await screen.findByRole("tooltip")).toHaveTextContent(
      "zhipu · glm-5",
    );
    fireEvent.keyDown(trigger, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("tooltip")).not.toBeInTheDocument());
  });
});
