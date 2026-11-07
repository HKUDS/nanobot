import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ProviderParameterFields } from "@/components/settings/models/ProviderParameterFields";
import i18n from "@/i18n";
import { ApiError } from "@/lib/api";

beforeEach(async () => { await i18n.changeLanguage("en"); });
afterEach(cleanup);

const form = { extraHeaders: "", extraQuery: "", extraBody: "{}" };

it.each([
  { field: "extra_headers", formKey: "extraHeaders", title: "请求头" },
  { field: "extra_query", formKey: "extraQuery", title: "查询参数" },
] as const)("localizes a rejected secret mask in $field and allows a corrected retry", async ({ field, formKey, title }) => {
  await i18n.changeLanguage("zh-CN");
  const save = vi.fn().mockRejectedValueOnce(new ApiError(400, `${field}.X-Token: Input should be a valid string`)).mockResolvedValue(undefined);
  render(<ProviderParameterFields inherit fields={[field]} form={form} onChange={vi.fn()} onSave={save} />);
  fireEvent.click(screen.getByRole("button", { name: `${title} 使用提供商设置 编辑` }));
  const dialog = screen.getByRole("dialog", { name: title });
  const editor = within(dialog).getByRole("textbox");
  fireEvent.change(editor, { target: { value: '{"X-Token":"••••••••"}' } });
  fireEvent.click(within(dialog).getByRole("button", { name: "保存" }));
  expect(await within(dialog).findByRole("alert")).toHaveTextContent("掩码没有对应的已保存密钥。请输入实际值，或删除该项。");
  expect(editor).toHaveValue('{"X-Token":"••••••••"}');
  expect(editor).toHaveFocus();
  fireEvent.change(editor, { target: { value: '{"X-Token":"fixture-value"}' } });
  await act(async () => { fireEvent.click(within(dialog).getByRole("button", { name: "保存" })); });
  expect(save).toHaveBeenLastCalledWith({ [formKey]: '{"X-Token":"fixture-value"}' });
  expect(screen.queryByRole("dialog", { name: title })).not.toBeInTheDocument();
});

it("lets the gateway preserve an existing masked secret without rejecting it in the editor", async () => {
  const masked = '{"X-Token":"••••••••"}';
  const save = vi.fn().mockResolvedValue(undefined);
  render(<ProviderParameterFields inherit fields={["extra_headers"]} form={{ ...form, extraHeaders: masked }} onChange={vi.fn()} onSave={save} />);
  fireEvent.click(screen.getByRole("button", { name: "Headers Entries: 1 Edit" }));
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Save" })); });
  expect(save).toHaveBeenCalledWith({ extraHeaders: masked });
  expect(screen.queryByRole("dialog", { name: "Headers" })).not.toBeInTheDocument();
});

it("distinguishes a new preset draft from persisted settings and validates before applying", async () => {
  const change = vi.fn();
  render(<ProviderParameterFields inherit draft fields={["extra_headers"]} form={form} onChange={change} />);
  fireEvent.click(screen.getByRole("button", { name: "Headers Use provider settings Edit" }));
  const dialog = screen.getByRole("dialog", { name: "Headers" });
  expect(dialog).toHaveAccessibleDescription("Save the new preset to apply these settings.");
  const editor = within(dialog).getByRole("textbox");
  for (const value of ["broken", "[]", '{"X-Route":123}']) {
    fireEvent.change(editor, { target: { value } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Use in preset" }));
    expect(await within(dialog).findByRole("alert")).toBeVisible();
    expect(change).not.toHaveBeenCalled();
    expect(editor).toHaveFocus();
  }
  fireEvent.change(editor, { target: { value: '{"X-Route":"demo"}' } });
  await act(async () => { fireEvent.click(within(dialog).getByRole("button", { name: "Use in preset" })); });
  expect(change).toHaveBeenCalledTimes(1);
  expect(change).toHaveBeenCalledWith({ extraHeaders: '{"X-Route":"demo"}' });
});

it("waits for persistence, keeps errors and drafts in place, and lets users cancel a failed save", async () => {
  let rejectSave!: (reason: Error) => void;
  const save = vi.fn(() => new Promise<void>((_resolve, reject) => { rejectSave = reject; }));
  const change = vi.fn();
  render(<ProviderParameterFields inherit fields={["extra_body"]} form={form} onChange={change} onSave={save} />);
  fireEvent.click(screen.getByRole("button", { name: "Body parameters Use provider settings Edit" }));
  const dialog = screen.getByRole("dialog", { name: "Body parameters" });
  const editor = within(dialog).getByRole("textbox");
  fireEvent.change(editor, { target: { value: '{"watermark":false}' } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
  expect(within(dialog).getByRole("button", { name: i18n.t("settings.actions.saving") })).toBeDisabled();
  expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeDisabled();
  fireEvent.keyDown(editor, { key: "Escape" });
  expect(dialog).toBeVisible();
  await act(async () => rejectSave(new Error("Connection lost. Try again.")));
  expect(within(dialog).getByRole("alert")).toHaveTextContent("Connection lost. Try again.");
  expect(editor).toHaveValue('{"watermark":false}');
  expect(editor).toHaveFocus();
  fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
  expect(change).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Body parameters Use provider settings Edit" }));
  expect(screen.getByRole("textbox")).toHaveValue("{}");
});
