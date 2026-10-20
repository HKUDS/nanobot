import { useState } from "react";
import userEvent from "@testing-library/user-event";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  CredentialForm,
  channelValuesForSubmit,
  defaultChannelFieldValues,
} from "@/components/settings/channels/CredentialForm";
import { channelSetup } from "@/components/settings/channels/ChannelIdentity";
import type { ChannelConfigField } from "@/channel-plugins/catalog";

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
  it("preserves inherited notices and lets an explicit override return to the default", () => {
    const key = "channels.qq.showCompactionNotices";
    const setup = channelSetup({
      name: "qq", display_name: "QQ", type: "channel", enabled: false,
      installed: true, ready: false, status: "not_enabled",
      install_supported: true, requires_restart: false,
      setup: { fields: [{
        key, field: "showCompactionNotices", kind: "bool", choices: [],
        required: false, inheritable: true,
      }] },
    });
    const noticeFields = setup.fields!;
    expect(defaultChannelFieldValues(noticeFields)).toEqual({ [key]: "" });
    expect(channelValuesForSubmit(noticeFields, {}, new Set())).toEqual({});
    expect(defaultChannelFieldValues(noticeFields, { [key]: "false" })).toEqual({ [key]: "false" });
    expect(channelValuesForSubmit(noticeFields, { [key]: "true" }, new Set([key])))
      .toEqual({ [key]: "true" });
    expect(channelValuesForSubmit(noticeFields, { [key]: "" }, new Set([key])))
      .toEqual({ [key]: "" });

    const onChange = vi.fn();
    render(<CredentialForm fields={noticeFields} values={{ [key]: "false" }}
      visibleSecrets={{}} onChange={onChange} onToggleSecret={vi.fn()} />);
    expect(screen.getByRole("radio", { name: "Off" })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: "Default" }));
    expect(onChange).toHaveBeenCalledWith(key, "");
  });

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

  it("associates option errors and exposes a stable focus target", () => {
    render(
      <CredentialForm
        fields={[fields[1]!]}
        values={{ "channels.matrix.groupPolicy": "mention" }}
        visibleSecrets={{}}
        onChange={vi.fn()}
        onToggleSecret={vi.fn()}
        errors={{ "channels.matrix.groupPolicy": "Required to complete setup." }}
      />,
    );

    const group = screen.getByRole("group", { name: "Group behavior" });
    const firstRadio = within(group).getByRole("radio", { name: "Mention only" });
    const secondRadio = within(group).getByRole("radio", { name: "All messages" });

    expect(group).toHaveAttribute("id", "channel-field-channels-matrix-groupPolicy-group");
    expect(group).toHaveAttribute("aria-invalid", "true");
    expect(group).toHaveAccessibleDescription(
      "Required to complete setup.",
    );
    expect(firstRadio).toHaveAttribute("id", "channel-field-channels-matrix-groupPolicy");
    expect(secondRadio).toHaveAttribute("id", "channel-field-channels-matrix-groupPolicy-1");
    expect(firstRadio).toHaveAttribute("aria-invalid", "true");
    expect(firstRadio).toHaveAccessibleDescription(
      "Required to complete setup.",
    );

    document.getElementById("channel-field-channels-matrix-groupPolicy")?.focus();
    expect(firstRadio).toHaveFocus();
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
        showSecretActions
      />,
    );

    const password = screen.getByLabelText("Password");
    expect(password).toHaveAttribute("aria-invalid", "true");
    expect(password).toHaveAccessibleDescription("Required to complete setup.");
    fireEvent.click(screen.getByRole("button", { name: "Remove credentials" }));
    expect(onClearSecret).toHaveBeenCalledWith("channels.matrix.password", true);
  });

  it("keeps saved hints out of drafts and preserves blur, visibility and clear/keep actions", async () => {
    const key = "channels.matrix.password";
    const onFieldBlur = vi.fn();
    const onSubmit = vi.fn();
    function Editor() {
      const [value, setValue] = useState("");
      const [visible, setVisible] = useState(false);
      const [cleared, setCleared] = useState(false);
      return <form onSubmit={(event) => { event.preventDefault(); onSubmit(); }}>
        <CredentialForm fields={[fields[0]!]} values={{ [key]: value }}
          configuredFields={new Set([key])} visibleSecrets={{ [key]: visible }}
          onChange={(_, draft) => setValue(draft)} onFieldBlur={onFieldBlur}
          onToggleSecret={() => setVisible((current) => !current)}
          clearedSecrets={new Set(cleared ? [key] : [])} showSecretActions
          onClearSecret={(_, clear) => setCleared(clear)} />
      </form>;
    }
    const user = userEvent.setup();
    render(<Editor />);
    const input = screen.getByLabelText("Password");
    expect(input).toHaveValue("");
    expect(input).toHaveAttribute("placeholder", "Saved secret");
    await user.type(input, "replacement");
    await user.click(screen.getByRole("button", { name: "Show secret" }));
    expect(input).toHaveAttribute("type", "text");
    expect(input).toHaveValue("replacement");
    expect(onFieldBlur).toHaveBeenCalledWith(key);
    expect(onSubmit).toHaveBeenCalledTimes(0);
    await user.clear(input);
    await user.click(screen.getByRole("button", { name: "Remove credentials" }));
    expect(screen.getByText("Will be removed")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Keep credentials" }));
    expect(input).toHaveValue("");
    expect(input).toHaveAttribute("placeholder", "Saved secret");
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
