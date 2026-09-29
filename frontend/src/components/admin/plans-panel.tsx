"use client";

import * as React from "react";
import { ArrowDown, ArrowUp, Check, Pencil, Plus, Trash2, X } from "lucide-react";

import { FormError } from "@/components/common/async-state";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { SectionCard } from "@/components/common/section-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useCreatePlan, useDeletePlan, usePlans, useUpdatePlan } from "@/hooks/use-admin";
import type { adminApi } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The plans a company can be on. Renaming a plan moves every company on it
 * to the new name; a plan in use cannot be deleted, only switched off —
 * which keeps it on those companies but stops it being offered.
 */
export function PlansPanel({ onChanged }: { onChanged?: () => void }) {
  const plans = usePlans();
  const changed = React.useCallback(() => {
    plans.refresh();
    onChanged?.();
  }, [plans, onChanged]);

  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [editing, setEditing] = React.useState<{ id: string; name: string; description: string } | null>(null);
  const [deleting, setDeleting] = React.useState<adminApi.SubscriptionPlan | null>(null);

  const create = useCreatePlan(() => {
    setName("");
    setDescription("");
    changed();
  });
  const update = useUpdatePlan(changed);
  const remove = useDeletePlan(changed);
  const rows = plans.data ?? [];

  async function move(index: number, delta: -1 | 1) {
    const target = index + delta;
    if (target < 0 || target >= rows.length) return;
    const reordered = [...rows];
    [reordered[index], reordered[target]] = [reordered[target], reordered[index]];
    for (const [i, plan] of reordered.entries()) {
      if (plan.sortOrder !== i * 10) await update.run({ id: plan.id, patch: { sortOrder: i * 10 } });
    }
  }

  async function saveEdit() {
    if (!editing) return;
    const result = await update.run({ id: editing.id, patch: { name: editing.name, description: editing.description } });
    if (result) setEditing(null);
  }

  const error = create.error ?? update.error ?? remove.error;

  return (
    <SectionCard title="Subscription plans" description="The plans offered when onboarding or editing a company">
      <div className="overflow-x-auto">
        <Table data-testid="plans-table">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="pl-4">Plan</TableHead>
              <TableHead>Description</TableHead>
              <TableHead className="text-right">Companies</TableHead>
              <TableHead>Offered</TableHead>
              <TableHead className="pr-4 text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((plan, index) => {
              const isEditing = editing?.id === plan.id;
              return (
                <TableRow key={plan.id}>
                  <TableCell className="pl-4 font-medium">
                    {isEditing ? (
                      <Input value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                        className="h-8" aria-label="Plan name" autoFocus />
                    ) : (
                      <span className={cn(!plan.isActive && "text-muted-foreground line-through")}>{plan.name}</span>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {isEditing ? (
                      <Input value={editing.description} onChange={(e) => setEditing({ ...editing, description: e.target.value })}
                        className="h-8" aria-label="Plan description" />
                    ) : (
                      plan.description || "—"
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular">
                    <Badge variant="neutral">{plan.companyCount}</Badge>
                  </TableCell>
                  <TableCell>
                    <Switch
                      checked={plan.isActive}
                      onCheckedChange={(checked) => void update.run({ id: plan.id, patch: { isActive: checked } })}
                      aria-label={`${plan.name} offered`}
                    />
                  </TableCell>
                  <TableCell className="pr-4">
                    <div className="flex justify-end gap-1">
                      {isEditing ? (
                        <>
                          <Button size="icon" variant="ghost" className="size-8" aria-label="Save" onClick={() => void saveEdit()}>
                            <Check className="size-4" />
                          </Button>
                          <Button size="icon" variant="ghost" className="size-8" aria-label="Cancel" onClick={() => setEditing(null)}>
                            <X className="size-4" />
                          </Button>
                        </>
                      ) : (
                        <>
                          <Button size="icon" variant="ghost" className="size-8" aria-label={`Move ${plan.name} up`}
                            disabled={index === 0 || update.isPending} onClick={() => void move(index, -1)}>
                            <ArrowUp className="size-3.5" />
                          </Button>
                          <Button size="icon" variant="ghost" className="size-8" aria-label={`Move ${plan.name} down`}
                            disabled={index === rows.length - 1 || update.isPending} onClick={() => void move(index, 1)}>
                            <ArrowDown className="size-3.5" />
                          </Button>
                          <Button size="icon" variant="ghost" className="size-8" aria-label={`Edit ${plan.name}`}
                            onClick={() => setEditing({ id: plan.id, name: plan.name, description: plan.description })}>
                            <Pencil className="size-3.5" />
                          </Button>
                          <Button size="icon" variant="ghost" className="size-8 text-destructive" aria-label={`Delete ${plan.name}`}
                            disabled={plan.companyCount > 0}
                            title={plan.companyCount > 0 ? "In use — switch it off instead" : undefined}
                            onClick={() => setDeleting(plan)}>
                            <Trash2 className="size-3.5" />
                          </Button>
                        </>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <form
        className="flex flex-wrap gap-2 border-t p-4"
        onSubmit={(e) => {
          e.preventDefault();
          void create.run({ name, description });
        }}
      >
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="New plan name"
          aria-label="New plan name" className="w-48" />
        <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Description (optional)"
          aria-label="New plan description" className="min-w-0 flex-1" />
        <Button type="submit" variant="outline" disabled={create.isPending || !name.trim()}>
          <Plus className="size-4" /> Add plan
        </Button>
      </form>
      {error && (
        <div className="px-4 pb-4">
          <FormError message={error} />
        </div>
      )}

      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`Delete the ${deleting?.name ?? ""} plan?`}
        description="No company is on it. It will no longer be offered."
        confirmLabel="Delete"
        tone="destructive"
        onConfirm={async () => {
          if (deleting) await remove.run(deleting.id);
        }}
      />
    </SectionCard>
  );
}

/** Plan names for a picker: the active ones, plus `current` if it isn't. */
export function planOptions(plans: adminApi.SubscriptionPlan[] | undefined, current?: string): string[] {
  const active = (plans ?? []).filter((p) => p.isActive).map((p) => p.name);
  return current && !active.includes(current) ? [...active, current] : active;
}
