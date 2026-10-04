import { useState } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AutomationRunAtPicker, parseAutomationRunAt } from "@/components/settings/system/AutomationRunAtPicker";
import { AutomationEditDialog } from "@/components/settings/system/AutomationsSettings";
import i18n from "@/i18n";
import type { SessionAutomationJob } from "@/lib/types";

afterEach(cleanup);

function Harness({ initial = "2032-09-12T09:37" }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  return <AutomationRunAtPicker value={value} onChange={setValue} />;
}

function dayName(value: string) {
  return new Intl.DateTimeFormat("en", { dateStyle: "full" }).format(parseAutomationRunAt(`${value}T12:00`)!);
}

describe("Automation run time picker", () => {
  it("uses text fields and a themed calendar without native date or time controls", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    expect(screen.getByRole("textbox", { name: "Run date" })).toHaveValue("2032-09-12");
    expect(screen.getByRole("textbox", { name: "Run time" })).toHaveValue("09:37");
    expect(document.querySelector('input[type="datetime-local"], input[type="date"], input[type="time"]')).toBeNull();
    const trigger = screen.getByRole("button", { name: "Choose date" });
    await user.click(trigger);
    const calendar = screen.getByRole("dialog", { name: "Choose date" });
    expect(within(calendar).getByRole("grid", { name: "September 2032" })).toBeVisible();
    expect(within(calendar).getByRole("button", { name: dayName("2032-09-12") })).toHaveFocus();
    await user.click(within(calendar).getByRole("button", { name: dayName("2032-09-17") }));
    expect(screen.getByRole("textbox", { name: "Run date" })).toHaveValue("2032-09-17");
    expect(screen.getByRole("textbox", { name: "Run time" })).toHaveValue("09:37");
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("moves focus across month boundaries and clamps PageDown to a leap month's last day", async () => {
    const user = userEvent.setup();
    render(<Harness initial="2032-01-31T09:37" />);
    await user.click(screen.getByRole("button", { name: "Choose date" }));
    await user.keyboard("{PageDown}");
    expect(screen.getByRole("button", { name: dayName("2032-02-29") })).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("button", { name: dayName("2032-03-01") })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("textbox", { name: "Run date" })).toHaveValue("2032-03-01");
    expect(screen.getByRole("textbox", { name: "Run time" })).toHaveValue("09:37");
  });

  it("supports week navigation and Escape without selecting a different date", async () => {
    const user = userEvent.setup();
    render(<Harness initial="2032-03-03T09:37" />);
    const trigger = screen.getByRole("button", { name: "Choose date" });
    await user.click(trigger);
    await user.keyboard("{Home}");
    expect(screen.getByRole("button", { name: dayName("2032-03-01") })).toHaveFocus();
    await user.keyboard("{End}{ArrowDown}");
    expect(screen.getByRole("button", { name: dayName("2032-03-14") })).toHaveFocus();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(screen.getByRole("textbox", { name: "Run date" })).toHaveValue("2032-03-03");
  });

  it("preserves exact minutes when typing and opens the calendar at the typed month", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const date = screen.getByRole("textbox", { name: "Run date" });
    const time = screen.getByRole("textbox", { name: "Run time" });
    await user.clear(date);
    await user.type(date, "2033-01-02");
    await user.clear(time);
    await user.type(time, "23:59");
    await user.click(screen.getByRole("button", { name: "Choose date" }));
    expect(screen.getByRole("grid", { name: "January 2033" })).toBeVisible();
    expect(screen.getByRole("button", { name: dayName("2033-01-02") })).toHaveFocus();
    expect(time).toHaveValue("23:59");
  });

  it("keeps the editor open when dismissing its calendar and saves a local timestamp", async () => {
    const user = userEvent.setup();
    const save = vi.fn();
    const onOpenChange = vi.fn();
    const job: SessionAutomationJob = {
      id: "once", name: "One-time report", enabled: true,
      schedule: { kind: "at", at_ms: new Date(2099, 8, 12, 9, 37).getTime() },
      payload: { message: "Summarize project updates" }, state: {},
    };
    render(<AutomationEditDialog job={job} saving={false} onSave={save} onOpenChange={onOpenChange} />);
    await user.click(screen.getByRole("button", { name: "Choose date" }));
    await user.keyboard("{Escape}");
    expect(screen.getByRole("dialog", { name: "Edit automation" })).toBeVisible();
    expect(onOpenChange).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Choose date" }));
    await user.click(screen.getByRole("button", { name: dayName("2099-09-17") }));
    const time = screen.getByRole("textbox", { name: "Run time" });
    await user.clear(time);
    await user.type(time, "09:45");
    await user.click(screen.getByRole("button", { name: "Save", exact: true }));
    expect(save).toHaveBeenCalledWith(job, {
      name: job.name, message: job.payload.message,
      schedule: { kind: "at", at_ms: new Date(2099, 8, 17, 9, 45).getTime() },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Run date" }), { target: { value: "2099-02-31" } });
    expect(screen.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
    expect(screen.getByText("Choose a run time.")).toBeVisible();
  });

  it("localizes the calendar and its field labels in Chinese", async () => {
    await act(() => i18n.changeLanguage("zh-CN"));
    const user = userEvent.setup();
    render(<Harness />);
    expect(screen.getByRole("textbox", { name: "运行日期" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "运行时刻" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "选择日期" }));
    expect(screen.getByRole("grid", { name: "2032年9月" })).toBeVisible();
    expect(screen.getByRole("button", { name: "下个月" })).toBeVisible();
  });
});

describe("Automation local date validation", () => {
  it.each(["", "2032-02-30T12:00", "2031-02-29T12:00", "2032-13-01T12:00", "2032-00-01T12:00",
    "2032-01-00T12:00", "2032-01-01T24:00", "2032-01-01T12:60", "2032-01-01T9:00", "2032-01-01T", "0000-01-01T12:00"])(
    "rejects an invalid local date or time: %s", (value) => expect(parseAutomationRunAt(value)).toBeNull(),
  );

  it("accepts leap days, midnight, and years below 100 without changing the local fields", () => {
    expect(parseAutomationRunAt("2032-02-29T00:00")?.getTime()).toBe(new Date(2032, 1, 29, 0, 0).getTime());
    expect(parseAutomationRunAt("0099-01-01T00:00")?.getFullYear()).toBe(99);
  });
});
