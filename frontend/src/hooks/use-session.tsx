"use client";

/**
 * Session context and permission helpers.
 *
 * One provider holds the signed-in principal; `usePermission` answers "may
 * this user be *offered* this action". It is UX only — the server decides
 * (see `lib/domain/permissions.ts`).
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { authApi, errorMessage } from "@/lib/api";
import {
  canAccessRoute,
  canActInGodown,
  canApprovePoValue,
  canSeeGodown,
  hasAll,
  hasAny,
  hasPermission,
  isOwner,
  visibleGodownIds,
} from "@/lib/domain/permissions";
import type { Id, ImpersonationSession, PermissionCode, SessionUser } from "@/types";
import { useApiQuery } from "./use-api";

interface SessionContextValue {
  user: SessionUser | null;
  impersonation: ImpersonationSession | null;
  isLoading: boolean;
  signIn: (identifier: string, password: string) => Promise<SessionUser>;
  signOut: () => Promise<void>;
  refresh: () => void;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [impersonation, setImpersonation] = useState<ImpersonationSession | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const load = useCallback(async () => {
    // Paint the cached principal immediately (no flash of "signed out" on a
    // reload while `/auth/me` is in flight), then validate/refresh it for
    // real — an expired or revoked token resolves to `null` here.
    const cached = authApi.currentSession();
    if (cached) setUser(cached);
    setImpersonation(authApi.currentImpersonation());
    const fresh = await authApi.getSession();
    setUser(fresh);
    setIsLoading(false);
  }, []);

  // Resolved in an effect, never during render: the session lives in
  // localStorage, and reading it while rendering causes a hydration mismatch.
  useEffect(() => {
    void load();
  }, [load]);

  const signIn = useCallback(async (identifier: string, password: string) => {
    const next = await authApi.signIn(identifier, password);
    setUser(next);
    setImpersonation(authApi.currentImpersonation());
    setIsLoading(false);
    return next;
  }, []);

  const signOut = useCallback(async () => {
    await authApi.signOut();
    setUser(null);
    setImpersonation(null);
  }, []);

  const value = useMemo(
    () => ({ user, impersonation, isLoading, signIn, signOut, refresh: load }),
    [user, impersonation, isLoading, signIn, signOut, load],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const context = useContext(SessionContext);
  if (!context) throw new Error("useSession must be used inside <SessionProvider>.");
  return context;
}

/* ---------------------------------------------------------- Permissions */

export function usePermissions() {
  const { user } = useSession();

  return useMemo(
    () => ({
      user,
      can: (permission: PermissionCode) => hasPermission(user, permission),
      canAny: (permissions: PermissionCode[]) => hasAny(user, permissions),
      canAll: (permissions: PermissionCode[]) => hasAll(user, permissions),
      canSeeGodown: (godownId: Id | null | undefined) => canSeeGodown(user, godownId),
      canActInGodown: (godownId: Id | null | undefined) => canActInGodown(user, godownId),
      canAccessRoute: (pathname: string) => canAccessRoute(user, pathname),
      canApprovePo: (total: number, threshold: number) => canApprovePoValue(user, total, threshold),
      visibleGodowns: (ids: Id[]) => visibleGodownIds(user, ids),
      isPlatformAdmin: !!user?.isPlatformAdmin,
      isOwner: isOwner(user),
    }),
    [user],
  );
}

/**
 * True only once the signed-in user is *known* to belong to a company.
 *
 * Gate tenant-scoped queries on this, not on `!user?.isPlatformAdmin`: while
 * the session is still loading `user` is null, that expression is `true`, and
 * the queries fire (and 403) for a platform admin before the session resolves.
 */
export function useIsTenantUser(): boolean {
  const { user } = useSession();
  return !!user && !user.isPlatformAdmin;
}

/* ------------------------------------ Multi-company login (BR-AUTH-13) */

/**
 * The companies this login can switch between. Keyed on the active company
 * so it refetches after a switch. Skipped for platform admins (no company)
 * and while impersonating (the server would only return the one company
 * being visited anyway).
 */
export function useMyCompanies() {
  const { user, impersonation } = useSession();
  const enabled = !!user && !user.isPlatformAdmin && !impersonation;
  return useApiQuery(["my-companies", user?.id, user?.companyId], () => authApi.listMyCompanies(), {
    enabled,
  });
}

/** Switch company, then reload the app on the dashboard. A full reload is
 * deliberate: every cached list and detail on screen belongs to the
 * company being left, and the cheapest way to guarantee none of it lingers
 * is to start the page over with the new token. */
export function useSwitchCompany() {
  const [pendingId, setPendingId] = useState<Id | null>(null);
  const [error, setError] = useState<string | null>(null);

  const switchTo = useCallback(async (companyId: Id) => {
    setPendingId(companyId);
    setError(null);
    try {
      await authApi.switchCompany(companyId);
      window.location.assign("/dashboard");
    } catch (e) {
      setError(errorMessage(e, "Could not switch company."));
      setPendingId(null);
    }
  }, []);

  return { switchTo, pendingId, error };
}

/** Convenience for a single check. */
export function usePermission(permission: PermissionCode): boolean {
  const { user } = useSession();
  return hasPermission(user, permission);
}
