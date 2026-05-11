import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  ApiError,
  adminDeleteUser,
  adminListUsers,
  adminSetDisabled,
  adminSetRole,
  type AdminUserRow,
} from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";

interface AdminUsersPageProps {
  onBack: () => void;
}

function formatTimestamp(epoch: number | null): string {
  if (!epoch) return "—";
  return new Date(epoch * 1000).toLocaleString();
}

export function AdminUsersPage({ onBack }: AdminUsersPageProps) {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<AdminUserRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<AdminUserRow | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const rows = await adminListUsers();
      setUsers(rows);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load users.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const wrap = async (id: string, action: () => Promise<unknown>) => {
    setPendingId(id);
    setError(null);
    try {
      await action();
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed.");
    } finally {
      setPendingId(null);
    }
  };

  const onTogglePromote = (u: AdminUserRow) =>
    wrap(u.id, () => adminSetRole(u.id, u.role === "admin" ? "user" : "admin"));
  const onToggleDisabled = (u: AdminUserRow) =>
    wrap(u.id, () => adminSetDisabled(u.id, !u.disabled));
  const onConfirmDelete = (u: AdminUserRow) => setConfirmDelete(u);
  const onCancelDelete = () => setConfirmDelete(null);
  const onExecuteDelete = () => {
    if (!confirmDelete) return;
    const target = confirmDelete;
    setConfirmDelete(null);
    return wrap(target.id, () => adminDeleteUser(target.id));
  };

  return (
    <div className="flex h-full w-full flex-col bg-background p-6">
      <header className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Users</h1>
          <p className="text-sm text-muted-foreground">
            Manage WebUI accounts. You are signed in as {currentUser?.email}.
          </p>
        </div>
        <Button variant="ghost" onClick={onBack}>
          Back to chat
        </Button>
      </header>

      {error && (
        <div
          role="alert"
          className="mb-4 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {error}
        </div>
      )}

      {users === null ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : users.length === 0 ? (
        <p className="text-sm text-muted-foreground">No users yet.</p>
      ) : (
        <div className="overflow-auto rounded-md border border-border" data-testid="admin-users-table">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-3 py-2">Email</th>
                <th className="px-3 py-2">Role</th>
                <th className="px-3 py-2">Created</th>
                <th className="px-3 py-2">Last login</th>
                <th className="px-3 py-2">Disabled</th>
                <th className="px-3 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => {
                const isSelf = currentUser?.id === u.id;
                const busy = pendingId === u.id;
                return (
                  <tr key={u.id} className="border-t border-border" data-testid={`row-${u.email}`}>
                    <td className="px-3 py-2 font-medium">
                      {u.display_name ? `${u.display_name} (${u.email})` : u.email}
                    </td>
                    <td className="px-3 py-2 capitalize">{u.role}</td>
                    <td className="px-3 py-2 text-muted-foreground">
                      {formatTimestamp(u.created_at)}
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">
                      {formatTimestamp(u.last_login_at)}
                    </td>
                    <td className="px-3 py-2">{u.disabled ? "yes" : "no"}</td>
                    <td className="space-x-2 px-3 py-2 text-right">
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        disabled={busy || isSelf}
                        onClick={() => onTogglePromote(u)}
                      >
                        {u.role === "admin" ? "Demote" : "Promote"}
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        disabled={busy || isSelf}
                        onClick={() => onToggleDisabled(u)}
                      >
                        {u.disabled ? "Enable" : "Disable"}
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        disabled={busy || isSelf}
                        onClick={() => onConfirmDelete(u)}
                      >
                        Delete
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {confirmDelete && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
        >
          <div className="w-full max-w-sm rounded-lg border border-border bg-card p-5 shadow-lg">
            <h2 className="text-lg font-semibold">Delete user?</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              This will remove <strong>{confirmDelete.email}</strong> and revoke their sessions.
              The user's filesystem data is preserved and must be removed manually if needed.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="ghost" onClick={onCancelDelete}>
                Cancel
              </Button>
              <Button variant="destructive" onClick={onExecuteDelete}>
                Delete
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
