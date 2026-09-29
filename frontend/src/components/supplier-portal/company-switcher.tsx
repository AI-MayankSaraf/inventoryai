"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Building2, Check, ChevronDown } from "lucide-react";

import { Card } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useSupplierSession } from "@/hooks/use-supplier-session";
import { cn } from "@/lib/utils";

/**
 * Full-page company picker — shown right after sign-in when a supplier
 * account has more than one company, and reachable any time from
 * `CompanySwitcherMenu`'s "Switch company" item.
 */
export function CompanyPicker() {
  const router = useRouter();
  const { principal, selectedCompany, selectCompany } = useSupplierSession();

  function choose(companyId: string) {
    selectCompany(companyId);
    router.push("/supplier-portal/dashboard");
  }

  if (!principal) return null;

  return (
    <div className="mx-auto w-full max-w-[560px]">
      <header className="mb-6 text-center">
        <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-foreground">
          Which company are you working with?
        </h1>
        <p className="mt-1.5 text-body text-muted-foreground">
          You supply {principal.companies.length} companies on InventoryAI. Switch anytime from the
          header.
        </p>
      </header>

      <div className="space-y-2.5">
        {principal.companies.map((company) => {
          const active = company.id === selectedCompany?.id;
          return (
            <Card
              key={company.id}
              role="button"
              tabIndex={0}
              onClick={() => choose(company.id)}
              onKeyDown={(e) => e.key === "Enter" && choose(company.id)}
              className={cn(
                "flex cursor-pointer items-center gap-3.5 p-4 transition-colors hover:border-ring",
                active && "border-primary ring-[3px] ring-primary/15",
              )}
            >
              <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                <Building2 className="size-5" strokeWidth={1.9} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[14.5px] font-medium text-foreground">{company.name}</span>
                <span className="block text-caption text-muted-foreground">
                  {[company.city, company.stateName].filter(Boolean).join(", ")}
                  {company.city || company.stateName ? " · " : ""}as {company.supplierName}
                </span>
              </span>
              {active && <Check className="size-4 shrink-0 text-primary" />}
            </Card>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Compact switcher for the portal header — the "selected company context"
 * ask isn't just a one-time choice at login, it has to stay changeable
 * without signing out.
 */
export function CompanySwitcherMenu() {
  const router = useRouter();
  const { principal, selectedCompany, selectCompany } = useSupplierSession();

  if (!principal) return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex items-center gap-2 rounded-md border border-border bg-card py-1.5 pr-2.5 pl-2.5 text-left transition-colors outline-none hover:bg-muted focus-visible:ring-[3px] focus-visible:ring-ring/25">
        <Building2 className="size-4 text-muted-foreground" strokeWidth={1.9} />
        <span className="max-w-[160px] truncate text-[13px] font-medium text-foreground">
          {selectedCompany?.name ?? "Select a company"}
        </span>
        <ChevronDown className="size-3.5 text-muted-foreground" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[15rem]">
        <DropdownMenuLabel>Companies you supply</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {principal.companies.map((company) => (
          <DropdownMenuItem key={company.id} onClick={() => selectCompany(company.id)}>
            <Building2 />
            <span className="min-w-0 flex-1 truncate">{company.name}</span>
            {company.id === selectedCompany?.id && <Check className="size-3.5 text-primary" />}
          </DropdownMenuItem>
        ))}
        {principal.companies.length > 1 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => router.push("/supplier-portal/select-company")}>
              Browse all companies
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
