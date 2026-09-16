import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ModelPresetBadge } from "@/components/thread/ModelPresetBadge";

const presets = [
  { name: "zhipu", model: "glm-5", provider: "zhipu" },
  { name: "codex", model: "openai-codex/gpt-5.5", provider: "openai_codex" },
];

describe("ModelPresetBadge fallback tooltip", () => {
  it("shows only the effective preset on hover and preserves the preset picker", async () => {
    const user = userEvent.setup();
    const onPresetChange = vi.fn();
    const { container } = render(
      <ModelPresetBadge
        label="zhipu"
        modelPreset="zhipu"
        modelDetail="glm-5"
        provider="zhipu"
        modelPresets={presets}
        fallbackModelName="openai-codex/gpt-5.5"
        onPresetChange={onPresetChange}
        isHero={false}
      />,
    );

    const trigger = screen.getByRole("button", { name: "codex" });
    expect(container.querySelector("[title]")).toBeNull();
    await user.hover(trigger);
    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent("codex · openai-codex/gpt-5.5");
    expect(tooltip).not.toHaveTextContent("zhipu");
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
        modelPresets={presets}
        fallbackModelName="openai-codex/gpt-5.5"
        isHero
      />,
    );
    const trigger = screen.getByLabelText("codex");
    expect(trigger).toHaveAttribute("tabindex", "0");
    fireEvent.focus(trigger);
    expect(await screen.findByRole("tooltip")).toHaveTextContent(
      "codex · openai-codex/gpt-5.5",
    );
    fireEvent.keyDown(trigger, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("tooltip")).not.toBeInTheDocument());
  });
});
