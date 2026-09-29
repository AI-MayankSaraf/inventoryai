"use client";

/**
 * Session context for the Supplier Portal.
 *
 * A parallel, deliberately separate context from `use-session.tsx`'s
 * `SessionProvider` — that one holds a tenant user (one `companyId`); this
 * one holds a supplier contact who can see *several* companies and picks
 * which one to work in. Mixing the two into one context would mean every
 * consumer of the tenant session has to account for a principal shape that
 * doesn't apply to it.
 *
 * Backed by `/supplier-portal/*` (see `lib/api/supplier-portal.api.ts`). The
 * chosen company is remembered per browser; the list of companies is always
 * re-read from the server, so access a company revokes disappears at once.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import * as portalApi from "@/lib/api/supplier-portal.api";
import { errorMessage } from "@/lib/api";
import type {
  SupplierPortalCompany,
  SupplierPortalCompanyActivity,
  SupplierPortalPrincipal,
} from "@/types/supplier-portal";

const COMPANY_KEY = "inventoryai.supplier_portal.company.v1";
const EMPTY: SupplierPortalCompanyActivity = { rfqs: [], quotations: [], purchaseOrders: [] };

function readCompany(): string | null {
  try {
    return window.localStorage.getItem(COMPANY_KEY);
  } catch {
    return null;
  }
}

function writeCompany(id: string | null): void {
  try {
    if (id) window.localStorage.setItem(COMPANY_KEY, id);
    else window.localStorage.removeItem(COMPANY_KEY);
  } catch {
    /* storage unavailable — the choice just won't survive a reload */
  }
}

interface SupplierSessionContextValue {
  principal: SupplierPortalPrincipal | null;
  isLoading: boolean;
  selectedCompany: SupplierPortalCompany | null;
  activity: SupplierPortalCompanyActivity;
  activityLoading: boolean;
  activityError: string | null;
  signIn: (email: string, password: string) => Promise<SupplierPortalPrincipal>;
  signOut: () => void;
  selectCompany: (companyId: string) => void;
  refreshActivity: () => void;
}

const SupplierSessionContext = createContext<SupplierSessionContextValue | null>(null);

export function SupplierSessionProvider({ children }: { children: ReactNode }) {
  const [principal, setPrincipal] = useState<SupplierPortalPrincipal | null>(null);
  const [selectedCompanyId, setSelectedCompanyId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [activity, setActivity] = useState<SupplierPortalCompanyActivity>(EMPTY);
  const [activityLoading, setActivityLoading] = useState(false);
  const [activityError, setActivityError] = useState<string | null>(null);
  const [activityNonce, setActivityNonce] = useState(0);

  const adopt = useCallback((next: SupplierPortalPrincipal | null) => {
    setPrincipal(next);
    if (!next) {
      setSelectedCompanyId(null);
      return;
    }
    // Keep the remembered company only while it is still granted; with a
    // single company there is nothing to choose.
    const remembered = readCompany();
    const stillThere = next.companies.find((c) => c.id === remembered);
    const pick = stillThere?.id ?? (next.companies.length === 1 ? next.companies[0].id : null);
    setSelectedCompanyId(pick);
    writeCompany(pick);
  }, []);

  // Resolved in an effect, never during render — same reason as the tenant
  // session: localStorage read during render desyncs the SSR/client pass.
  useEffect(() => {
    let cancelled = false;
    portalApi
      .getMe()
      .then((me) => !cancelled && adopt(me))
      .catch(() => !cancelled && adopt(null))
      .finally(() => !cancelled && setIsLoading(false));
    return () => {
      cancelled = true;
    };
  }, [adopt]);

  useEffect(() => {
    if (!selectedCompanyId || !principal) {
      setActivity(EMPTY);
      return;
    }
    let cancelled = false;
    setActivityLoading(true);
    setActivityError(null);
    portalApi
      .getActivity(selectedCompanyId)
      .then((a) => !cancelled && setActivity(a))
      .catch((err) => {
        if (cancelled) return;
        setActivity(EMPTY);
        setActivityError(errorMessage(err));
        // The grant was revoked while signed in: re-read what's left.
        portalApi.getMe().then((me) => !cancelled && adopt(me)).catch(() => undefined);
      })
      .finally(() => !cancelled && setActivityLoading(false));
    return () => {
      cancelled = true;
    };
  }, [selectedCompanyId, principal, activityNonce, adopt]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const next = await portalApi.signIn(email, password);
      adopt(next);
      return next;
    },
    [adopt],
  );

  const signOut = useCallback(() => {
    portalApi.signOut();
    writeCompany(null);
    setPrincipal(null);
    setSelectedCompanyId(null);
  }, []);

  const selectCompany = useCallback((companyId: string) => {
    setSelectedCompanyId(companyId);
    writeCompany(companyId);
  }, []);

  const refreshActivity = useCallback(() => setActivityNonce((n) => n + 1), []);

  const selectedCompany = useMemo(
    () => principal?.companies.find((c) => c.id === selectedCompanyId) ?? null,
    [principal, selectedCompanyId],
  );

  const value = useMemo(
    () => ({
      principal,
      isLoading,
      selectedCompany,
      activity,
      activityLoading,
      activityError,
      signIn,
      signOut,
      selectCompany,
      refreshActivity,
    }),
    [principal, isLoading, selectedCompany, activity, activityLoading, activityError, signIn, signOut, selectCompany, refreshActivity],
  );

  return <SupplierSessionContext.Provider value={value}>{children}</SupplierSessionContext.Provider>;
}

export function useSupplierSession(): SupplierSessionContextValue {
  const context = useContext(SupplierSessionContext);
  if (!context) {
    throw new Error("useSupplierSession must be used inside <SupplierSessionProvider>.");
  }
  return context;
}
