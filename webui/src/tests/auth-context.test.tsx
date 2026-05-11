import { describe, it, expect, beforeEach, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { AuthProvider, useAuth } from "@/auth/AuthContext";

function Probe() {
  const auth = useAuth();
  return (
    <div>
      <span data-testid="status">{auth.status}</span>
      <span data-testid="email">{auth.user?.email ?? "<none>"}</span>
      <button onClick={() => void auth.login("a@b.com", "pwd-long-enough-1234")}>
        login
      </button>
      <button onClick={() => void auth.logout()}>logout</button>
    </div>
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("AuthContext", () => {
  it("starts in loading then anon on 401 from /auth/me", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ error: "unauthenticated" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    expect(screen.getByTestId("status").textContent).toBe("loading");
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("anon"));
  });

  it("transitions to authed when /auth/me returns a user", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          user: { id: "01ABC", email: "a@b.com", display_name: null, role: "user" },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authed"));
    expect(screen.getByTestId("email").textContent).toBe("a@b.com");
  });

  it("login() flips status to authed and exposes the returned user", async () => {
    // First call (/auth/me) is 401, second call (/auth/login) is 200.
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response("{}", { status: 401, headers: { "Content-Type": "application/json" } }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            user: { id: "01ABC", email: "c@d.com", display_name: null, role: "user" },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("anon"));
    await act(async () => {
      screen.getByText("login").click();
    });
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authed"));
    expect(screen.getByTestId("email").textContent).toBe("c@d.com");
    // Confirm credentials propagated.
    const loginCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/auth/login"));
    expect(loginCall?.[1]).toMatchObject({ credentials: "include" });
  });

  it("logout() drops to anon even if the network call fails", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            user: { id: "01ABC", email: "a@b.com", display_name: null, role: "user" },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockRejectedValueOnce(new Error("offline"));
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authed"));
    await act(async () => {
      screen.getByText("logout").click();
    });
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("anon"));
  });
});
