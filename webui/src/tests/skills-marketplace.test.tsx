import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SkillsMarketplace } from "@/components/settings/SkillsMarketplace";
import {
  fetchMarketplaceSkillTrends,
  fetchSkills,
  fetchTrendingMarketplaceSkills,
  searchMarketplaceSkills,
} from "@/lib/api";
import type { NanobotClient } from "@/lib/nanobot-client";
import { SKILLS_CHANGED_EVENT } from "@/lib/skill-events";
import { ClientProvider } from "@/providers/ClientProvider";
import { useSkills } from "@/hooks/useSkills";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    fetchMarketplaceSkillTrends: vi.fn(),
    fetchSkills: vi.fn(),
    fetchTrendingMarketplaceSkills: vi.fn(),
    searchMarketplaceSkills: vi.fn(),
  };
});

const client = {} as NanobotClient;

function marketplace(
  token: string,
  installedSkills: ComponentProps<typeof SkillsMarketplace>["installedSkills"] = [],
) {
  return (
    <ClientProvider client={client} token={token}>
      <SkillsMarketplace
        installedSkills={installedSkills}
        installing=""
        onInstallingChange={() => {}}
      />
    </ClientProvider>
  );
}

describe("useSkills", () => {
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
    vi.mocked(fetchMarketplaceSkillTrends).mockReset().mockResolvedValue({
      trends: { "acme/agent-skills/github": [] },
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

  it("allows a marketplace skill to shadow a built-in skill with the same name", async () => {
    vi.mocked(fetchTrendingMarketplaceSkills).mockResolvedValueOnce({
      period: "mixed",
      provider: "all",
      install_supported: true,
      skills: [
        {
          id: "acme/agent-skills/github",
          skill_id: "github",
          name: "GitHub",
          source: "acme/agent-skills",
          provider: "skills_sh",
          installs: 42,
          url: "https://skills.sh/acme/agent-skills/github",
          installed: false,
          install_supported: true,
          metric: "installs_total",
        },
      ],
    });

    render(marketplace("tok", [
      {
        name: "github",
        description: "Bundled GitHub skill.",
        source: "builtin",
        available: true,
      },
    ]));

    await act(async () => {});

    const install = screen.getByRole("button", { name: "Install GitHub" });
    expect(install).toBeEnabled();
    fireEvent.click(install);
    expect(
      screen.getByText(
        "This workspace copy will override the existing built-in or plugin skill until you delete it.",
      ),
    ).toBeInTheDocument();
  });

  it("keeps a marketplace skill disabled when it is installed in the workspace", async () => {
    vi.mocked(fetchTrendingMarketplaceSkills).mockResolvedValueOnce({
      period: "mixed",
      provider: "all",
      install_supported: true,
      skills: [
        {
          id: "acme/agent-skills/github",
          skill_id: "github",
          name: "GitHub",
          source: "acme/agent-skills",
          provider: "skills_sh",
          installs: 42,
          url: "https://skills.sh/acme/agent-skills/github",
          installed: false,
          install_supported: true,
          metric: "installs_total",
        },
      ],
    });

    render(marketplace("tok", [
      {
        name: "github",
        description: "Workspace GitHub skill.",
        source: "workspace",
        available: true,
      },
    ]));

    await act(async () => {});

    expect(screen.getByRole("button", { name: "Installed GitHub" })).toBeDisabled();
  });
});
