"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Lock, ShieldAlert } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { Sidebar } from "@/components/layout/sidebar";
import { TopHeader } from "@/components/layout/top-header";
import { Button } from "@/components/ui/button";
import { TooltipProvider } from "@/components/ui/tooltip";
import { SessionProvider, usePermissions, useSession } from "@/hooks/use-session";
import { authApi } from "@/lib/api";
import { DirtyGuardProvider } from "@/lib/unsaved-changes";
import { cn } from "@/lib/utils";

const STORAGE_KEY = "inventoryai:sidebar-collapsed";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <TooltipProvider>
        <DirtyGuardProvider>
          <Shell>{children}</Shell>
        </DirtyGuardProvider>
      </TooltipProvider>
    </SessionProvider>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { user, impersonation, refresh } = useSession();
  const [collapsed, setCollapsed] = React.useState(false);
  const [mobileOpen, setMobileOpen] = React.useState(false);

  // Read the collapse preference after hydration — localStorage is not
  // available during server rendering and reading it in render desynchronises
  // the two passes.
  React.useEffect(() => {
    try {
      setCollapsed(window.localStorage.getItem(STORAGE_KEY) === "1");
    } catch {
      /* storage unavailable — fall back to expanded */
    }
  }, []);

  const toggleCollapsed = React.useCallback(() => {
    setCollapsed((prev) => {
      try {
        window.localStorage.setItem(STORAGE_KEY, prev ? "0" : "1");
      } catch {
        /* ignore */
      }
      return !prev;
    });
  }, []);

  const endImpersonation = React.useCallback(async () => {
    await authApi.endImpersonation();
    refresh();
    router.push("/system-admin");
  }, [refresh, router]);

  return (
    <div className="min-h-dvh bg-background print:bg-white">
      <div className="print:hidden">
        <Sidebar
          collapsed={collapsed}
          onToggleCollapsed={toggleCollapsed}
          mobileOpen={mobileOpen}
          onCloseMobile={() => setMobileOpen(false)}
        />
      </div>

      <div
        className={cn(
          "flex min-h-dvh flex-col transition-[padding] duration-200 ease-out print:pl-0",
          collapsed ? "lg:pl-16" : "lg:pl-[248px]",
        )}
      >
        {impersonation && (
          <div className="flex items-center justify-center gap-2.5 bg-warning px-4 py-2 text-center text-[12.5px] font-medium text-warning-foreground print:hidden">
            <ShieldAlert className="size-4 shrink-0" />
            Viewing as {impersonation.targetUserName} · {impersonation.targetCompanyName} — every
            action is logged against {impersonation.platformUserName}
            <Button
              size="sm"
              variant="secondary"
              className="ml-1 h-6 px-2 text-[11.5px]"
              onClick={endImpersonation}
            >
              Return to Super Admin
            </Button>
          </div>
        )}
        <div className="print:hidden">
          <TopHeader user={user} onOpenMobileNav={() => setMobileOpen(true)} />
        </div>
        <main className="flex-1 px-4 py-5 sm:px-6 sm:py-6 print:p-0">
          <div className="mx-auto w-full max-w-[1600px] print:max-w-none">
            <RouteGuard>{children}</RouteGuard>
          </div>
        </main>
      </div>
    </div>
  );
}

/**
 * Refuses to mount a page the signed-in user cannot open (ROUTE_PERMISSIONS).
 *
 * The sidebar already hides those pages, but a typed or bookmarked URL used
 * to render them anyway, and every request they made came back 403. The
 * server still decides; this only stops asking it for data that will be
 * refused, and says why.
 */
function RouteGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { isLoading } = useSession();
  const { user, canAccessRoute } = usePermissions();

  // Until the session is known the page must not mount: its queries would
  // fire before the guard can tell whether they are allowed.
  if (isLoading) return null;
  if (!user || canAccessRoute(pathname)) return <>{children}</>;

  return user.isPlatformAdmin ? (
    <EmptyState
      icon={Lock}
      title="This page belongs to a company"
      description="Platform admins are not members of a company. To see a company's screens, impersonate one of its users from System Admin."
      action={
        <Button asChild size="sm">
          <Link href="/system-admin">Go to System Admin</Link>
        </Button>
      }
      className="py-16"
    />
  ) : (
    <EmptyState
      icon={Lock}
      title="You don't have access to this page"
      description="Your role doesn't include it. Ask your company's Owner if you need it."
      action={
        <Button asChild size="sm" variant="outline">
          <Link href="/dashboard">Go to Dashboard</Link>
        </Button>
      }
      className="py-16"
    />
  );
}
