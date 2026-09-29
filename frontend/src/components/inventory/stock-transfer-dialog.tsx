"use client";

import * as React from "react";
import { ArrowLeftRight } from "lucide-react";

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
import { useCreateTransfer, useStockByGodown } from "@/hooks/use-inventory";
import { usePermissions } from "@/hooks/use-session";
import { PREVIEW_NUMBER_NOTE } from "@/lib/domain/numbering";
import { useNextDocumentNumber } from "@/hooks/use-admin";
import { formatNumber } from "@/lib/format";
import type { Id } from "@/types";

export function StockTransferDialog() {
  const nextNumber = useNextDocumentNumber("transfer");
  const [open, setOpen] = React.useState(false);
  const [fromGodownId, setFromGodownId] = React.useState<Id | "">("");
  const [toGodownId, setToGodownId] = React.useState<Id | "">("");
  const [productVariantId, setProductVariantId] = React.useState<Id | "">("");
  const [quantity, setQuantity] = React.useState("1");
  const [vehicleNumber, setVehicleNumber] = React.useState("");
  const [lrNumber, setLrNumber] = React.useState("");
  const [ewayBillNumber, setEwayBillNumber] = React.useState("");
  const [remarks, setRemarks] = React.useState("");

  const permissions = usePermissions();
  const godownsState = useGodowns();
  const godowns = React.useMemo(() => {
    const all = godownsState.data ?? [];
    const visible = new Set(permissions.visibleGodowns(all.map((g) => g.id)));
    return all.filter((g) => visible.has(g.id));
  }, [godownsState.data, permissions]);

  const productsState = useProducts({ limit: 1000, sort: "name" });
  const products = productsState.data?.items ?? [];
  const productDetail = useProduct(productVariantId || undefined);
  const stockByGodown = useStockByGodown(productVariantId || undefined);

  const create = useCreateTransfer(() => {
    setOpen(false);
    reset();
  });

  function reset() {
    setFromGodownId("");
    setToGodownId("");
    setProductVariantId("");
    setQuantity("1");
    setVehicleNumber("");
    setLrNumber("");
    setEwayBillNumber("");
    setRemarks("");
    create.reset();
  }

  const quantityNumber = Number(quantity);
  const available = stockByGodown.data?.find((r) => r.godownId === fromGodownId)?.quantity;
  const sameGodown = !!fromGodownId && !!toGodownId && fromGodownId === toGodownId;
  const canSubmit =
    !!fromGodownId && !!toGodownId && !sameGodown && !!productVariantId && quantityNumber > 0 && !create.isPending;

  async function submit() {
    const variant = productDetail.data?.variant;
    if (!fromGodownId || !toGodownId || !productVariantId || !variant) return;
    await create.run({
      fromGodownId,
      toGodownId,
      productVariantId,
      quantity: quantityNumber,
      uomId: variant.uomId,
      vehicleNumber: vehicleNumber.trim() || undefined,
      lrNumber: lrNumber.trim() || undefined,
      ewayBillNumber: ewayBillNumber.trim() || undefined,
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
          <ArrowLeftRight />
          New Transfer
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Transfer stock between godowns</DialogTitle>
          <DialogDescription>
            Posts a linked pair of ledger entries — stock leaves the source godown and lands in the
            destination the moment you save.
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-3.5">
          <p className="text-caption text-muted-foreground">
            {nextNumber} · {PREVIEW_NUMBER_NOTE}
          </p>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="tr-from">From Godown</Label>
              <Select value={fromGodownId} onValueChange={setFromGodownId}>
                <SelectTrigger id="tr-from">
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
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tr-to">To Godown</Label>
              <Select value={toGodownId} onValueChange={setToGodownId}>
                <SelectTrigger id="tr-to">
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
            </div>
          </div>
          {sameGodown && (
            <p className="text-[12.5px] font-medium text-destructive">Pick two different godowns.</p>
          )}

          <div className="space-y-1.5">
            <Label htmlFor="tr-product">Product</Label>
            <Select value={productVariantId} onValueChange={setProductVariantId}>
              <SelectTrigger id="tr-product">
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
            {productVariantId && fromGodownId && (
              <p className="text-caption text-muted-foreground">
                {formatNumber(available ?? 0)} available at the source godown
              </p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="tr-qty">Quantity</Label>
            <Input
              id="tr-qty"
              type="number"
              min={1}
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="tr-vehicle">Vehicle Number (optional)</Label>
              <Input id="tr-vehicle" value={vehicleNumber} onChange={(e) => setVehicleNumber(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tr-lr">LR Number (optional)</Label>
              <Input id="tr-lr" value={lrNumber} onChange={(e) => setLrNumber(e.target.value)} />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="tr-eway">E-way Bill Number (optional)</Label>
            <Input id="tr-eway" value={ewayBillNumber} onChange={(e) => setEwayBillNumber(e.target.value)} />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="tr-remarks">Remarks (optional)</Label>
            <Textarea id="tr-remarks" value={remarks} onChange={(e) => setRemarks(e.target.value)} rows={2} />
          </div>
        </DialogBody>

        <FormError message={create.error} fieldErrors={create.fieldErrors} />

        <DialogFooter>
          <PermissionButton permission="inventory.transfer" onClick={submit} disabled={!canSubmit}>
            {create.isPending ? "Transferring..." : "Transfer Stock"}
          </PermissionButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
