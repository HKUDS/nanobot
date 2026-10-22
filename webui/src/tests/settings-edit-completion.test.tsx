import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { installSettingsViewTestHooks, renderSettingsView, requestMutationMock, settingsPayload } from "@/tests/settings-test-utils";
import { describe, expect, it, vi } from "vitest";
import { useEditCompletion, type EditCompletion } from "@/components/settings/shared/useEditCompletion";
import { NumberInput } from "@/components/settings/shared/SettingsControls";
import { ReasoningEffortPicker } from "@/components/settings/models/ReasoningEffortPicker";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function Editor({ save, identity = "a", expose }: {
  save: (identity: string, value: string) => Promise<boolean>;
  identity?: string;
  expose?: (edits: EditCompletion) => void;
}) {
  const [value, setValue] = useState("");
  const edits = useEditCompletion(value, value !== "", () => save(identity, value), value !== "invalid", identity);
  expose?.(edits);
  return <div onChangeCapture={edits.onChangeCapture} onFocusCapture={edits.onFocusCapture} onBlurCapture={edits.onBlurCapture}>
    <input aria-label="Draft" value={value} onChange={(event) => setValue(event.target.value)} />
    <button onClick={() => setValue("selected")}>Select</button>
    <button onClick={() => void edits.commit()}>Close</button>
  </div>;
}

describe("settings edit completion", () => {
  it("does not restore a closing picker over a newer focused input", async () => {
    vi.useFakeTimers();
    try {
      render(<Dialog open><DialogContent aria-describedby={undefined}><DialogTitle>Model</DialogTitle>
        <ReasoningEffortPicker token="test" provider={undefined} model="test" value="" onChange={() => {}} />
        <input aria-label="Next field" />
      </DialogContent></Dialog>);
      const effort = screen.getByRole("combobox", { name: "Reasoning effort" });
      effort.focus();
      fireEvent.click(effort);
      const option = screen.getByRole("option", { name: "Default" });
      option.focus();
      fireEvent.click(option);
      // The enclosing Radix focus scope recovers here after the option is removed.
      screen.getByRole("dialog").focus();
      await act(async () => { vi.runOnlyPendingTimers(); });
      expect(effort).toHaveFocus();
      fireEvent.click(effort);
      const selected = screen.getByRole("option", { name: "Default" });
      selected.focus();
      fireEvent.click(selected);
      const next = screen.getByRole("textbox", { name: "Next field" });
      next.focus();
      await act(async () => { vi.runOnlyPendingTimers(); });
      expect(next).toHaveFocus();
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps text draft through pauses, then deduplicates blur and close", async () => {
    const pending = deferred<boolean>();
    const save = vi.fn(() => pending.promise);
    render(<Editor save={save} />);
    const input = screen.getByRole("textbox");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "first" } });
    await act(async () => { await new Promise((done) => setTimeout(done, 700)); });
    expect(save).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "latest" } });
    fireEvent.blur(input);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(save).toHaveBeenCalledWith("a", "latest"));
    expect(save).toHaveBeenCalledTimes(1);
    await act(async () => pending.resolve(true));
  });

  it("saves discrete edits immediately and serializes later completed drafts", async () => {
    const first = deferred<boolean>();
    const save = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue(true);
    render(<Editor save={save} />);
    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    await waitFor(() => expect(save).toHaveBeenCalledWith("a", "selected"));
    expect(save).toHaveBeenCalledTimes(1);
    const input = screen.getByRole("textbox");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "second" } });
    fireEvent.blur(input);
    await act(async () => {});
    expect(save).toHaveBeenCalledTimes(1);
    await act(async () => first.resolve(true));
    await waitFor(() => expect(save).toHaveBeenLastCalledWith("a", "second"));
  });

  it("does not confuse a later edit with an earlier successful draft containing the same text", async () => {
    const pending = deferred<boolean>();
    const save = vi.fn().mockResolvedValueOnce(true).mockReturnValueOnce(pending.promise).mockResolvedValue(true);
    render(<Editor save={save} />);
    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "different" } });
    fireEvent.blur(input);
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    fireEvent.change(input, { target: { value: "selected" } });
    fireEvent.blur(input);
    await act(async () => pending.resolve(true));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(3));
    expect(save).toHaveBeenLastCalledWith("a", "selected");
  });

  it("flushes the focused version on unmount, including after a request already in flight", async () => {
    const first = deferred<boolean>();
    const save = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue(true);
    const view = render(<Editor save={save} />);
    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    fireEvent.focus(screen.getByRole("textbox"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "unmounted" } });
    view.unmount();
    await act(async () => first.resolve(true));
    await waitFor(() => expect(save).toHaveBeenLastCalledWith("a", "unmounted"));
  });

  it("persists a revert to the old baseline when an earlier save is still pending", async () => {
    const first = deferred<boolean>();
    const save = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue(true);
    render(<Editor save={save} />);
    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await act(async () => first.resolve(true));
    await waitFor(() => expect(save).toHaveBeenLastCalledWith("a", ""));
  });

  it("retains an empty numeric draft instead of committing it as zero", async () => {
    const save = vi.fn().mockResolvedValue(true);
    function NumericEditor() {
      const [value, setValue] = useState(1);
      const edits = useEditCompletion(value, value !== 1, () => save(value), Number.isFinite(value));
      return <div onChangeCapture={edits.onChangeCapture} onFocusCapture={edits.onFocusCapture} onBlurCapture={edits.onBlurCapture}>
        <NumberInput value={value} min={0} max={2} onChange={setValue} />
      </div>;
    }
    render(<NumericEditor />);
    const input = screen.getByRole("spinbutton");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.blur(input);
    await act(async () => {});
    expect(input).toHaveValue(null);
    expect(save).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "0" } });
    fireEvent.blur(input);
    await waitFor(() => expect(save).toHaveBeenCalledWith(0));
  });

  it("blocks completion for invalid or rejected drafts and permits retry", async () => {
    const save = vi.fn().mockResolvedValueOnce(false).mockResolvedValue(true);
    let edits!: EditCompletion;
    render(<Editor save={save} expose={(current) => { edits = current; }} />);
    fireEvent.focus(screen.getByRole("textbox"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "invalid" } });
    expect(await edits.commit()).toBe(false);
    expect(save).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "valid" } });
    expect(await edits.commit()).toBe(false);
    expect(screen.getByRole("textbox")).toHaveValue("valid");
    expect(await edits.commit()).toBe(true);
    expect(save).toHaveBeenCalledTimes(2);
  });

  it("does not flush a newer focused text draft when a discrete save finishes", async () => {
    const first = deferred<boolean>();
    const save = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue(true);
    render(<Editor save={save} />);
    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    await waitFor(() => expect(save).toHaveBeenCalledWith("a", "selected"));
    fireEvent.focus(screen.getByRole("textbox"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "still typing" } });
    await act(async () => first.resolve(true));
    expect(save).toHaveBeenCalledTimes(1);
    fireEvent.blur(screen.getByRole("textbox"));
    await waitFor(() => expect(save).toHaveBeenLastCalledWith("a", "still typing"));
  });

  it("retains each source object when blur and an object switch share a turn", async () => {
    const first = deferred<boolean>();
    const save = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue(true);
    let edits!: EditCompletion;
    const view = render(<Editor save={save} expose={(current) => { edits = current; }} />);
    fireEvent.focus(screen.getByRole("textbox"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "object-a" } });
    fireEvent.blur(screen.getByRole("textbox"));
    view.rerender(<Editor save={save} identity="b" expose={(current) => { edits = current; }} />);
    fireEvent.focus(screen.getByRole("textbox"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "object-b" } });
    const completion = edits.commit();
    await waitFor(() => expect(save).toHaveBeenCalledWith("a", "object-a"));
    await act(async () => first.resolve(true));
    expect(await completion).toBe(true);
    expect(save).toHaveBeenLastCalledWith("b", "object-b");
  });
});

// Exercise the real controller and portaled editor, not only the completion primitive.
describe("model editor completion boundaries", () => {
  installSettingsViewTestHooks();

  it("retains a focused draft through a pause and a failed close, then retries without losing it", async () => {
    const payload = settingsPayload();
    const saved = {
      ...payload,
      model_presets: payload.model_presets.map((preset) => ({ ...preset, name: "Renamed", label: "Renamed" })),
      model_call_order: ["Renamed"],
    };
    requestMutationMock.mockRejectedValueOnce(new Error("Save failed")).mockResolvedValueOnce(saved);
    renderSettingsView({ initialSection: "models", initialSettings: payload });
    fireEvent.click(within(screen.getByTestId("model-call-order-row-primary")).getAllByRole("button")[0]);
    const name = screen.getByRole("textbox", { name: "Preset name" });
    fireEvent.focus(name);
    fireEvent.change(name, { target: { value: "Renamed" } });
    await act(async () => { await new Promise((done) => setTimeout(done, 700)); });
    expect(requestMutationMock).not.toHaveBeenCalled();
    fireEvent.blur(name);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledTimes(1));
    await act(async () => {});
    expect(screen.getByRole("textbox", { name: "Preset name" })).toHaveValue("Renamed");
    expect(within(screen.getByRole("dialog")).getByRole("alert")).toHaveTextContent("Save failed");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(requestMutationMock).toHaveBeenCalledTimes(2);
  });

  it("keeps a failed context-window save visible in the advanced dialog", async () => {
    const payload = settingsPayload();
    requestMutationMock.mockRejectedValueOnce(new Error("Save failed"));
    renderSettingsView({ initialSection: "models", initialSettings: payload });
    fireEvent.click(within(screen.getByTestId("model-call-order-row-primary")).getAllByRole("button")[0]);
    fireEvent.click(screen.getByRole("button", { name: /Advanced options/ }));
    const context = screen.getByRole("textbox", { name: "Context window" });
    fireEvent.focus(context);
    fireEvent.change(context, { target: { value: "500k" } });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledTimes(1));
    expect(within(screen.getByRole("dialog", { name: "Advanced options" })).getByRole("alert")).toHaveTextContent("Save failed");
    expect(context).toHaveValue("500k");
  });

  it("does not let an unchanged reasoning selection complete subsequent typing", async () => {
    renderSettingsView({ initialSection: "models", initialSettings: settingsPayload() });
    fireEvent.click(within(screen.getByTestId("model-call-order-row-primary")).getAllByRole("button")[0]);
    const effort = screen.getByRole("combobox", { name: "Reasoning effort" });
    fireEvent.click(effort);
    fireEvent.click(await screen.findByRole("option", { name: "Default" }));
    fireEvent.focus(effort);
    fireEvent.change(effort, { target: { value: "m" } });
    await act(async () => {});
    expect(effort).toHaveValue("m");
    expect(requestMutationMock).not.toHaveBeenCalled();
    fireEvent.blur(effort);
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.model_configuration.update", { name: "primary", reasoning_effort: "m" }, 20_000,
    ));
  });

  it("queues a rename back to its original name using the latest catalog", async () => {
    const payload = settingsPayload();
    const first = deferred<ReturnType<typeof settingsPayload>>();
    requestMutationMock.mockReturnValueOnce(first.promise).mockResolvedValueOnce(payload);
    renderSettingsView({ initialSection: "models", initialSettings: payload });
    fireEvent.click(within(screen.getByTestId("model-call-order-row-primary")).getAllByRole("button")[0]);
    const name = screen.getByRole("textbox", { name: "Preset name" });
    fireEvent.focus(name);
    fireEvent.change(name, { target: { value: "First" } });
    fireEvent.blur(name);
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledTimes(1));
    fireEvent.focus(name);
    fireEvent.change(name, { target: { value: "primary" } });
    fireEvent.blur(name);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await act(async () => first.resolve({
      ...payload, model_presets: payload.model_presets.map((preset) => ({ ...preset, name: "First", label: "First" })),
      model_call_order: ["First"],
    }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenLastCalledWith(
      "settings.model_configuration.update", { name: "First", new_name: "primary" }, 20_000,
    ));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByTestId("model-call-order-row-primary")).toBeInTheDocument();
    expect(requestMutationMock).toHaveBeenCalledTimes(2);
  });

  it("preserves and queues a later rename while the previous rename response is pending", async () => {
    const payload = settingsPayload();
    const first = deferred<ReturnType<typeof settingsPayload>>();
    requestMutationMock.mockReturnValueOnce(first.promise).mockImplementationOnce(async (_action, args) => ({
      ...payload,
      model_presets: payload.model_presets.map((preset) => ({ ...preset, name: args.new_name, label: args.new_name })),
      model_call_order: [args.new_name],
    }));
    renderSettingsView({ initialSection: "models", initialSettings: payload });
    fireEvent.click(within(screen.getByTestId("model-call-order-row-primary")).getAllByRole("button")[0]);
    const name = screen.getByRole("textbox", { name: "Preset name" });
    fireEvent.focus(name);
    fireEvent.change(name, { target: { value: "First" } });
    fireEvent.blur(name);
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.focus(name);
    fireEvent.change(name, { target: { value: "Latest" } });
    await act(async () => first.resolve({
      ...payload,
      model_presets: payload.model_presets.map((preset) => ({ ...preset, name: "First", label: "First" })),
      model_call_order: ["First"],
    }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenLastCalledWith(
      "settings.model_configuration.update", { name: "First", new_name: "Latest" }, 20_000,
    ));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByTestId("model-call-order-row-Latest")).toBeInTheDocument();
  });
});
