import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ThreadMessages } from "@/components/thread/ThreadMessages";
import { fmtDateTime } from "@/lib/format-time";

vi.mock("@/components/MarkdownText", () => ({ MarkdownText: ({ children }: { children: string }) => <p>{children}</p> }));
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("desktop hover timestamp", () => {
  it("shows user creation / assistant completion time without opening a panel on click", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 8, 24, 16));
    const createdAt = new Date(2026, 8, 23, 12).getTime();
    const completedAt = new Date(2026, 8, 24, 14, 32).getTime();
    const { container } = render(<ThreadMessages messages={[
      { id: "u", role: "user", content: "Question", createdAt },
      { id: "a", role: "assistant", content: "Answer", createdAt, completedAt },
    ]} />);
    const times = container.querySelectorAll<HTMLTimeElement>("[data-message-side-actions] time[data-message-hover-time]");
    expect(times).toHaveLength(2);
    expect(times[0]).toHaveTextContent("9/23");
    expect(times[1]).toHaveTextContent("14:32");
    expect(times[1]).toHaveAttribute("datetime", new Date(completedAt).toISOString());
    fireEvent.click(times[1]);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(times[1]).toHaveAttribute("tabindex", "0");
    fireEvent.focus(times[1]);
    expect(await screen.findByRole("tooltip")).toHaveTextContent(fmtDateTime(completedAt));
  });

  it("refreshes the short date when hovering again after midnight", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    const createdAt = new Date(2026, 11, 31, 23, 30).getTime();
    vi.setSystemTime(new Date(2026, 11, 31, 23, 50));
    const { container } = render(<ThreadMessages messages={[{ id: "a", role: "assistant", content: "Answer", createdAt }]} />);
    const time = container.querySelector("[data-message-hover-time]")!;
    const row = time.closest("[data-thread-display-unit]")!;
    fireEvent.pointerEnter(row, { pointerType: "mouse" });
    expect(time).toHaveTextContent("23:30");
    fireEvent.pointerLeave(row, { pointerType: "mouse", relatedTarget: document.body });
    vi.setSystemTime(new Date(2027, 0, 1, 0, 10));
    fireEvent.pointerEnter(row, { pointerType: "mouse" });
    expect(time).toHaveTextContent("12/31");
  });

  it("falls back to creation time and omits invalid timestamps", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 8, 24, 16));
    const { container } = render(<ThreadMessages messages={[
      { id: "a", role: "assistant", turnId: "first", content: "Answer", createdAt: new Date(2026, 8, 22).getTime(), completedAt: NaN },
      { id: "b", role: "assistant", turnId: "second", content: "Unknown", createdAt: NaN },
    ]} />);
    const times = container.querySelectorAll("[data-message-hover-time]");
    expect(times).toHaveLength(1);
    expect(times[0]).toHaveTextContent("9/22");
    const unknown = screen.getByText("Unknown").closest<HTMLElement>("[data-thread-display-unit]")!;
    expect(within(unknown).getByRole("button", { name: "Copy" })).toBeEnabled();
    expect(unknown.querySelector('button[aria-haspopup="dialog"]')).toBeNull();
  });
});
