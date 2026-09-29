"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { CompanySwitcherMenu } from "@/components/supplier-portal/company-switcher";
import { Logo } from "@/components/common/logo";
import { useSupplierSession } from "@/hooks/use-supplier-session";

/**
 * Shell for signed-in supplier-portal screens: requires a signed-in
 * principal (redirects to the portal login otherwise) and keeps the company
 * switcher available on every screen, not just right after sign-in.
 */
export function SupplierPortalShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { principal, isLoading, signOut, selectedCompany } = useSupplierSession();

  React.useEffect(() => {
    if (!isLoading && !principal) router.replace("/supplier-portal/login");
  }, [isLoading, principal, router]);

  if (isLoading || !principal) return null;

  const initials = principal.contactName
    .split(" ")
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  function handleSignOut() {
    signOut();
    router.push("/supplier-portal/login");
  }

  return (
    <div className="min-h-dvh bg-background">
      <header className="sticky top-0 z-30 flex h-15 shrink-0 items-center gap-3 border-b border-border bg-card/95 px-4 backdrop-blur sm:px-6">
        <Logo showWordmark className="mr-2" />
        <span className="hidden text-[12.5px] text-muted-foreground md:block">Supplier Portal</span>

        <div className="ml-auto flex items-center gap-2.5">
          <CompanySwitcherMenu />

          <div className="mx-1 hidden items-center gap-2 sm:flex">
            <Avatar>
              <AvatarFallback>{initials}</AvatarFallback>
            </Avatar>
            <span className="leading-tight">
              <span className="block text-[13px] font-medium text-foreground">
                {principal.contactName}
              </span>
              <span className="block text-[11.5px] text-muted-foreground">
                {selectedCompany?.supplierName ?? principal.email}
              </span>
            </span>
          </div>

          <Button variant="outline" size="sm" onClick={handleSignOut}>
            <LogOut />
            Sign Out
          </Button>
        </div>
      </header>

      <main className="px-4 py-6 sm:px-6">
        <div className="mx-auto w-full max-w-[1100px]">{children}</div>
      </main>
    </div>
  );
}
