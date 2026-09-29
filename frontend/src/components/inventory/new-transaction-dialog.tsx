"use client";

import * as React from "react";
import { Plus } from "lucide-react";

import { FormError } from "@/components/common/async-state";
import { PermissionButton } from "@/components/common/permission-gate";
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
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useGodowns, useProduct, useProducts } from "@/hooks/use-catalog";
import { useCreateTransaction, useStockByGodown } from "@/hooks/use-inventory";
import { usePermissions } from "@/hooks/use-session";
import { PREVIEW_NUMBER_NOTE } from "@/lib/domain/numbering";
import { useNextDocumentNumber } from "@/hooks/use-admin";
import { formatNumber } from "@/lib/format";
import type { CreateTransactionInput, Id } from "@/types";

type TxnType = CreateTransactionInput["txnType"];

const TYPE_OPTIONS: { value: TxnType; label: string; description: string }[] = [
  {
    value: "DAMAGE",
    label: "Damage / Write-off",
    description: "Stock damaged, lost or otherwise unsellable. This always reduces stock.",
  },
  {
    value: "SALES_ISSUE",
    label: "Sales Issue",
    description: "Stock issued against a sale outside the normal order flow. This always reduces stock.",
  },
  {
    value: "STOCK_CORRECTION",
    label: "Stock Correction",
    description: "Adjust stock after a physical count — choose whether it increases or decreases below.",
  },
  {
    value: "EXPIRY_WRITE_OFF",
    label: "Expiry Write-off",
    description: "Stock that has expired and is being removed. This always reduces stock.",
  },
];

const REMARKS_REQUIRED: TxnType[] = ["DAMAGE", "STOCK_CORRECTION"];

export function NewTransactionDialog() {
  const nextNumber = useNextDocumentNumber("adjustment");
  const [open, setOpen] = React.useState(false);
  const [txnType, setTxnType] = React.useState<TxnType>("STOCK_CORRECTION");
  const [productVariantId, setProductVariantId] = React.useState<Id | "">("");
  const [godownId, setGodownId] = React.useState<Id | "">("");
  const [quantity, setQuantity] = React.useState("1");
  const [direction, setDirection] = React.useState<"increase" | "decrease">("decrease");
  const [reference, setReference] = React.useState("");
  const [remarks, setRemarks] = React.useState("");

  const permissions = usePermissions();
  const productsState = useProducts({ limit: 1000, sort: "name" });
  const products = productsState.data?.items ?? [];
  const godownsState = useGodowns();
  const godowns = React.useMemo(() => {
    const all = godownsState.data ?? [];
    const visible = new Set(permissions.visibleGodowns(all.map((g) => g.id)));
    return all.filter((g) => visible.has(g.id));
  }, [godownsState.data, permissions]);

  const productDetail = useProduct(productVariantId || undefined);
  const stockByGodown = useStockByGodown(productVariantId || undefined);

  const create = useCreateTransaction(() => {
    setOpen(false);
    reset();
  });

  function reset() {
    setTxnType("STOCK_CORRECTION");
    setProductVariantId("");
    setGodownId("");
    setQuantity("1");
    setDirection("decrease");
    setReference("");
    setRemarks("");
    create.reset();
  }

  const quantityNumber = Number(quantity);
  const currentBalance = stockByGodown.data?.find((r) => r.godownId === godownId)?.quantity;
  const remarksRequired = REMARKS_REQUIRED.includes(txnType);
  const canSubmit =
    !!productVariantId && !!godownId && quantityNumber > 0 && !create.isPending;

  async function submit() {
    const variant = productDetail.data?.variant;
    if (!productVariantId || !godownId || !variant) return;
    await create.run({
      txnType,
      productVariantId,
      godownId,
      quantity: quantityNumber,
      uomId: variant.uomId,
      direction: txnType === "STOCK_CORRECTION" ? direction : undefined,
      reference: reference.trim() || undefined,
      remarks: remarks.trim() || undefined,
    });
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        if (!v) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button>
          <Plus />
          New Transaction
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Record a manual transaction</DialogTitle>
          <DialogDescription>
            Every stock change is a transaction — this is how you record one that didn&apos;t come
            from a Goods Receipt or a transfer.
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-3.5">
          <p className="text-caption text-muted-foreground">
            {nextNumber} · {PREVIEW_NUMBER_NOTE}
          </p>

          <div className="space-y-1.5">
            <Label htmlFor="tx-kind">Transaction Type</Label>
            <Select value={txnType} onValueChange={(v) => setTxnType(v as TxnType)}>
              <SelectTrigger id="tx-kind">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TYPE_OPTIONS.map((k) => (
                  <SelectItem key={k.value} value={k.value}>
                    {k.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-caption text-muted-foreground">
              {TYPE_OPTIONS.find((k) => k.value === txnType)?.description}
            </p>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="tx-product">Product</Label>
            <Select value={productVariantId} onValueChange={setProductVariantId}>
              <SelectTrigger id="tx-product">
                <SelectValue placeholder="Select product..." />
              </SelectTrigger>
              <SelectContent>
                {products.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.name} · {p.sku}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="tx-godown">Godown</Label>
            <Select value={godownId} onValueChange={setGodownId}>
              <SelectTrigger id="tx-godown">
                <SelectValue placeholder="Select godown..." />
              </SelectTrigger>
              <SelectContent>
                {godowns.map((g) => (
                  <SelectItem key={g.id} value={g.id}>
                    {g.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {productVariantId && godownId && (
              <p className="text-caption text-muted-foreground">
                Current balance here: {formatNumber(currentBalance ?? 0)}
              </p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="tx-qty">Quantity</Label>
              <Input
                id="tx-qty"
                type="number"
                min={1}
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
              />
            </div>
            {txnType === "STOCK_CORRECTION" && (
              <div className="space-y-1.5">
                <Label htmlFor="tx-direction">Direction</Label>
                <Select value={direction} onValueChange={(v) => setDirection(v as typeof direction)}>
                  <SelectTrigger id="tx-direction">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="increase">Increase stock (+)</SelectItem>
                    <SelectItem value="decrease">Decrease stock (−)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="tx-reference">Reference (optional)</Label>
            <Input
              id="tx-reference"
              value={reference}
              onChange={(e) => setReference(e.target.value)}
              placeholder="e.g. a physical count sheet number"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="tx-remarks">
              Remarks {remarksRequired ? "(required)" : "(optional)"}
            </Label>
            <Textarea id="tx-remarks" value={remarks} onChange={(e) => setRemarks(e.target.value)} rows={2} />
          </div>
        </DialogBody>

        <FormError message={create.error} fieldErrors={create.fieldErrors} />

        <DialogFooter>
          <PermissionButton permission="inventory.adjust" onClick={submit} disabled={!canSubmit}>
            {create.isPending ? "Recording..." : "Record Transaction"}
          </PermissionButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
