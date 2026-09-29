"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Bell,
  Building2,
  Check,
  ChevronDown,
  HelpCircle,
  LogOut,
  Menu,
  Search,
  Settings,
  ShieldCheck,
  UserRound,
} from "lucide-react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Separator } from "@/components/ui/separator";
import { useAlertSummary } from "@/hooks/use-ops";
import { useIsTenantUser, useMyCompanies, useSession, useSwitchCompany } from "@/hooks/use-session";
import type { SessionUser } from "@/types";

export function TopHeader({
  user,
  onOpenMobileNav,
}: {
  user: SessionUser | null;
  onOpenMobileNav: () => void;
}) {
  const router = useRouter();
  const { signOut } = useSession();
  // BR-AUTH-13: only rendered when the login belongs to more than one
  // company — for everyone else the menu looks exactly as before.
  const myCompanies = useMyCompanies();
  const companies = myCompanies.data ?? [];
  const switcher = useSwitchCompany();
  // The unread count is read from the alert service, not passed in as a
  // decorative default (I13). It is a *tenant* endpoint, so it is skipped
  // for a platform admin, who has no company: asking anyway returned a 403
  // on every page they opened and showed them a bell that could never mean
  // anything. Also skipped until the session has loaded (see `useIsTenantUser`).
  const alertSummary = useAlertSummary(useIsTenantUser());
  const unreadAlerts = alertSummary.data?.unread ?? 0;

  const displayName = user?.fullName ?? "Signed out";
  const initials = displayName
    .split(" ")
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  async function handleSignOut() {
    await signOut();
    router.push("/login");
  }

  return (
    <header className="sticky top-0 z-30 flex h-15 shrink-0 items-center gap-3 border-b border-border bg-card/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-card/80 sm:px-5">
      <button
        onClick={onOpenMobileNav}
        aria-label="Open menu"
        className="-ml-1 rounded-md p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground lg:hidden"
      >
        <Menu className="size-5" />
      </button>

      {/* Global search */}
      <div className="relative min-w-0 flex-1 md:max-w-[440px]">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
        <input
          type="search"
          placeholder="Search products, suppliers, documents..."
          className="h-9 w-full rounded-md border border-input bg-muted/55 pr-14 pl-9 text-[13.5px] text-foreground transition-[background-color,box-shadow,border-color] outline-none placeholder:text-muted-foreground/80 focus:border-ring focus:bg-card focus:ring-[3px] focus:ring-ring/20 [&::-webkit-search-cancel-button]:hidden"
        />
        <kbd className="pointer-events-none absolute top-1/2 right-2.5 hidden -translate-y-1/2 items-center gap-0.5 rounded border border-border bg-card px-1.5 py-0.5 text-[10.5px] font-medium text-muted-foreground sm:flex">
          Ctrl K
        </kbd>
      </div>

      <div className="ml-auto flex items-center gap-1">
        <Link
          href="/alerts"
          aria-label={`Alerts, ${unreadAlerts} unread`}
          className="relative rounded-md p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <Bell className="size-[18px]" strokeWidth={1.9} />
          {unreadAlerts > 0 && (
            <span className="absolute top-1 right-1 flex size-4 items-center justify-center rounded-full bg-destructive text-[9.5px] font-bold text-destructive-foreground tabular">
              {unreadAlerts}
            </span>
          )}
        </Link>

        <button
          aria-label="Help"
          className="hidden rounded-md p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground sm:block"
        >
          <HelpCircle className="size-[18px]" strokeWidth={1.9} />
        </button>

        <Separator orientation="vertical" className="mx-1.5 !h-7" />

        <DropdownMenu>
          <DropdownMenuTrigger className="flex items-center gap-2.5 rounded-md py-1 pr-2 pl-1 transition-colors outline-none hover:bg-muted focus-visible:ring-[3px] focus-visible:ring-ring/25">
            <Avatar>
              <AvatarFallback>{initials}</AvatarFallback>
            </Avatar>
            <span className="hidden text-left leading-tight sm:block">
              <span className="block text-[13px] font-medium text-foreground">
                {displayName}
              </span>
              <span className="block text-[11.5px] text-muted-foreground">
                {user?.companyName ?? ""}
              </span>
            </span>
            <ChevronDown className="hidden size-3.5 text-muted-foreground sm:block" />
          </DropdownMenuTrigger>

          <DropdownMenuContent align="end" className="min-w-[14rem]">
            <DropdownMenuLabel className="py-2">
              <span className="block text-[13.5px] font-medium text-foreground">
                {displayName}
              </span>
              <span className="block text-[12px] font-normal text-muted-foreground">
                {user?.email ?? ""}
              </span>
              <span className="mt-1 block text-[11.5px] font-normal text-muted-foreground">
                {user?.companyName ?? ""} · {user?.roleName ?? ""}
              </span>
            </DropdownMenuLabel>
            {companies.length > 1 && (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuLabel className="py-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                  Switch company
                </DropdownMenuLabel>
                {companies.map((c) => {
                  const suspended = c.companyStatus !== "active";
                  return (
                    <DropdownMenuItem
                      key={c.companyId}
                      disabled={c.isCurrent || suspended || switcher.pendingId !== null}
                      data-testid={`switch-company-${c.companyId}`}
                      onSelect={(event) => {
                        // Keep the menu open while the switch is in flight,
                        // so a failure has somewhere to show.
                        event.preventDefault();
                        if (!c.isCurrent && !suspended) void switcher.switchTo(c.companyId);
                      }}
                    >
                      <Building2 />
                      <span className="flex min-w-0 flex-1 flex-col leading-tight">
                        <span className="truncate">{c.companyName}</span>
                        <span className="text-[11px] text-muted-foreground">
                          {suspended
                            ? "Suspended"
                            : switcher.pendingId === c.companyId
                              ? "Switching..."
                              : `${c.roleName}${c.isHome ? " · home" : ""}`}
                        </span>
                      </span>
                      {c.isCurrent && <Check className="text-primary" />}
                    </DropdownMenuItem>
                  );
                })}
                {switcher.error && (
                  <p className="px-2 py-1 text-[12px] text-destructive" role="alert">
                    {switcher.error}
                  </p>
                )}
              </>
            )}
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link href="/profile">
                <UserRound />
                My Profile
              </Link>
            </DropdownMenuItem>
            <DropdownMenuItem asChild>
              <Link href="/settings">
                <Settings />
                Settings
              </Link>
            </DropdownMenuItem>
            {user?.isPlatformAdmin && (
              <DropdownMenuItem asChild>
                <Link href="/system-admin">
                  <ShieldCheck />
                  System Admin
                </Link>
              </DropdownMenuItem>
            )}
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onClick={handleSignOut}>
              <LogOut />
              Sign Out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
