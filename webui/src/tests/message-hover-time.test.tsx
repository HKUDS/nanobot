import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ThreadMessages } from "@/components/thread/ThreadMessages";
import { fmtDateTime } from "@/lib/format";

vi.mock("@/components/MarkdownText", () => ({ MarkdownText: ({ content }: { content: string }) => <p>{content}</p> }));
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("desktop hover timestamp", () => {
  it("uses user creation / assistant completion time and exposes the full date on keyboard focus", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 8, 24, 16));
    const createdAt = new Date(2026, 8, 23, 12).getTime();
    const completedAt = new Date(2026, 8, 24, 14, 32).getTime();
    const { container } = render(<ThreadMessages messages={[
      { id: "u", role: "user", content: "Question", createdAt },
      { id: "a", role: "assistant", content: "Answer", createdAt, completedAt },
    ]} />);
    const times = container.querySelectorAll<HTMLTimeElement>("[data-message-hover-time]");
    expect(times).toHaveLength(2);
    expect(times[0]).toHaveTextContent("9/23");
    expect(times[1]).toHaveTextContent("14:32");
    expect(times[1]).toHaveAttribute("datetime", new Date(completedAt).toISOString());
    expect(times[1]).toHaveAttribute("aria-label", fmtDateTime(completedAt));
    fireEvent.focus(times[1]);
    expect(await screen.findByRole("tooltip")).toHaveTextContent(fmtDateTime(completedAt));
    expect(times[1].closest("[data-thread-display-unit]")).toHaveAttribute("data-context-block-active");
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
      { id: "a", role: "assistant", content: "Answer", createdAt: new Date(2026, 8, 22).getTime(), completedAt: NaN },
      { id: "b", role: "assistant", content: "Unknown", createdAt: NaN },
    ]} />);
    const times = container.querySelectorAll("[data-message-hover-time]");
    expect(times).toHaveLength(1);
    expect(times[0]).toHaveTextContent("9/22");
  });
});
