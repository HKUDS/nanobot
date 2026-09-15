import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AddProviderCombobox } from "@/components/settings/models/ProviderSettings";

type Provider = { name: string; label: string };

const providers: Provider[] = [
  { name: "anthropic", label: "Anthropic" },
  { name: "openai", label: "OpenAI" },
  { name: "xai_grok", label: "xAI Grok" },
  { name: "bedrock", label: "Amazon Bedrock" },
  { name: "mistral", label: "Mistral AI" },
];

function setup() {
  const onSelectCustom = vi.fn();
  const onSelectProvider = vi.fn();
  const user = userEvent.setup();
  render(
    <AddProviderCombobox
      providers={providers}
      showBrandLogos={false}
      onSelectCustom={onSelectCustom}
      onSelectProvider={onSelectProvider}
    />,
  );
  return { user, onSelectCustom, onSelectProvider };
}

async function openDropdown() {
  await userEvent.setup().click(
    screen.getByRole("button", { name: "Add your own model provider" }),
  );
}

describe("AddProviderCombobox", () => {
  it("opens and lists custom provider plus all unconfigured providers", async () => {
    setup();
    await openDropdown();

    const listbox = screen.getByRole("listbox");
    const options = within(listbox).getAllByRole("option");
    expect(options.map((el) => el.textContent)).toEqual([
      "Custom provider",
      ...providers.map((p) => p.label),
    ]);
  });

  it("shows a separator between the pinned custom entry and provider list", async () => {
    setup();
    await openDropdown();

    const listbox = screen.getByRole("listbox");
    expect(listbox.querySelector('[role="separator"]')).toBeInTheDocument();
  });

  it("filters unconfigured providers by name and label case-insensitively", async () => {
    const { user } = setup();
    await openDropdown();

    const input = screen.getByRole("combobox", { name: "Search providers" });
    await user.type(input, "xAI");

    const listbox = screen.getByRole("listbox");
    const options = within(listbox).getAllByRole("option");
    expect(options.map((el) => el.textContent)).toEqual([
      "Custom provider",
      "xAI Grok",
    ]);
  });

  it("filters by provider internal name as well as label", async () => {
    const { user } = setup();
    await openDropdown();

    const input = screen.getByRole("combobox", { name: "Search providers" });
    await user.type(input, "grok");

    const listbox = screen.getByRole("listbox");
    const options = within(listbox).getAllByRole("option");
    expect(options.map((el) => el.textContent)).toEqual([
      "Custom provider",
      "xAI Grok",
    ]);
  });

  it("keeps custom provider pinned and visible regardless of filter", async () => {
    const { user } = setup();
    await openDropdown();

    const input = screen.getByRole("combobox", { name: "Search providers" });
    await user.type(input, "nomatch");

    const listbox = screen.getByRole("listbox");
    const options = within(listbox).getAllByRole("option");
    expect(options).toHaveLength(1);
    expect(options[0].textContent).toBe("Custom provider");

    expect(screen.getByText("No providers match this search.")).toBeInTheDocument();
  });

  it("restores the full list when the query is cleared", async () => {
    const { user } = setup();
    await openDropdown();

    const input = screen.getByRole("combobox", { name: "Search providers" });
    await user.type(input, "xAI");
    await user.clear(input);

    const listbox = screen.getByRole("listbox");
    const options = within(listbox).getAllByRole("option");
    expect(options.map((el) => el.textContent)).toEqual([
      "Custom provider",
      ...providers.map((p) => p.label),
    ]);
  });

  it("selects custom provider when its option is clicked", async () => {
    const { user, onSelectCustom } = setup();
    await openDropdown();

    await user.click(screen.getByRole("option", { name: "Custom provider" }));

    expect(onSelectCustom).toHaveBeenCalledOnce();
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("selects an unconfigured provider when its option is clicked", async () => {
    const { user, onSelectProvider } = setup();
    await openDropdown();

    await user.click(screen.getByRole("option", { name: "OpenAI" }));

    expect(onSelectProvider).toHaveBeenCalledWith("openai");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("supports keyboard navigation and selection", async () => {
    const { user, onSelectProvider } = setup();
    const trigger = screen.getByRole("button", { name: "Add your own model provider" });
    await user.click(trigger);

    const input = await screen.findByRole("combobox", { name: "Search providers" });
    await user.click(input);
    await user.type(input, "{arrowdown}{arrowdown}{enter}");

    expect(onSelectProvider).toHaveBeenCalledWith("openai");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});
