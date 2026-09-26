import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ProviderPicker } from "@/components/settings/shared/ModelControls";

const PROVIDERS = [
  { name: "anthropic", label: "Anthropic" },
  { name: "openai", label: "OpenAI" },
  { name: "openrouter", label: "OpenRouter" },
  { name: "ollama", label: "Ollama" },
];

function ProviderPickerHarness(props: {
  value?: string;
  disabled?: boolean;
  showProviderLogos?: boolean;
}) {
  const [value, setValue] = useState(props.value ?? "anthropic");
  return (
    <ProviderPicker
      providers={PROVIDERS}
      value={value}
      emptyLabel="Select provider"
      onChange={setValue}
      showProviderLogos={props.showProviderLogos}
      triggerProps={props.disabled ? { disabled: true } : undefined}
    />
  );
}

describe("ProviderPicker", () => {
  it("renders the selected provider label", () => {
    render(<ProviderPickerHarness />);
    expect(screen.getByRole("combobox")).toHaveTextContent("Anthropic");
  });

  it("opens the popover with a filter input and the full list", async () => {
    render(<ProviderPickerHarness />);
    await userEvent.setup().click(screen.getByRole("combobox"));
    expect(screen.getByPlaceholderText("Search providers")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getAllByRole("option").length).toBe(PROVIDERS.length);
    });
  });

  it("filters providers by label substring", async () => {
    render(<ProviderPickerHarness />);
    await userEvent.setup().click(screen.getByRole("combobox"));
    const input = screen.getByPlaceholderText("Search providers");
    await userEvent.setup().type(input, "open");
    await waitFor(() => {
      const options = screen.getAllByRole("option");
      expect(options.map((o) => o.textContent)).toEqual(["OpenAI", "OpenRouter"]);
    });
  });

  it("filters providers by name substring", async () => {
    render(<ProviderPickerHarness />);
    await userEvent.setup().click(screen.getByRole("combobox"));
    const input = screen.getByPlaceholderText("Search providers");
    await userEvent.setup().type(input, "ollama");
    await waitFor(() => {
      const options = screen.getAllByRole("option");
      expect(options.map((o) => o.textContent)).toEqual(["Ollama"]);
    });
  });

  it("shows the full list when the query is empty", async () => {
    render(<ProviderPickerHarness />);
    await userEvent.setup().click(screen.getByRole("combobox"));
    const input = screen.getByPlaceholderText("Search providers");
    await userEvent.setup().type(input, "xyz");
    await userEvent.setup().clear(input);
    await waitFor(() => {
      expect(screen.getAllByRole("option").length).toBe(PROVIDERS.length);
    });
  });

  it("shows a no-matches message when nothing matches", async () => {
    render(<ProviderPickerHarness />);
    await userEvent.setup().click(screen.getByRole("combobox"));
    const input = screen.getByPlaceholderText("Search providers");
    await userEvent.setup().type(input, "nope");
    await waitFor(() => {
      expect(screen.queryByRole("option")).not.toBeInTheDocument();
      expect(screen.getByText("No providers match this search.")).toBeInTheDocument();
    });
  });

  it("selects a provider and closes the popover", async () => {
    const onChange = vi.fn();
    render(
      <ProviderPicker
        providers={PROVIDERS}
        value="anthropic"
        emptyLabel="Select provider"
        onChange={onChange}
      />,
    );
    await userEvent.setup().click(screen.getByRole("combobox"));
    const option = screen.getByRole("option", { name: /OpenAI/i });
    await userEvent.setup().click(option);
    expect(onChange).toHaveBeenCalledWith("openai");
  });

  it("supports keyboard navigation to select a filtered option", async () => {
    const onChange = vi.fn();
    render(
      <ProviderPicker
        providers={PROVIDERS}
        value="anthropic"
        emptyLabel="Select provider"
        onChange={onChange}
      />,
    );
    await userEvent.setup().click(screen.getByRole("combobox"));
    const input = screen.getByPlaceholderText("Search providers");
    await userEvent.setup().type(input, "open");
    await waitFor(() => expect(screen.getAllByRole("option").length).toBe(2));
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("openai");
  });

  it("closes the popover on Escape", async () => {
    render(<ProviderPickerHarness />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("combobox"));
    const input = screen.getByPlaceholderText("Search providers");
    await user.type(input, "open");
    fireEvent.keyDown(input, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByPlaceholderText("Search providers")).not.toBeInTheDocument();
    });
  });

  it("disables the trigger when providers is empty", () => {
    render(
      <ProviderPicker
        providers={[]}
        value=""
        emptyLabel="Select provider"
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("combobox")).toBeDisabled();
  });

  it("shows a provider logo when showProviderLogos is true", async () => {
    render(<ProviderPickerHarness showProviderLogos />);
    await userEvent.setup().click(screen.getByRole("combobox"));
    await waitFor(() => {
      const option = screen.getAllByRole("option")[0];
      expect(
        within(option).queryByTestId(/provider-picker-logo-|provider-picker-logo-fallback-/),
      ).toBeInTheDocument();
    });
  });
});
