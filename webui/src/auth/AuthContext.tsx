import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { ApiError, authLogin, authLogout, authMe, type AuthUser } from "@/lib/api";

type AuthStatus = "loading" | "anon" | "authed";

interface AuthState {
  status: AuthStatus;
  user: AuthUser | null;
}

interface AuthApi extends AuthState {
  login: (email: string, password: string) => Promise<AuthUser>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthApi | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    status: "loading",
    user: null,
  });

  const refresh = useCallback(async () => {
    try {
      const user = await authMe();
      setState({ status: "authed", user });
    } catch (err) {
      // 401 (or any failure) keeps us anon. Other errors are silent — the
      // user lands on the login screen and any backend-side issue surfaces
      // there.
      if (!(err instanceof ApiError) || err.status !== 401) {
        // Surface unexpected failures to the console for operator triage.
        // eslint-disable-next-line no-console
        console.warn("auth/me failed:", err);
      }
      setState({ status: "anon", user: null });
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const login = useCallback(
    async (email: string, password: string) => {
      const user = await authLogin(email, password);
      setState({ status: "authed", user });
      return user;
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      await authLogout();
    } catch {
      // Even if the network call fails we still drop local state — the
      // cookie remains set on the browser; we'll naturally hit the login
      // screen on the next page load.
    }
    setState({ status: "anon", user: null });
  }, []);

  const value = useMemo<AuthApi>(
    () => ({ ...state, login, logout, refresh }),
    [state, login, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthApi {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return ctx;
}
