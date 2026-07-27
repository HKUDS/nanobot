import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ExtensionsView } from "@/components/ExtensionsView";
import type { NanobotClient } from "@/lib/nanobot-client";
import type { ExtensionInfo } from "@/lib/types";
import { ClientProvider } from "@/providers/ClientProvider";

function response(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => "application/json" },
    json: async () => body,
    text: async () => "",
  } as unknown as Response;
}

function extension(overrides: Partial<ExtensionInfo> = {}): ExtensionInfo {
  return {
    id: "sample.tools",
    name: "Sample Tools",
    version: "1.0.0",
    description: "Adds a small set of native tools.",
    homepage: "",
    license: "MIT",
    location: "/tmp/extensions/sample.tools",
    enabled: true,
    trusted: false,
    active: false,
    requested_permissions: ["network"],
    granted_permissions: [],
    source: "git",
    source_ref: "https://example.com/sample-tools.git",
    integrity: "sha256:example",
    installed_at: "2026-07-26T00:00:00Z",
    dependencies: [],
    permissions: [{ name: "network", reason: "Fetch selected URLs." }],
    ...overrides,
  };
}

function renderView() {
  return render(
    <ClientProvider client={{} as NanobotClient} token="tok">
      <ExtensionsView onBackToChat={() => {}} />
    </ClientProvider>,
  );
}

describe("ExtensionsView", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("requires permission grants before trust", async () => {
    let current = extension();
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (url === "/api/extensions/permissions") {
        current = extension({ granted_permissions: ["network"] });
      }
      if (url === "/api/extensions/trust") {
        current = extension({
          granted_permissions: ["network"],
          trusted: true,
          active: true,
        });
      }
      return url === "/api/extensions"
        ? response({ extensions: [current], diagnostics: [] })
        : response({});
    }));

    renderView();
    fireEvent.click(await screen.findByRole("button", { name: /Sample Tools/ }));

    const trust = screen.getByRole("button", { name: "Trust" });
    expect(trust).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Grant permissions" }));
    await waitFor(() => expect(trust).toBeEnabled());
    fireEvent.click(trust);

    await waitFor(() =>
      expect(requests.some(({ url }) => url === "/api/extensions/trust")).toBe(true),
    );
  });

  it("installs a Git package without granting trust", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      return url === "/api/extensions"
        ? response({ extensions: [], diagnostics: [] })
        : response({});
    }));

    renderView();
    fireEvent.change(screen.getByPlaceholderText("https://github.com/acme/extension.git"), {
      target: { value: "https://example.com/sample-tools.git" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Install" }));

    await waitFor(() =>
      expect(requests.some(({ url }) => url === "/api/extensions/install")).toBe(true),
    );
    const install = requests.find(({ url }) => url === "/api/extensions/install");
    const encoded = new Headers(install?.init?.headers).get(
      "X-Nanobot-Extension-Values",
    );
    expect(JSON.parse(decodeURIComponent(encoded ?? ""))).toEqual({
      source: "https://example.com/sample-tools.git",
      kind: "git",
    });
  });
});
