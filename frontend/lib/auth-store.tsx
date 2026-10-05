/* Client-side session storage. The JWT is the backend-minted bearer token;
   auth architecture is unchanged — this only persists the token the backend
   issued. Role checks derived from /auth/me are UX-only; backend re-validates. */

"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { UserRead } from "./types";
import { apiRequest } from "./api";

const TOKEN_KEY = "ledgerlens.token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* storage unavailable — session lasts for this tab only */
  }
}

export function clearToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

interface AuthState {
  user: UserRead | null;
  loading: boolean;
  error: string | null;
  role: "viewer" | "analyst" | "admin" | null;
  companyName: string | null;
  refresh: () => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState>({
  user: null,
  loading: true,
  error: null,
  role: null,
  companyName: null,
  refresh: async () => {},
  logout: () => {},
});

export function useAuth(): AuthState {
  return useContext(AuthContext);
}

function primaryRole(user: UserRead | null): AuthState["role"] {
  if (!user || user.companies.length === 0) return null;
  const rank = { viewer: 0, analyst: 1, admin: 2 } as const;
  let best: AuthState["role"] = "viewer";
  for (const m of user.companies) {
    if (rank[m.role] > rank[best as keyof typeof rank]) best = m.role;
  }
  return best;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const me = await apiRequest<UserRead>("/auth/me");
      setUser(me);
    } catch (e) {
      setUser(null);
      setError(e instanceof Error ? e.message : "Unable to load your profile.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const logout = useCallback(() => {
    clearToken();
    setUser(null);
  }, []);

  const value = useMemo<AuthState>(() => {
    const role = primaryRole(user);
    const companyName = user && user.companies.length > 0 ? user.companies[0].company_name : null;
    return { user, loading, error, role, companyName, refresh, logout };
  }, [user, loading, error, refresh, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/** Role helpers — UX gating only. Backend remains the security authority. */
export function canWrite(role: AuthState["role"]): boolean {
  return role === "analyst" || role === "admin";
}
export function isAdmin(role: AuthState["role"]): boolean {
  return role === "admin";
}
