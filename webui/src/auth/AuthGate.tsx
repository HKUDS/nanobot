import type { ReactNode } from "react";
import { useAuth } from "@/auth/AuthContext";
import { LoginPage } from "@/auth/LoginPage";

export function AuthGate({ children }: { children: ReactNode }) {
  const { status } = useAuth();

  if (status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="text-sm text-muted-foreground">Loading…</div>
      </div>
    );
  }

  if (status === "anon") {
    return <LoginPage />;
  }

  return <>{children}</>;
}
