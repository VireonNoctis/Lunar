import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { api, API_BASE, type Me } from "../api/client";

const DEMO_USER: Me = {
  id: "1419744000977403994",
  username: "Demo Admin",
  roles: ["owner", "admin"],
};

interface AuthContextValue {
  user: Me | null;
  isAdmin: boolean;
  isOwner: boolean;
  loading: boolean;
  loginDemo: () => void;
  loginDiscord: () => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const DEMO_KEY = "lunar_demo_admin";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    (async () => {
      if (localStorage.getItem(DEMO_KEY) === "1") {
        setUser(DEMO_USER);
        setLoading(false);
        return;
      }
      const me = await api.fetchMe();
      if (active) {
        setUser(me);
        setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isAdmin: user?.roles?.includes("admin") || user?.roles?.includes("owner") || user?.id === DEMO_USER.id,
      isOwner: user?.roles?.includes("owner") || user?.id === DEMO_USER.id,
      loading,
      loginDemo: () => {
        localStorage.setItem(DEMO_KEY, "1");
        setUser(DEMO_USER);
      },
      loginDiscord: () => {
        const base = API_BASE || window.location.origin;
        window.location.href = `${base}/auth/discord`;
      },
      logout: () => {
        localStorage.removeItem(DEMO_KEY);
        setUser(null);
      },
    }),
    [user, loading],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-lunar-500 border-t-transparent" />
      </div>
    );
  }

  if (!user) {
    const returnTo = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/auth?returnTo=${returnTo}`} replace />;
  }

  return <>{children}</>;
}