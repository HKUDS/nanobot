import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HostCompatibilityDialog } from "@/components/remote/HostCompatibilityDialog";
import i18n from "@/i18n";
import type { RemoteProfile } from "@/lib/remote-instances";

afterEach(async () => {
  cleanup();
  vi.restoreAllMocks();
  await i18n.changeLanguage("en");
});

describe("host compatibility facts", () => {
  it.each(["en", "zh-CN", "zh-TW", "es", "fr", "pt-BR", "id", "ja", "ko", "vi"])(
    "distinguishes update precautions from the external guide (%s)", async (language) => {
      await i18n.changeLanguage(language);
      const profile: RemoteProfile = {
        id: "host", name: "Team server", host: "ubuntu@example.test", port: 22,
        config_path: "", ssh_config: "", identity_file: "", runtime_user: "", connected: false,
        compatibility: { status: "update_host", client_version: "0.3.5", host_version: "0.3.4" },
      };
      render(<HostCompatibilityDialog profile={profile} onClose={vi.fn()} />);
      const dialog = screen.getByRole("dialog");
      const guide = i18n.t("remote.compatibility.guide");
      const preparation = i18n.t("remote.compatibility.preparation");
      expect(preparation).not.toBe("remote.compatibility.preparation");
      expect(preparation).not.toBe(guide);
      expect(within(dialog).getAllByText(guide)).toHaveLength(1);
      expect(within(dialog).getByRole("link", { name: guide })).toBeVisible();
      expect(dialog.querySelector("summary")).toHaveTextContent(preparation);
      expect(dialog.querySelector("details")).toHaveTextContent(i18n.t("remote.compatibility.serverUpdateHint"));
    },
  );

  it("keeps the last host report during exit, but never reuses it for a new host", async () => {
    const getStyle = window.getComputedStyle.bind(window);
    vi.spyOn(window, "getComputedStyle").mockImplementation((node) => {
      const style = getStyle(node);
      if (node.getAttribute("role") !== "dialog") return style;
      return new Proxy(style, { get(target, property) {
        if (property === "animationName") return node.getAttribute("data-state") === "closed" ? "exit" : "enter";
        const value = Reflect.get(target, property, target);
        return typeof value === "function" ? value.bind(target) : value;
      } });
    });
    const profile: RemoteProfile = {
      id: "host", name: "Team server", host: "ubuntu@example.test", port: 22,
      config_path: "", ssh_config: "", identity_file: "", runtime_user: "", connected: true,
      compatibility: { status: "compatible", client_version: "0.3.5", host_version: "0.3.5" },
    };
    const onClose = vi.fn();
    const { rerender } = render(<HostCompatibilityDialog profile={profile} onClose={onClose} />);
    const dialog = screen.getByRole("dialog");
    rerender(<HostCompatibilityDialog profile={undefined} onClose={onClose} />);
    expect(dialog).toHaveAttribute("data-state", "closed");
    expect(dialog).toHaveTextContent("Team server");
    expect(dialog).toHaveTextContent("No update needed to connect.");
    expect(dialog).not.toHaveTextContent("Not checked yet");
    const exit = new Event("animationend", { bubbles: true });
    Object.defineProperty(exit, "animationName", { value: "exit" });
    fireEvent(dialog, exit);
    await waitFor(() => expect(dialog).not.toBeInTheDocument());
    rerender(<HostCompatibilityDialog profile={{ ...profile, id: "another", name: "Another server", compatibility: undefined }} onClose={onClose} />);
    expect(screen.getByRole("dialog")).toHaveTextContent("Another server");
    expect(screen.getByRole("status")).toHaveTextContent("Not checked yet");
  });
  it.each(["en", "zh-CN", "zh-TW", "es", "fr", "pt-BR", "id", "ja", "ko", "vi"])(
    "keeps full version values and their labels in a compact read-only group (%s)",
    async (language) => {
      await i18n.changeLanguage(language);
      const version = "0.3.5-dev+long-build-identifier-0123456789abcdef";
      const profile: RemoteProfile = {
        id: "host", name: "Team server", host: "ubuntu@example.test",
        port: 22, config_path: "", ssh_config: "", identity_file: "", runtime_user: "",
        connected: true,
        compatibility: { status: "compatible", client_version: version, host_version: version },
      };
      render(<HostCompatibilityDialog profile={profile} onClose={vi.fn()} />);
      const dialog = screen.getByRole("dialog");
      const terms = within(dialog).getAllByRole("term");
      expect(terms.map((term) => term.textContent)).toEqual([
        i18n.t("remote.compatibility.client"), i18n.t("remote.compatibility.host"),
      ]);
      const values = within(dialog).getAllByRole("definition");
      expect(values.map((value) => value.textContent)).toEqual([version, version]);
      // Read-only facts must not inherit the settings controls' 60px row floor.
      expect(dialog.querySelector(".settings-list-row")).toBeNull();
      expect(dialog.querySelector(".break-all, .truncate")).toBeNull();
      expect(within(dialog).getByRole("status")).toHaveTextContent(i18n.t("remote.compatibility.compatibleHint"));
      expect(within(dialog).queryByRole("link")).not.toBeInTheDocument();
    },
  );
});
