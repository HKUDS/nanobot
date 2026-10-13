import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SkillsMarketplace } from "@/components/settings/SkillsMarketplace";
import { SkillsCatalogSettings } from "@/components/settings/SkillsCatalogSettings";
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
  it("shows loading, retries a failed first read, and preserves an empty catalog during refresh", async () => {
    let rejectInitial!: (error: Error) => void;
    let resolveRetry!: (value: Awaited<ReturnType<typeof fetchSkills>>) => void;
    let resolveRefresh!: (value: Awaited<ReturnType<typeof fetchSkills>>) => void;
    vi.mocked(fetchSkills).mockReset()
      .mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectInitial = reject; }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveRetry = resolve; }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveRefresh = resolve; }));
    const getToken = () => "tok";
    function Catalog() {
      const state = useSkills(getToken);
      return <SkillsCatalogSettings {...state} />;
    }
    render(<ClientProvider client={client} token="tok"><Catalog /></ClientProvider>);

    expect(screen.getByRole("status", { name: "Loading skills…" })).toHaveAttribute("aria-busy", "true");
    fireEvent.change(screen.getByRole("textbox", { name: "Search installed skills" }), {
      target: { value: "cron" },
    });
    await act(async () => { rejectInitial(new Error("Offline")); });
    expect(screen.getByRole("alert")).toHaveTextContent("Could not load skills.");
    expect(screen.queryByText("No skills are available.")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(screen.getByRole("status", { name: "Loading skills…" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await act(async () => { resolveRetry({ skills: [] }); });
    expect(screen.getByText("No skills are available.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All 0" })).toBeInTheDocument();

    act(() => { requestSkillsRefresh(); });
    expect(screen.getByText("No skills are available.")).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading skills…" })).not.toBeInTheDocument();
    await act(async () => {
      resolveRefresh({ skills: [{
        name: "weather", description: "Get the weather.", source: "builtin", available: true,
      }] });
    });
    expect(screen.getByText("No matching skills.")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Search installed skills" }), {
      target: { value: "" },
    });
    expect(screen.getByRole("button", { name: "Open details for weather" })).toBeInTheDocument();
    expect(fetchSkills).toHaveBeenCalledTimes(3);
  });

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
      const { skills } = useSkills(getToken);
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
    expect(result.current.skills).toEqual([installed]);

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
    expect(result.current.skills).toEqual([installed]);

    await act(async () => {
      requestSkillsRefresh();
    });
    expect(fetchSkills).toHaveBeenCalledTimes(2);
    expect(result.current).toEqual({ skills: [installed], loading: false, error: false });

    await act(async () => {
      requestSkillsRefresh();
    });
    expect(fetchSkills).toHaveBeenCalledTimes(3);
    expect(result.current).toEqual({ skills: [], loading: false, error: false });
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

  it.each([false, true])("does not let an older request overwrite a newer skill event (failure: %s)", async (fails) => {
    let settle!: () => void;
    vi.mocked(fetchSkills).mockReset().mockImplementationOnce(
      () => new Promise((resolve, reject) => {
        settle = () => fails ? reject(new Error("Offline")) : resolve({ skills: [] });
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
    expect(result.current).toEqual({ skills: [installed], loading: false, error: false });

    await act(async () => {
      settle();
    });

    expect(result.current).toEqual({ skills: [installed], loading: false, error: false });
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

  it("shows discovery skeletons while trending or the first search is pending and keeps loaded search results", async () => {
    const skill = {
      id: "skillhub:react-testing", skill_id: "react-testing", name: "React Testing",
      source: "react-testing", provider: "skillhub" as const, installs: 42,
      url: "https://skillhub.cn/skills/react-testing", installed: false, install_supported: true,
      metric: "installs_total" as const, rank: 1,
    };
    let resolveTrending!: (value: Awaited<ReturnType<typeof fetchTrendingMarketplaceSkills>>) => void;
    let resolveSearch!: (value: Awaited<ReturnType<typeof searchMarketplaceSkills>>) => void;
    let resolveNextSearch!: (value: Awaited<ReturnType<typeof searchMarketplaceSkills>>) => void;
    vi.mocked(fetchTrendingMarketplaceSkills).mockImplementationOnce(
      () => new Promise((resolve) => { resolveTrending = resolve; }),
    );
    vi.mocked(searchMarketplaceSkills)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveSearch = resolve; }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveNextSearch = resolve; }));
    render(marketplace("tok"));

    expect(screen.getByRole("status", { name: "Loading skills…" })).toHaveAttribute("aria-busy", "true");
    await act(async () => {
      resolveTrending({ period: "mixed", provider: "all", install_supported: true, skills: [skill] });
    });
    expect(screen.getByRole("button", { name: "Install React Testing" })).toBeInTheDocument();

    fireEvent.change(screen.getByRole("textbox", { name: "Search skills" }), {
      target: { value: "React" },
    });
    expect(screen.getByRole("status", { name: "Loading skills…" })).toHaveAttribute("aria-busy", "true");
    expect(searchMarketplaceSkills).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    expect(searchMarketplaceSkills).toHaveBeenCalledWith("tok", "React");
    expect(screen.getByRole("status", { name: "Loading skills…" })).toBeInTheDocument();
    await act(async () => {
      resolveSearch({ query: "React", provider: "all", install_supported: true, skills: [skill] });
    });

    fireEvent.change(screen.getByRole("textbox", { name: "Search skills" }), {
      target: { value: "Vue" },
    });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    expect(screen.getByRole("button", { name: "Install React Testing" })).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading skills…" })).not.toBeInTheDocument();
    await act(async () => {
      resolveNextSearch({ query: "Vue", provider: "all", install_supported: true, skills: [] });
    });
    expect(screen.getByText("No skills found for “Vue”.")).toBeInTheDocument();
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
