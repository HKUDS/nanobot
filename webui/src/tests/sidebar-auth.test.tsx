import { describe, it, expect, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { AuthProvider } from "@/auth/AuthContext";

// ConnectionBadge depends on the WS client provider which isn't relevant
// here; stub it so we can render the Sidebar in isolation.
vi.mock("@/components/ConnectionBadge", () => ({
  ConnectionBadge: () => null,
}));

import { Sidebar } from "@/components/Sidebar";

const noop = () => {};

function renderWithAuth(meResponse: Response) {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(meResponse);
  return render(
    <AuthProvider>
      <Sidebar
        sessions={[]}
        activeKey={null}
        loading={false}
        onNewChat={noop}
        onSelect={noop}
        onRequestDelete={noop}
        onOpenSettings={noop}
        onCollapse={noop}
      />
    </AuthProvider>,
  );
}

describe("Sidebar — auth footer", () => {
  it("shows display_name when authed", async () => {
    renderWithAuth(
      new Response(
        JSON.stringify({
          user: { id: "01ABC", email: "a@b.com", display_name: "Alice", role: "user" },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    // Wait one microtask for /auth/me to resolve.
    await act(async () => {});
    const row = await screen.findByTestId("sidebar-user");
    expect(row.textContent).toContain("Alice");
    expect(screen.getByRole("button", { name: /sign out/i })).toBeInTheDocument();
  });

  it("falls back to email when display_name is null", async () => {
    renderWithAuth(
      new Response(
        JSON.stringify({
          user: { id: "01ABC", email: "fallback@b.com", display_name: null, role: "user" },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    await act(async () => {});
    const row = await screen.findByTestId("sidebar-user");
    expect(row.textContent).toContain("fallback@b.com");
  });

  it("hides the user row when /auth/me returns 401", async () => {
    renderWithAuth(
      new Response("{}", { status: 401, headers: { "Content-Type": "application/json" } }),
    );
    await act(async () => {});
    expect(screen.queryByTestId("sidebar-user")).toBeNull();
  });
});
