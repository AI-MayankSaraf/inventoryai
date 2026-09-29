"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, Pencil, Trash2, Warehouse } from "lucide-react";

import { AsyncBoundary } from "@/components/common/async-state";
import { ConfirmButton } from "@/components/common/confirm-dialog";
import { PageHeader } from "@/components/common/page-header";
import { PermissionGate } from "@/components/common/permission-gate";
import { GodownFormDialog } from "@/components/godowns/godown-form-dialog";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useDeactivateGodown, useGodownsWithUsage } from "@/hooks/use-admin";
import { useUoms } from "@/hooks/use-catalog";
import type { GodownWithUsage } from "@/lib/api/admin.api";
import { formatCurrency, formatNumber } from "@/lib/format";


export function GodownsScreen() {
  const state = useGodownsWithUsage();

  return (
    <div className="space-y-5">
      <PageHeader
        title="Godowns"
        description="Storage locations that stock can be received into and issued from"
        actions={
          <PermissionGate permission="godown.manage">
            {/* Without this, a newly added godown doesn't appear until the
                user navigates away and back. */}
            <GodownFormDialog onSaved={() => state.refresh()} />
          </PermissionGate>
        }
      />

      <AsyncBoundary
        state={state}
        isEmpty={(d) => d.length === 0}
        empty={{
          icon: Warehouse,
          title: "No godowns yet",
          description: "Add your first storage location so goods receipts have somewhere to land.",
        }}
      >
        {(godowns) => (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {godowns.map((godown) => (
              <GodownCard key={godown.id} godown={godown} onChanged={() => state.refresh()} />
            ))}
          </div>
        )}
      </AsyncBoundary>
    </div>
  );
}

function GodownCard({ godown, onChanged }: { godown: GodownWithUsage; onChanged: () => void }) {
  const uoms = useUoms().data ?? [];
  const uomCode = (id: string | null | undefined) => uoms.find((u) => u.id === id)?.code ?? "";
  // Same fix as the top-level "Add Godown" dialog above — an in-card edit
  // or delete otherwise leaves this card showing stale data indefinitely.
  const deactivate = useDeactivateGodown(onChanged);

  // Usage arrives with the list itself. Each card used to fetch its own,
  // which was one request per godown on every render of this screen.
  const inUse = godown.inUse;
  const reason = godown.isDefault
    ? "it's the default godown — set another as default first"
    : godown.usageReason;
  const blocked = inUse || godown.isDefault;

  return (
    <Card className="p-5">
      <div className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary-subtle text-primary-subtle-foreground">
          <Warehouse className="size-5" strokeWidth={1.9} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-section text-foreground">{godown.name}</p>
          <p className="text-caption text-muted-foreground">
            {godown.city} · In-charge {godown.inchargeName || "Unassigned"}
            {godown.capacityValue ? ` · Capacity ${godown.capacityValue.toLocaleString("en-IN")} ${uomCode(godown.capacityUomId)}` : ""}
          </p>
        </div>
        <PermissionGate permission="godown.manage">
          <div className="flex shrink-0 items-center gap-1">
            <GodownFormDialog
              godown={godown}
              onSaved={onChanged}
              trigger={
                <Button variant="ghost" size="icon-sm" aria-label={`Edit ${godown.name}`}>
                  <Pencil />
                </Button>
              }
            />
            {blocked ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <span>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      disabled
                      aria-label={`Delete ${godown.name}`}
                    >
                      <Trash2 />
                    </Button>
                  </span>
                </TooltipTrigger>
                <TooltipContent>Can&apos;t delete — {reason ?? "checking usage"}</TooltipContent>
              </Tooltip>
            ) : (
              <ConfirmButton
                variant="ghost"
                size="icon-sm"
                tone="destructive"
                title={`Delete ${godown.name}?`}
                description="This godown holds no stock and is not referenced by any transaction, so it can be safely removed."
                confirmLabel="Delete"
                aria-label={`Delete ${godown.name}`}
                onConfirm={() => deactivate.run(godown.id)}
              >
                <Trash2 className="text-destructive" />
              </ConfirmButton>
            )}
          </div>
        </PermissionGate>
      </div>

      <dl className="mt-5 grid grid-cols-2 gap-4">
        <div>
          <dt className="text-caption text-muted-foreground">SKUs stored</dt>
          <dd className="text-[20px] leading-none font-semibold text-foreground tabular">
            {formatNumber(godown.skuCount)}
          </dd>
        </div>
        <div>
          <dt className="text-caption text-muted-foreground">Stock value</dt>
          <dd className="text-[20px] leading-none font-semibold text-foreground tabular">
            {formatCurrency(godown.stockValue)}
          </dd>
        </div>
      </dl>

      {deactivate.error && (
        <p className="mt-3 text-[12.5px] font-medium text-destructive">{deactivate.error}</p>
      )}

      <Button variant="outline" size="sm" asChild className="mt-5 w-full">
        <Link href="/inventory/by-godown">
          View stock
          <ArrowRight />
        </Link>
      </Button>
    </Card>
  );
}
