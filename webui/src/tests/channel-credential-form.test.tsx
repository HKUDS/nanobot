import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  CredentialForm,
  channelValuesForSubmit,
} from "@/components/settings/channels/CredentialForm";
import type { ChannelConfigField } from "@/components/settings/channels/catalog";

const fields: ChannelConfigField[] = [
  {
    key: "channels.matrix.password",
    label: "Password",
    secret: true,
  },
  {
    key: "channels.matrix.groupPolicy",
    label: "Group behavior",
    options: [
      { value: "mention", label: "Mention only" },
      { value: "open", label: "All messages" },
    ],
  },
];

describe("CredentialForm", () => {
  it("uses native radio semantics for option fields", () => {
    const onChange = vi.fn();
    render(
      <CredentialForm
        fields={[fields[1]!]}
        values={{ "channels.matrix.groupPolicy": "mention" }}
        visibleSecrets={{}}
        onChange={onChange}
        onToggleSecret={vi.fn()}
      />,
    );

    const group = screen.getByRole("group", { name: "Group behavior" });
    expect(within(group).getByRole("radio", { name: "Mention only" })).toBeChecked();
    fireEvent.click(within(group).getByRole("radio", { name: "All messages" }));
    expect(onChange).toHaveBeenCalledWith("channels.matrix.groupPolicy", "open");
  });

  it("associates field errors and saved-secret removal actions", () => {
    const onClearSecret = vi.fn();
    render(
      <CredentialForm
        fields={[fields[0]!]}
        values={{}}
        configuredFields={new Set(["channels.matrix.password"])}
        visibleSecrets={{}}
        onChange={vi.fn()}
        onToggleSecret={vi.fn()}
        errors={{ "channels.matrix.password": "Required to complete setup." }}
        onClearSecret={onClearSecret}
      />,
    );

    const password = screen.getByLabelText("Password");
    expect(password).toHaveAttribute("aria-invalid", "true");
    expect(password).toHaveAccessibleDescription("Required to complete setup.");
    fireEvent.click(screen.getByRole("button", { name: "Remove saved credential" }));
    expect(onClearSecret).toHaveBeenCalledWith("channels.matrix.password", true);
  });

  it("uses null only for an explicitly cleared secret", () => {
    expect(
      channelValuesForSubmit(
        fields,
        { "channels.matrix.password": "" },
        new Set(),
        new Set(["channels.matrix.password"]),
      ),
    ).toEqual({ "channels.matrix.password": null });
    expect(channelValuesForSubmit(fields, {}, new Set())).toEqual({});
  });
});
