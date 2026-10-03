import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SkillsMarketplace } from "@/components/settings/SkillsMarketplace";
import { ThreadComposer } from "@/components/thread/ThreadComposer";
import {
  fetchSkills,
  fetchTrendingMarketplaceSkills,
  searchMarketplaceSkills,
} from "@/lib/api";
import type { NanobotClient } from "@/lib/nanobot-client";
import { requestSkillsRefresh, SKILLS_CHANGED_EVENT } from "@/lib/skill-events";
import { ClientProvider } from "@/providers/ClientProvider";
import { useSkills } from "@/hooks/useSkills";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    fetchSkills: vi.fn(),
    fetchTrendingMarketplaceSkills: vi.fn(),
    searchMarketplaceSkills: vi.fn(),
  };
});

const client = {} as NanobotClient;

function marketplace(token: string) {
  return (
    <ClientProvider client={client} token={token}>
      <SkillsMarketplace
        installedSkills={[]}
        installing=""
        onInstallingChange={() => {}}
      />
    </ClientProvider>
  );
}

describe("useSkills", () => {
  it("discovers skills added after page load when opening the $ menu, not on each keystroke", async () => {
    const installed = {
      name: "simple-pr-review",
      description: "Review pull requests.",
      source: "workspace",
      enabled: true,
      available: true,
    };
    vi.mocked(fetchSkills).mockReset().mockResolvedValueOnce({ skills: [] })
      .mockResolvedValue({ skills: [installed] });
    const getToken = () => "tok";
    function Composer() {
      const skills = useSkills(getToken);
      return <ThreadComposer onSend={vi.fn()} skills={skills} />;
    }
    render(<Composer />);
    await act(async () => {});
    expect(fetchSkills).toHaveBeenCalledTimes(1);

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "/", selectionStart: 1 } });
    fireEvent.change(input, { target: { value: "@", selectionStart: 1 } });
    expect(fetchSkills).toHaveBeenCalledTimes(1);
    fireEvent.change(input, { target: { value: "$", selectionStart: 1 } });
    expect(await screen.findByRole("option", { name: /simple-pr-review/ })).toBeInTheDocument();
    expect(fetchSkills).toHaveBeenCalledTimes(2);

    fireEvent.change(input, { target: { value: "$simple", selectionStart: 7 } });
    await act(async () => {});
    expect(fetchSkills).toHaveBeenCalledTimes(2);
    fireEvent.keyDown(input, { key: "Tab" });
    expect(input).toHaveValue("$simple-pr-review ");

    // A later open must also refresh removals without remounting the page.
    vi.mocked(fetchSkills).mockResolvedValue({ skills: [] });
    fireEvent.change(input, { target: { value: "$", selectionStart: 1 } });
    await act(async () => {});
    expect(fetchSkills).toHaveBeenCalledTimes(3);
    expect(screen.queryByRole("listbox", { name: "Slash commands" })).not.toBeInTheDocument();
  });

  it("coalesces opens during an older fetch into one trailing refresh", async () => {
    let resolveSkills!: (value: Awaited<ReturnType<typeof fetchSkills>>) => void;
    const installed = {
      name: "simple-pr-review",
      description: "Review pull requests.",
      source: "workspace",
      available: true,
    };
    vi.mocked(fetchSkills).mockReset().mockImplementationOnce(
      () => new Promise((resolve) => {
        resolveSkills = resolve;
      }),
    ).mockResolvedValue({ skills: [installed] });
    const getToken = () => "tok";
    const { result, unmount } = renderHook(() => useSkills(getToken));

    act(() => {
      requestSkillsRefresh();
      requestSkillsRefresh();
    });
    expect(fetchSkills).toHaveBeenCalledTimes(1);
    await act(async () => {
      resolveSkills({ skills: [] });
    });
    // The old response was captured before installation; it cannot satisfy the new opens.
    expect(fetchSkills).toHaveBeenCalledTimes(2);
    expect(result.current).toEqual([installed]);

    unmount();
    requestSkillsRefresh();
    expect(fetchSkills).toHaveBeenCalledTimes(2);
  });

  it("keeps existing skills on refresh failure and retries on the next open", async () => {
    const installed = {
      name: "simple-pr-review",
      description: "Review pull requests.",
      source: "workspace",
      available: true,
    };
    vi.mocked(fetchSkills).mockReset()
      .mockResolvedValueOnce({ skills: [installed] })
      .mockRejectedValueOnce(new Error("Temporarily offline"))
      .mockResolvedValueOnce({ skills: [] });
    const getToken = () => "tok";
    const { result } = renderHook(() => useSkills(getToken));
    await act(async () => {});
    expect(result.current).toEqual([installed]);

    await act(async () => {
      requestSkillsRefresh();
    });
    expect(fetchSkills).toHaveBeenCalledTimes(2);
    expect(result.current).toEqual([installed]);

    await act(async () => {
      requestSkillsRefresh();
    });
    expect(fetchSkills).toHaveBeenCalledTimes(3);
    expect(result.current).toEqual([]);
  });

  it.each([false, true])("does not start a queued refresh after unmount (failure: %s)", async (fails) => {
    let settle!: () => void;
    vi.mocked(fetchSkills).mockReset().mockImplementationOnce(
      () => new Promise((resolve, reject) => {
        settle = () => fails ? reject(new Error("Offline")) : resolve({ skills: [] });
      }),
    );
    const getToken = () => "tok";
    const { unmount } = renderHook(() => useSkills(getToken));
    act(() => {
      requestSkillsRefresh();
    });
    unmount();

    await act(async () => {
      settle();
    });
    requestSkillsRefresh();
    expect(fetchSkills).toHaveBeenCalledTimes(1);
  });

  it("does not let an older request overwrite a newer skill event", async () => {
    let resolveSkills!: (value: Awaited<ReturnType<typeof fetchSkills>>) => void;
    vi.mocked(fetchSkills).mockReset().mockImplementationOnce(
      () => new Promise((resolve) => {
        resolveSkills = resolve;
      }),
    );
    const installed = {
      name: "react-testing",
      description: "Test React apps.",
      source: "workspace",
      available: true,
    };
    const getToken = () => "tok";
    const { result } = renderHook(() => useSkills(getToken));

    expect(fetchSkills).toHaveBeenCalledTimes(1);
    act(() => {
      window.dispatchEvent(new CustomEvent(SKILLS_CHANGED_EVENT, {
        detail: { skills: [installed] },
      }));
    });
    expect(result.current).toEqual([installed]);

    await act(async () => {
      resolveSkills({ skills: [] });
    });

    expect(result.current).toEqual([installed]);
  });
});

describe("SkillsMarketplace", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(fetchTrendingMarketplaceSkills).mockReset().mockResolvedValue({
      period: "mixed",
      provider: "all",
      install_supported: true,
      skills: [],
    });
    vi.mocked(searchMarketplaceSkills).mockReset().mockImplementation(
      async (_token, query) => ({
        query,
        provider: "all",
        install_supported: true,
        skills: [],
      }),
    );
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps loaded marketplace data stable when the auth token rotates", async () => {
    const { rerender } = render(marketplace("tok-old"));

    await act(async () => {});
    expect(fetchTrendingMarketplaceSkills).toHaveBeenCalledTimes(1);
    expect(fetchTrendingMarketplaceSkills).toHaveBeenCalledWith("tok-old");

    fireEvent.change(screen.getByRole("textbox", { name: "Search skills" }), {
      target: { value: "React" },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(searchMarketplaceSkills).toHaveBeenCalledTimes(1);
    expect(searchMarketplaceSkills).toHaveBeenLastCalledWith("tok-old", "React");

    rerender(marketplace("tok-new"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });

    expect(fetchTrendingMarketplaceSkills).toHaveBeenCalledTimes(1);
    expect(searchMarketplaceSkills).toHaveBeenCalledTimes(1);

    fireEvent.change(screen.getByRole("textbox", { name: "Search skills" }), {
      target: { value: "Vue" },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(searchMarketplaceSkills).toHaveBeenCalledTimes(2);
    expect(searchMarketplaceSkills).toHaveBeenLastCalledWith("tok-new", "Vue");
  });
});
