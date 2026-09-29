"use client";

import * as React from "react";
import { Plus, Ruler, Trash2 } from "lucide-react";

import { FormError } from "@/components/common/async-state";
import { ConfirmButton } from "@/components/common/confirm-dialog";
import { EmptyState } from "@/components/common/empty-state";
import { PermissionGate } from "@/components/common/permission-gate";
import { SectionCard } from "@/components/common/section-card";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useAddUomConversion, useDeleteUomConversion, useUoms } from "@/hooks/use-catalog";
import type { UomConversionRow } from "@/lib/api/catalog.api";
import { formatNumber } from "@/lib/format";
import type { Id } from "@/types";

/**
 * "1 Box = 12 Nos" — lets a PO or GRN line be entered in another unit while
 * stock is always kept in the base unit (BR-INV-08). There is no edit:
 * remove and re-add, because documents already froze the factor they used.
 */
export function UomConversionsCard({
  variantId,
  baseUomId,
  baseCode,
  conversions,
  onChanged,
}: {
  variantId: Id;
  baseUomId: Id;
  baseCode: string;
  conversions: UomConversionRow[];
  onChanged: () => void;
}) {
  const remove = useDeleteUomConversion(onChanged);

  return (
    <SectionCard
      title="Unit Conversions"
      description={`Buy in other units; stock is kept in ${baseCode || "the base unit"}`}
      action={
        <PermissionGate permission="product.update">
          <AddConversionDialog
            variantId={variantId}
            baseUomId={baseUomId}
            baseCode={baseCode}
            existing={conversions}
            onSaved={onChanged}
          />
        </PermissionGate>
      }
    >
      {conversions.length === 0 ? (
        <EmptyState
          icon={Ruler}
          title="No conversions"
          description={`Only ${baseCode || "the base unit"} can be used on documents for this item.`}
          className="py-8"
        />
      ) : (
        <ul className="divide-y divide-border">
          {conversions.map((c) => (
            <li key={c.id} className="flex items-center gap-3 px-4 py-3" data-testid="uom-conversion">
              <span className="min-w-0 flex-1 text-[13.5px] text-foreground tabular">
                1 {c.fromCode} = {formatNumber(c.factor)} {c.toCode}
              </span>
              {c.isPurchaseDefault && <StatusBadge status="active" label="Purchase default" />}
              <PermissionGate permission="product.update">
                <ConfirmButton
                  variant="ghost"
                  size="icon"
                  className="size-7"
                  tone="destructive"
                  aria-label={`Remove ${c.fromCode} conversion`}
                  title={`Remove the ${c.fromCode} conversion?`}
                  description={`New documents will no longer accept ${c.fromCode} for this item. Documents already raised keep the factor they used.`}
                  confirmLabel="Remove"
                  onConfirm={() => remove.run(c.id).then(() => undefined)}
                >
                  <Trash2 className="size-3.5" />
                </ConfirmButton>
              </PermissionGate>
            </li>
          ))}
        </ul>
      )}
      {remove.error && <FormError message={remove.error} className="m-3" />}
    </SectionCard>
  );
}

function AddConversionDialog({
  variantId,
  baseUomId,
  baseCode,
  existing,
  onSaved,
}: {
  variantId: Id;
  baseUomId: Id;
  baseCode: string;
  existing: UomConversionRow[];
  onSaved: () => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [fromUomId, setFromUomId] = React.useState("");
  const [factor, setFactor] = React.useState("");
  const [isDefault, setIsDefault] = React.useState(false);
  const uomsState = useUoms();

  const taken = new Set(existing.map((c) => c.fromUomId));
  const choices = (uomsState.data ?? []).filter((u) => u.id !== baseUomId && !taken.has(u.id));
  const fromCode = choices.find((u) => u.id === fromUomId)?.code;

  const add = useAddUomConversion(variantId, () => {
    setOpen(false);
    onSaved();
  });

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (next) {
      setFromUomId("");
      setFactor("");
      setIsDefault(existing.length === 0);
      add.reset();
    }
  }

  const factorNumber = Number(factor);

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm" data-testid="add-conversion">
          <Plus />
          Add
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a unit conversion</DialogTitle>
          <DialogDescription>How many {baseCode || "base units"} make one of the other unit?</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-3.5">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="cv-unit">Unit</Label>
              <Select value={fromUomId} onValueChange={setFromUomId}>
                <SelectTrigger id="cv-unit">
                  <SelectValue placeholder="Select unit..." />
                </SelectTrigger>
                <SelectContent>
                  {choices.map((u) => (
                    <SelectItem key={u.id} value={u.id}>
                      {u.code} — {u.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cv-factor">Contains ({baseCode})</Label>
              <Input
                id="cv-factor"
                type="number"
                min={0}
                step="any"
                value={factor}
                onChange={(e) => setFactor(e.target.value)}
                placeholder="e.g. 12"
              />
            </div>
          </div>
          {fromCode && factorNumber > 0 && (
            <p className="rounded-lg bg-muted px-3 py-2 text-[13px] text-foreground tabular">
              1 {fromCode} = {formatNumber(factorNumber)} {baseCode}
            </p>
          )}
          <label className="flex items-center gap-2 text-[13.5px] text-foreground">
            <Checkbox id="cv-default" checked={isDefault} onCheckedChange={(v) => setIsDefault(v === true)} />
            Default unit when buying this item
          </label>
        </DialogBody>
        <FormError message={add.error} fieldErrors={add.fieldErrors} />
        <DialogFooter>
          <Button
            onClick={() => add.run({ fromUomId, factor: factorNumber, isPurchaseDefault: isDefault })}
            disabled={!fromUomId || !(factorNumber > 0) || add.isPending}
          >
            {add.isPending ? "Saving..." : "Add Conversion"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
