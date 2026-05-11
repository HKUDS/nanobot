import { useState, type ReactNode } from "react";
import { useAuth } from "@/auth/AuthContext";
import { LoginPage } from "@/auth/LoginPage";
import { SignupPage } from "@/auth/SignupPage";

export function AuthGate({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const [mode, setMode] = useState<"login" | "signup">("login");

  if (status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="text-sm text-muted-foreground">Loading…</div>
      </div>
    );
  }

  if (status === "anon") {
    return mode === "login" ? (
      <LoginPage onSwitchToSignup={() => setMode("signup")} />
    ) : (
      <SignupPage onSwitchToLogin={() => setMode("login")} />
    );
  }

  return <>{children}</>;
}
