import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { AdminUsersPage } from "@/admin/AdminUsersPage";
import { AuthProvider } from "@/auth/AuthContext";

const adminUser = {
  user: { id: "01AAA", email: "admin@x", display_name: null, role: "admin" },
};
const userList = (rows: object[]) => ({ users: rows });
const noop = () => {};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

interface RouteMap {
  "/auth/me"?: Response;
  "/admin/users"?: Response[];
  /** Sequential responses for any URL containing this substring. */
  match?: { pattern: string; responses: Response[] }[];
}

function mockRoutes(routes: RouteMap) {
  const adminUsersQueue = [...(routes["/admin/users"] ?? [])];
  const matchQueues = (routes.match ?? []).map((m) => ({ ...m, queue: [...m.responses] }));
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("/auth/me")) {
      return routes["/auth/me"]?.clone() ?? new Response("{}", { status: 401 });
    }
    for (const m of matchQueues) {
      if (url.includes(m.pattern) && m.queue.length > 0) {
        return m.queue.shift()!;
      }
    }
    if (url.endsWith("/admin/users") && adminUsersQueue.length > 0) {
      return adminUsersQueue.shift()!;
    }
    return new Response("{}", { status: 500 });
  });
}

beforeEach(() => vi.restoreAllMocks());

const ROW_ADMIN = { id: "01AAA", email: "admin@x", role: "admin" as const, display_name: null, created_at: 1, last_login_at: 2, disabled: false };
const ROW_ALICE = { id: "01BBB", email: "alice@x", role: "user" as const, display_name: "Alice", created_at: 3, last_login_at: null, disabled: false };

describe("AdminUsersPage", () => {
  it("renders the user list returned by /admin/users", async () => {
    mockRoutes({
      "/auth/me": jsonResponse(adminUser),
      "/admin/users": [jsonResponse(userList([ROW_ADMIN, ROW_ALICE]))],
    });
    render(
      <AuthProvider>
        <AdminUsersPage onBack={noop} />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("admin-users-table")).toBeInTheDocument());
    expect(screen.getByTestId("row-alice@x").textContent).toContain("alice@x");
    expect(screen.getByTestId("row-alice@x").textContent).toContain("user");
  });

  it("surfaces API errors", async () => {
    mockRoutes({
      "/auth/me": jsonResponse(adminUser),
      "/admin/users": [jsonResponse({ error: "forbidden" }, 403)],
    });
    render(
      <AuthProvider>
        <AdminUsersPage onBack={noop} />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("forbidden"));
  });

  it("promote click fires POST /admin/users/:id/role and refreshes", async () => {
    const fetchMock = mockRoutes({
      "/auth/me": jsonResponse(adminUser),
      "/admin/users": [
        jsonResponse(userList([ROW_ADMIN, ROW_ALICE])),
        jsonResponse(userList([ROW_ADMIN, { ...ROW_ALICE, role: "admin" }])),
      ],
      match: [
        {
          pattern: "/admin/users/01BBB/role",
          responses: [jsonResponse({ user: { ...ROW_ALICE, role: "admin" } })],
        },
      ],
    });
    render(
      <AuthProvider>
        <AdminUsersPage onBack={noop} />
      </AuthProvider>,
    );
    const row = await screen.findByTestId("row-alice@x");
    await act(async () => {
      row.querySelector<HTMLButtonElement>("button:nth-of-type(1)")?.click();
    });
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).includes("/admin/users/01BBB/role"));
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ role: "admin" });
    });
  });

  it("delete shows a confirm dialog before firing DELETE", async () => {
    const fetchMock = mockRoutes({
      "/auth/me": jsonResponse(adminUser),
      "/admin/users": [
        jsonResponse(userList([ROW_ADMIN, ROW_ALICE])),
        jsonResponse(userList([ROW_ADMIN])),
      ],
      match: [
        { pattern: "/admin/users/01BBB", responses: [jsonResponse({ ok: true })] },
      ],
    });
    render(
      <AuthProvider>
        <AdminUsersPage onBack={noop} />
      </AuthProvider>,
    );
    const row = await screen.findByTestId("row-alice@x");
    await act(async () => {
      const buttons = row.querySelectorAll<HTMLButtonElement>("button");
      buttons[buttons.length - 1].click();
    });
    expect(screen.getByRole("dialog").textContent).toContain("Delete user?");
    await act(async () => {
      const dialogButtons = screen.getByRole("dialog").querySelectorAll<HTMLButtonElement>("button");
      dialogButtons[dialogButtons.length - 1].click();
    });
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).includes("/admin/users/01BBB") &&
          (init as { method?: string } | undefined)?.method === "DELETE",
      );
      expect(call).toBeTruthy();
    });
  });

  it("disables self-row actions to prevent operator lockout", async () => {
    mockRoutes({
      "/auth/me": jsonResponse(adminUser),
      "/admin/users": [jsonResponse(userList([ROW_ADMIN]))],
    });
    render(
      <AuthProvider>
        <AdminUsersPage onBack={noop} />
      </AuthProvider>,
    );
    const row = await screen.findByTestId("row-admin@x");
    const actionButtons = row.querySelectorAll<HTMLButtonElement>("button");
    for (const btn of actionButtons) {
      expect(btn.disabled).toBe(true);
    }
  });
});
