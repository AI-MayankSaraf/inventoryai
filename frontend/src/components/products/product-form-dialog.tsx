"use client";

/**
 * Add / edit a product.
 *
 * The correction that matters here: there is no "Current Stock" field, and
 * there never will be — a product form cannot change a balance (C2, C3).
 * Creating a product may optionally post an opening-stock transaction into one
 * godown; editing a product only ever shows stock, read-only, sourced from the
 * inventory ledger via `useStockByGodown`.
 */

import * as React from "react";
import { Pencil, Plus } from "lucide-react";

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
  useBrands,
  useCategories,
  useCreateProduct,
  useGodowns,
  useProduct,
  useUoms,
  useUpdateProduct,
} from "@/hooks/use-catalog";
import { useStockByGodown } from "@/hooks/use-inventory";
import type { catalogApi } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import type { Id, Product } from "@/types";

const SELECT_CLASS =
  "h-9 w-full rounded-md border border-input bg-card px-3 text-[13.5px] outline-none focus:border-ring focus:ring-[3px] focus:ring-ring/20 disabled:cursor-not-allowed disabled:opacity-60";

const TRACKING_TYPES: { value: Product["trackingType"]; label: string }[] = [
  { value: "none", label: "None" },
  { value: "batch", label: "Batch" },
  { value: "serial", label: "Serial" },
];

type FormState = {
  name: string;
  sku: string;
  brandId: string;
  categoryId: string;
  uomId: string;
  trackingType: Product["trackingType"];
  hsnCode: string;
  gstRate: string;
  purchasePrice: string;
  salePrice: string;
  mrp: string;
  reorderPoint: string;
  reorderQty: string;
  leadTimeDays: string;
  barcode: string;
  mpn: string;
  modelCode: string;
  displayEmoji: string;
};

const EMPTY_FORM: FormState = {
  name: "",
  sku: "",
  brandId: "",
  categoryId: "",
  uomId: "",
  trackingType: "none",
  hsnCode: "",
  gstRate: "18",
  purchasePrice: "0",
  salePrice: "0",
  mrp: "0",
  reorderPoint: "10",
  reorderQty: "50",
  leadTimeDays: "7",
  barcode: "",
  mpn: "",
  modelCode: "",
  displayEmoji: "📦",
};

function formFromDetail(detail: catalogApi.ProductDetail): FormState {
  return {
    name: detail.product.name,
    sku: detail.variant.sku,
    brandId: detail.product.brandId ?? "",
    categoryId: detail.product.categoryId ?? "",
    uomId: detail.variant.uomId,
    trackingType: detail.product.trackingType,
    hsnCode: detail.variant.hsnCode ?? detail.product.hsnCode,
    gstRate: String(detail.variant.gstRate ?? detail.product.gstRate),
    purchasePrice: String(detail.variant.purchasePrice),
    salePrice: String(detail.variant.salePrice),
    mrp: String(detail.variant.mrp),
    reorderPoint: String(detail.variant.reorderPoint),
    reorderQty: String(detail.variant.reorderQty),
    leadTimeDays: String(detail.variant.leadTimeDays ?? 7),
    barcode: detail.variant.barcode ?? "",
    mpn: detail.variant.mpn ?? "",
    modelCode: detail.variant.modelCode ?? "",
    displayEmoji: detail.product.displayEmoji ?? "📦",
  };
}

export function ProductFormDialog({
  variantId,
  trigger,
  onSaved,
}: {
  /** Present ⇒ edit this variant. Absent ⇒ create a new product. */
  variantId?: Id;
  onSaved?: (detail: catalogApi.ProductDetail) => void;
  trigger?: React.ReactNode;
}) {
  const isEdit = !!variantId;
  const [open, setOpen] = React.useState(false);
  const [form, setForm] = React.useState<FormState>(EMPTY_FORM);
  const [attributes, setAttributes] = React.useState<Record<string, string>>({});
  const [openingGodownId, setOpeningGodownId] = React.useState("");
  const [openingQty, setOpeningQty] = React.useState("");

  const categories = useCategories();
  const brands = useBrands();
  const uoms = useUoms();
  const godowns = useGodowns();
  const detailState = useProduct(open && isEdit ? variantId : undefined);
  const stockState = useStockByGodown(open && isEdit ? variantId : undefined);

  const create = useCreateProduct((detail) => {
    onSaved?.(detail);
    setOpen(false);
  });
  const update = useUpdateProduct(variantId ?? "", (detail) => {
    onSaved?.(detail);
    setOpen(false);
  });
  const mutation = isEdit ? update : create;

  React.useEffect(() => {
    if (open && isEdit && detailState.data) {
      setForm(formFromDetail(detailState.data));
      setAttributes(detailState.data.variant.attributes ?? {});
    }
  }, [open, isEdit, detailState.data]);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function handleOpenChange(next: boolean) {
    setOpen(next);
    mutation.reset();
    if (next && !isEdit) {
      setForm(EMPTY_FORM);
      setAttributes({});
      setOpeningGodownId("");
      setOpeningQty("");
    }
  }

  async function save() {
    const input: catalogApi.ProductInput = {
      name: form.name.trim(),
      sku: form.sku.trim(),
      brandId: form.brandId || null,
      categoryId: form.categoryId || null,
      hsnCode: form.hsnCode.trim(),
      gstRate: Number(form.gstRate) || 0,
      uomId: form.uomId,
      trackingType: form.trackingType,
      purchasePrice: Number(form.purchasePrice) || 0,
      salePrice: Number(form.salePrice) || 0,
      mrp: Number(form.mrp) || 0,
      reorderPoint: Number(form.reorderPoint) || 0,
      reorderQty: Number(form.reorderQty) || 0,
      leadTimeDays: form.leadTimeDays ? Number(form.leadTimeDays) : undefined,
      barcode: form.barcode.trim() || undefined,
      mpn: form.mpn.trim() || undefined,
      modelCode: form.modelCode.trim() || undefined,
      displayEmoji: form.displayEmoji.trim() || undefined,
      attributes,
      openingStock:
        !isEdit && openingGodownId && Number(openingQty) > 0
          ? { godownId: openingGodownId, quantity: Number(openingQty) }
          : null,
    };
    await mutation.run(input);
  }

  const canSubmit = !!form.name.trim() && !!form.sku.trim() && !!form.uomId && !mutation.isPending;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button>
            {isEdit ? <Pencil /> : <Plus />}
            {isEdit ? "Edit Product" : "Add Product"}
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-w-[600px]">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit product" : "Add a product"}</DialogTitle>
          <DialogDescription>
            {isEdit ? "Update this product's catalog details." : "Add a new SKU to your catalog."}
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-4">
          <FormError message={mutation.error} fieldErrors={mutation.fieldErrors} />

          <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
            <div className="space-y-1.5 sm:col-span-2">
              <Label htmlFor="pf-name">Product Name</Label>
              <Input id="pf-name" value={form.name} onChange={(e) => set("name", e.target.value)} autoFocus />
              {mutation.fieldErrors.name && (
                <p className="text-[12px] text-destructive">{mutation.fieldErrors.name}</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pf-sku">SKU</Label>
              <Input
                id="pf-sku"
                value={form.sku}
                onChange={(e) => set("sku", e.target.value.toUpperCase())}
                disabled={isEdit}
                className="font-mono"
              />
              {mutation.fieldErrors.sku && (
                <p className="text-[12px] text-destructive">{mutation.fieldErrors.sku}</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pf-brand">Brand</Label>
              <select
                id="pf-brand"
                value={form.brandId}
                onChange={(e) => set("brandId", e.target.value)}
                className={SELECT_CLASS}
              >
                <option value="">—</option>
                {(brands.data ?? []).map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pf-category">Category</Label>
              <select
                id="pf-category"
                value={form.categoryId}
                onChange={(e) => set("categoryId", e.target.value)}
                className={SELECT_CLASS}
              >
                <option value="">—</option>
                {(categories.data ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.path}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pf-uom">Unit</Label>
              <select
                id="pf-uom"
                value={form.uomId}
                onChange={(e) => set("uomId", e.target.value)}
                className={SELECT_CLASS}
              >
                <option value="">Choose a unit</option>
                {(uoms.data ?? []).map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name} ({u.code})
                  </option>
                ))}
              </select>
              {mutation.fieldErrors.uomId && (
                <p className="text-[12px] text-destructive">{mutation.fieldErrors.uomId}</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pf-tracking">Tracking</Label>
              <select
                id="pf-tracking"
                value={form.trackingType}
                onChange={(e) => set("trackingType", e.target.value as Product["trackingType"])}
                className={SELECT_CLASS}
              >
                {TRACKING_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pf-hsn">HSN Code</Label>
              <Input
                id="pf-hsn"
                value={form.hsnCode}
                onChange={(e) => set("hsnCode", e.target.value)}
                className="font-mono"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pf-gst">GST Rate %</Label>
              <Input
                id="pf-gst"
                type="number"
                min={0}
                value={form.gstRate}
                onChange={(e) => set("gstRate", e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pf-purchase-price">Purchase Price</Label>
              <Input
                id="pf-purchase-price"
                type="number"
                min={0}
                value={form.purchasePrice}
                onChange={(e) => set("purchasePrice", e.target.value)}
              />
              {mutation.fieldErrors.purchasePrice && (
                <p className="text-[12px] text-destructive">{mutation.fieldErrors.purchasePrice}</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pf-sale-price">Sale Price</Label>
              <Input
                id="pf-sale-price"
                type="number"
                min={0}
                value={form.salePrice}
                onChange={(e) => set("salePrice", e.target.value)}
              />
              {mutation.fieldErrors.salePrice && (
                <p className="text-[12px] text-destructive">{mutation.fieldErrors.salePrice}</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pf-mrp">MRP</Label>
              <Input
                id="pf-mrp"
                type="number"
                min={0}
                value={form.mrp}
                onChange={(e) => set("mrp", e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pf-reorder-point">Reorder Point</Label>
              <Input
                id="pf-reorder-point"
                type="number"
                min={0}
                value={form.reorderPoint}
                onChange={(e) => set("reorderPoint", e.target.value)}
              />
              {mutation.fieldErrors.reorderPoint && (
                <p className="text-[12px] text-destructive">{mutation.fieldErrors.reorderPoint}</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pf-reorder-qty">Reorder Quantity</Label>
              <Input
                id="pf-reorder-qty"
                type="number"
                min={0}
                value={form.reorderQty}
                onChange={(e) => set("reorderQty", e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pf-lead-time">Lead Time (days)</Label>
              <Input
                id="pf-lead-time"
                type="number"
                min={0}
                value={form.leadTimeDays}
                onChange={(e) => set("leadTimeDays", e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pf-barcode">Barcode</Label>
              <Input
                id="pf-barcode"
                value={form.barcode}
                onChange={(e) => set("barcode", e.target.value)}
                className="font-mono"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pf-mpn">MPN</Label>
              <Input
                id="pf-mpn"
                value={form.mpn}
                onChange={(e) => set("mpn", e.target.value)}
                className="font-mono"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pf-model">Model Code</Label>
              <Input
                id="pf-model"
                value={form.modelCode}
                onChange={(e) => set("modelCode", e.target.value)}
                className="font-mono"
              />
            </div>
          </div>

          {!isEdit && (
            <div className="space-y-2.5 rounded-lg border border-border bg-muted/40 p-3.5">
              <p className="text-[13px] font-medium text-foreground">Opening stock (optional)</p>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="pf-opening-godown">Godown</Label>
                  <select
                    id="pf-opening-godown"
                    value={openingGodownId}
                    onChange={(e) => setOpeningGodownId(e.target.value)}
                    className={SELECT_CLASS}
                  >
                    <option value="">Select a godown</option>
                    {(godowns.data ?? []).map((g) => (
                      <option key={g.id} value={g.id}>
                        {g.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="pf-opening-qty">Quantity</Label>
                  <Input
                    id="pf-opening-qty"
                    type="number"
                    min={0}
                    value={openingQty}
                    onChange={(e) => setOpeningQty(e.target.value)}
                  />
                </div>
              </div>
              <p className="text-caption text-muted-foreground">
                Posts an opening-stock transaction into the godown you choose. After that, stock only ever
                changes through receipts, transfers and adjustments — never by editing this form.
              </p>
            </div>
          )}

          {isEdit && (
            <div className="space-y-2 rounded-lg border border-border p-3.5">
              <p className="text-[13px] font-medium text-foreground">Stock by godown</p>
              {stockState.data && stockState.data.length > 0 ? (
                <ul className="divide-y divide-border">
                  {stockState.data.map((row) => (
                    <li key={row.id} className="flex items-center justify-between py-1.5 text-[13px]">
                      <span className="text-muted-foreground">{row.godownName}</span>
                      <span className="font-medium text-foreground tabular">
                        {formatNumber(row.quantity)} {row.uomCode}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-caption text-muted-foreground">No stock recorded for this product yet.</p>
              )}
              <p className="text-caption text-muted-foreground">
                Stock is changed from Inventory — receipts, transfers and adjustments — not from this form.
              </p>
            </div>
          )}
        </DialogBody>

        <DialogFooter>
          <PermissionButton
            permission={isEdit ? "product.update" : "product.create"}
            onClick={save}
            disabled={!canSubmit}
          >
            {mutation.isPending ? "Saving..." : isEdit ? "Save Changes" : "Add Product"}
          </PermissionButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
