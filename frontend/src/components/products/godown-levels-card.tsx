"use client";

import * as React from "react";
import { Pencil, Warehouse } from "lucide-react";

import { FormError } from "@/components/common/async-state";
import { EmptyState } from "@/components/common/empty-state";
import { PermissionGate } from "@/components/common/permission-gate";
import { SectionCard } from "@/components/common/section-card";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useGodowns, useSaveGodownPolicies } from "@/hooks/use-catalog";
import type { GodownPolicyInput, GodownPolicyRow } from "@/lib/api/catalog.api";
import { formatNumber } from "@/lib/format";
import type { Id } from "@/types";

/**
 * Per-godown reorder levels. A godown without its own level uses the item's
 * default reorder point — the Low Stock screen and reorder report already
 * read these (per-godown level wins, I8).
 */
export function GodownLevelsCard({
  variantId,
  uomCode,
  defaultReorderPoint,
  defaultReorderQty,
  policies,
  onChanged,
}: {
  variantId: Id;
  uomCode: string;
  defaultReorderPoint: number;
  defaultReorderQty: number;
  policies: GodownPolicyRow[];
  onChanged: () => void;
}) {
  return (
    <SectionCard
      title="Reorder Levels by Godown"
      description={`Other godowns use the default: ${formatNumber(defaultReorderPoint)} ${uomCode}`}
      action={
        <PermissionGate permission="product.update">
          <EditLevelsDialog
            variantId={variantId}
            uomCode={uomCode}
            defaultReorderPoint={defaultReorderPoint}
            defaultReorderQty={defaultReorderQty}
            policies={policies}
            onSaved={onChanged}
          />
        </PermissionGate>
      }
    >
      {policies.length === 0 ? (
        <EmptyState
          icon={Warehouse}
          title="Same level everywhere"
          description="Set a godown-specific level when one location sells faster than the rest."
          className="py-8"
        />
      ) : (
        <ul className="divide-y divide-border">
          {policies.map((p) => (
            <li key={p.id} className="flex items-center gap-3 px-4 py-3" data-testid="godown-level">
              <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium text-foreground">{p.godownName}</span>
              <span className="text-right text-[12.5px] text-muted-foreground tabular">
                Reorder at <span className="font-medium text-foreground">{formatNumber(p.reorderPoint)}</span>
                {" · "}order {formatNumber(p.reorderQty)}
                {p.maxStock !== undefined && <> · max {formatNumber(p.maxStock)}</>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  );
}

interface RowState {
  reorderPoint: string;
  reorderQty: string;
  maxStock: string;
}

function EditLevelsDialog({
  variantId,
  uomCode,
  defaultReorderPoint,
  defaultReorderQty,
  policies,
  onSaved,
}: {
  variantId: Id;
  uomCode: string;
  defaultReorderPoint: number;
  defaultReorderQty: number;
  policies: GodownPolicyRow[];
  onSaved: () => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [rows, setRows] = React.useState<Record<Id, RowState>>({});
  const godownsState = useGodowns();
  const godowns = godownsState.data ?? [];

  const save = useSaveGodownPolicies(variantId, () => {
    setOpen(false);
    onSaved();
  });

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (next) {
      const initial: Record<Id, RowState> = {};
      for (const p of policies) {
        initial[p.godownId] = {
          reorderPoint: String(p.reorderPoint),
          reorderQty: String(p.reorderQty),
          maxStock: p.maxStock === undefined ? "" : String(p.maxStock),
        };
      }
      setRows(initial);
      save.reset();
    }
  }

  function setField(godownId: Id, field: keyof RowState, value: string) {
    setRows((prev) => ({
      ...prev,
      [godownId]: { ...(prev[godownId] ?? { reorderPoint: "", reorderQty: "", maxStock: "" }), [field]: value },
    }));
  }

  function submit() {
    // A godown whose reorder point is blank has no level of its own. Keep
    // any existing level for a godown this user can't see in the list, so
    // saving never silently deletes it.
    const visible = new Set(godowns.map((g) => g.id));
    const out: GodownPolicyInput[] = [];
    for (const p of policies) {
      if (!visible.has(p.godownId)) {
        out.push({ godownId: p.godownId, reorderPoint: p.reorderPoint, reorderQty: p.reorderQty, maxStock: p.maxStock ?? null, isStocked: p.isStocked });
      }
    }
    for (const g of godowns) {
      const r = rows[g.id];
      if (!r || r.reorderPoint.trim() === "") continue;
      out.push({
        godownId: g.id,
        reorderPoint: Number(r.reorderPoint),
        reorderQty: r.reorderQty.trim() === "" ? 0 : Number(r.reorderQty),
        maxStock: r.maxStock.trim() === "" ? null : Number(r.maxStock),
        isStocked: true,
      });
    }
    return save.run(out);
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm" data-testid="edit-godown-levels">
          <Pencil />
          Edit
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Reorder levels by godown</DialogTitle>
          <DialogDescription>
            Leave a godown blank to use the item default ({formatNumber(defaultReorderPoint)} {uomCode}, order{" "}
            {formatNumber(defaultReorderQty)}).
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <div className="grid grid-cols-[1fr_88px_88px_88px] items-center gap-x-2 gap-y-2 text-[13px]">
            <span className="text-caption text-muted-foreground">Godown</span>
            <span className="text-caption text-muted-foreground">Reorder at</span>
            <span className="text-caption text-muted-foreground">Order qty</span>
            <span className="text-caption text-muted-foreground">Max (opt.)</span>
            {godowns.map((g) => {
              const r = rows[g.id] ?? { reorderPoint: "", reorderQty: "", maxStock: "" };
              return (
                <React.Fragment key={g.id}>
                  <span className="truncate text-foreground">{g.name}</span>
                  <Input
                    aria-label={`${g.name} reorder point`}
                    type="number"
                    min={0}
                    step="any"
                    value={r.reorderPoint}
                    placeholder={String(defaultReorderPoint)}
                    onChange={(e) => setField(g.id, "reorderPoint", e.target.value)}
                  />
                  <Input
                    aria-label={`${g.name} reorder quantity`}
                    type="number"
                    min={0}
                    step="any"
                    value={r.reorderQty}
                    placeholder={String(defaultReorderQty)}
                    onChange={(e) => setField(g.id, "reorderQty", e.target.value)}
                  />
                  <Input
                    aria-label={`${g.name} max stock`}
                    type="number"
                    min={0}
                    step="any"
                    value={r.maxStock}
                    onChange={(e) => setField(g.id, "maxStock", e.target.value)}
                  />
                </React.Fragment>
              );
            })}
          </div>
        </DialogBody>
        <FormError message={save.error} fieldErrors={save.fieldErrors} />
        <DialogFooter>
          <Button onClick={submit} disabled={save.isPending}>
            {save.isPending ? "Saving..." : "Save Levels"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
