"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

type DirtyGuardContextValue = {
  isDirty: boolean;
  setDirty: (dirty: boolean) => void;
  /** Runs `action` immediately if the form is clean, otherwise confirms first. */
  guardNavigation: (action: () => void) => void;
};

const DirtyGuardContext = React.createContext<DirtyGuardContextValue | null>(null);

/**
 * Provides app-wide "you have unsaved changes" protection. Mount once near
 * the root (AppShell). Forms call `useUnsavedChangesGuard(isDirty)` to
 * register their dirty state; nav links use `GuardedLink` instead of
 * next/link's `Link` so in-app navigation away from a dirty form confirms
 * first. Closing/refreshing the tab is covered by a `beforeunload` handler.
 */
export function DirtyGuardProvider({ children }: { children: React.ReactNode }) {
  const [isDirty, setIsDirty] = React.useState(false);
  const [pendingAction, setPendingAction] = React.useState<(() => void) | null>(null);

  React.useEffect(() => {
    function handler(e: BeforeUnloadEvent) {
      if (!isDirty) return;
      e.preventDefault();
      e.returnValue = "";
    }
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isDirty]);

  const guardNavigation = React.useCallback(
    (action: () => void) => {
      if (isDirty) {
        setPendingAction(() => action);
      } else {
        action();
      }
    },
    [isDirty],
  );

  const value = React.useMemo(
    () => ({ isDirty, setDirty: setIsDirty, guardNavigation }),
    [isDirty, guardNavigation],
  );

  return (
    <DirtyGuardContext.Provider value={value}>
      {children}
      <Dialog open={pendingAction != null} onOpenChange={(open) => !open && setPendingAction(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Leave without saving?</DialogTitle>
            <DialogDescription>
              You have unsaved changes on this page. If you leave now, your edits will be lost.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setPendingAction(null)}>
              Stay on page
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => {
                const action = pendingAction;
                setIsDirty(false);
                setPendingAction(null);
                action?.();
              }}
            >
              Leave page
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </DirtyGuardContext.Provider>
  );
}

function useDirtyGuardContext() {
  const ctx = React.useContext(DirtyGuardContext);
  if (!ctx) {
    throw new Error("useDirtyGuardContext must be used within DirtyGuardProvider");
  }
  return ctx;
}

/** Registers a form's dirty state with the app-wide navigation guard. */
export function useUnsavedChangesGuard(isDirty: boolean) {
  const { setDirty } = useDirtyGuardContext();
  React.useEffect(() => {
    setDirty(isDirty);
  }, [isDirty, setDirty]);

  // Clear the flag on unmount (e.g. after a successful save navigates away).
  React.useEffect(() => {
    return () => setDirty(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

/**
 * Drop-in replacement for next/link's `Link`. If a form registered as dirty,
 * clicking confirms before navigating; otherwise it behaves identically to
 * `Link`.
 */
export function GuardedLink({
  href,
  onClick,
  ...props
}: React.ComponentProps<typeof Link>) {
  const { guardNavigation } = useDirtyGuardContext();
  const router = useRouter();

  return (
    <Link
      href={href}
      onClick={(e) => {
        onClick?.(e);
        if (e.defaultPrevented) return;
        e.preventDefault();
        guardNavigation(() => router.push(typeof href === "string" ? href : href.toString()));
      }}
      {...props}
    />
  );
}

/** Imperative escape hatch for programmatic navigation (router.push) from a dirty form. */
export function useGuardedRouter() {
  const router = useRouter();
  const { guardNavigation } = useDirtyGuardContext();
  return React.useMemo(
    () => ({
      push: (href: string) => guardNavigation(() => router.push(href)),
      replace: (href: string) => guardNavigation(() => router.replace(href)),
    }),
    [guardNavigation, router],
  );
}
