"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { CalendarDays, Plus, Save, Send, Trash2 } from "lucide-react";

import { FormError } from "@/components/common/async-state";
import { PrintHeader } from "@/components/common/print-header";
import { SectionCard } from "@/components/common/section-card";
import { TaxSummary } from "@/components/procurement/tax-summary";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useCompanySettings, useNextDocumentNumber } from "@/hooks/use-admin";
import { useGodowns, useProducts, useUoms } from "@/hooks/use-catalog";
import { useCreatePurchaseOrder } from "@/hooks/use-procurement";
import { useSuppliers } from "@/hooks/use-suppliers";
import { computeDocumentTotals, computeLine, isInterState, taxBreakdown } from "@/lib/domain/money";
import { PREVIEW_NUMBER_NOTE } from "@/lib/domain/numbering";
import { formatCurrency } from "@/lib/format";
import type { procurementApi } from "@/lib/api";
import type { Id, TaxableLine } from "@/types";

const PAYMENT_TERMS = ["Advance", "15 Days", "30 Days", "45 Days", "Cash on Delivery"];
const DELIVERY_TERMS = ["FOR", "Ex-Works", "Door Delivery", "To Pay"];

interface DraftLine {
  key: string;
  productVariantId: Id | "";
  sku: string;
  productName: string;
  uomId: Id | "";
  uomCode: string;
  quantity: number;
  unitPrice: number;
  discountPct: number;
  gstRate: number;
}

function blankLine(): DraftLine {
  return {
    key: crypto.randomUUID(),
    productVariantId: "",
    sku: "",
    productName: "",
    uomId: "",
    uomCode: "",
    quantity: 1,
    unitPrice: 0,
    discountPct: 0,
    gstRate: 0,
  };
}

/**
 * Create Purchase Order.
 *
 * There is no "update purchase order" endpoint — a draft PO is either sent
 * forward or cancelled through `useSetPurchaseOrderStatus` on the detail
 * screen, never re-edited here. Every total on this screen comes from
 * `computeDocumentTotals` / `computeLine` (the same engine the API uses when
 * it builds the record), and CGST/SGST vs IGST is derived from the selected
 * supplier's and godown's state codes — never a toggle (C14).
 */
export function PoForm() {
  const router = useRouter();
  const suppliersState = useSuppliers({});
  const godownsState = useGodowns();
  const productsState = useProducts({ limit: 500 });
  const uomsState = useUoms();
  const settingsState = useCompanySettings();

  const create = useCreatePurchaseOrder((po) => router.push(`/procurement/purchase-orders/${po.id}`));

  const [supplierId, setSupplierId] = React.useState<Id | "">("");
  const [poDate, setPoDate] = React.useState(() => new Date().toISOString().slice(0, 10));
  const [expectedDeliveryDate, setExpectedDeliveryDate] = React.useState("");
  const [deliveryGodownId, setDeliveryGodownId] = React.useState<Id | "">("");
  const [paymentTerms, setPaymentTerms] = React.useState("30 Days");
  const [deliveryTerms, setDeliveryTerms] = React.useState("FOR");
  const [freight, setFreight] = React.useState(0);
  const [lines, setLines] = React.useState<DraftLine[]>([blankLine()]);

  const suppliers = suppliersState.data?.items ?? [];
  const godowns = godownsState.data ?? [];
  const products = productsState.data?.items ?? [];
  const uoms = React.useMemo(() => uomsState.data ?? [], [uomsState.data]);
  const uomsByCode = React.useMemo(() => new Map(uoms.map((u) => [u.code, u])), [uoms]);

  const supplier = suppliers.find((s) => s.id === supplierId);
  const godown = godowns.find((g) => g.id === deliveryGodownId);

  function updateLine(key: string, patch: Partial<DraftLine>) {
    setLines((prev) => prev.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  }

  function addLine() {
    setLines((prev) => [...prev, blankLine()]);
  }

  function removeLine(key: string) {
    setLines((prev) => prev.filter((l) => l.key !== key));
  }

  function handleProductChange(key: string, productVariantId: string) {
    const product = products.find((p) => p.id === productVariantId);
    if (!product) return;
    const uom = uomsByCode.get(product.uomCode);
    updateLine(key, {
      productVariantId,
      sku: product.sku,
      productName: product.name,
      uomId: uom?.id ?? "",
      uomCode: product.uomCode,
      gstRate: product.gstRate,
      unitPrice: product.purchasePrice,
    });
  }

  const taxableLines: TaxableLine[] = lines.map((l) => ({
    quantity: l.quantity,
    unitPrice: l.unitPrice,
    discountPct: l.discountPct,
    gstRate: l.gstRate,
    cessRate: 0,
  }));

  const totals = computeDocumentTotals({
    lines: taxableLines,
    freightAmount: freight,
    supplierStateCode: supplier?.stateCode,
    placeOfSupplyStateCode: godown?.stateCode,
  });
  const taxRows = taxBreakdown(taxableLines, totals.isInterState);

  const interStateNote =
    supplier && godown
      ? isInterState(supplier.stateCode, godown.stateCode)
        ? `Inter-state supply — ${supplier.stateName} (supplier) vs ${godown.stateCode} (delivery). IGST applies.`
        : `Intra-state supply — supplier and delivery godown are in the same state. CGST + SGST applies.`
      : "Select a supplier and a delivery godown to determine the GST treatment.";

  const previewNumber = useNextDocumentNumber("po");

  function buildInput(status: "draft" | "pending_approval"): procurementApi.PurchaseOrderInput {
    return {
      supplierId: supplierId as Id,
      poDate,
      expectedDeliveryDate: expectedDeliveryDate || null,
      deliveryGodownId: deliveryGodownId as Id,
      paymentTerms,
      deliveryTerms,
      freightAmount: freight,
      lines: lines.map((l) => ({
        productVariantId: l.productVariantId as Id,
        quantity: l.quantity,
        uomId: l.uomId as Id,
        unitPrice: l.unitPrice,
        discountPct: l.discountPct,
        gstRate: l.gstRate,
      })),
      status,
    };
  }

  return (
    <div className="space-y-4">
      <PrintHeader
        company={settingsState.data?.company.name ?? ""}
        gstin={settingsState.data?.company.gstin}
        address={settingsState.data?.company.addressLine1}
        email={settingsState.data?.company.email}
        phone={settingsState.data?.company.phone}
        docLabel={`Purchase Order — ${previewNumber}`}
      />

      <FormError message={create.error} fieldErrors={create.fieldErrors} />

      <SectionCard
        title="Basic Information"
        description="Add items manually, or start a purchase order from a supplier comparison instead"
      >
        <div className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-2 lg:grid-cols-3">
          <div className="space-y-1.5">
            <Label htmlFor="po-number">PO Number</Label>
            <Input id="po-number" value={previewNumber} readOnly className="bg-muted tabular" />
            <p className="text-[11px] text-muted-foreground">{PREVIEW_NUMBER_NOTE}</p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="po-date">PO Date</Label>
            <div className="relative">
              <Input
                id="po-date"
                type="date"
                value={poDate}
                onChange={(e) => setPoDate(e.target.value)}
                className="pr-9"
              />
              <CalendarDays className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground" />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="po-supplier">Supplier</Label>
            <Select value={supplierId || undefined} onValueChange={(v) => setSupplierId(v)}>
              <SelectTrigger id="po-supplier">
                <SelectValue placeholder="Select supplier" />
              </SelectTrigger>
              <SelectContent>
                {suppliers.map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {create.fieldErrors.supplierId && (
              <p className="text-[11.5px] text-destructive">{create.fieldErrors.supplierId}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="po-delivery">Expected Delivery Date</Label>
            <div className="relative">
              <Input
                id="po-delivery"
                type="date"
                value={expectedDeliveryDate}
                onChange={(e) => setExpectedDeliveryDate(e.target.value)}
                className="pr-9"
              />
              <CalendarDays className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground" />
            </div>
            {create.fieldErrors.expectedDeliveryDate && (
              <p className="text-[11.5px] text-destructive">{create.fieldErrors.expectedDeliveryDate}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="po-payment">Payment Terms</Label>
            <Select value={paymentTerms} onValueChange={setPaymentTerms}>
              <SelectTrigger id="po-payment">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PAYMENT_TERMS.map((t) => (
                  <SelectItem key={t} value={t}>
                    {t}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="po-delivery-terms">Delivery Terms</Label>
            <Select value={deliveryTerms} onValueChange={setDeliveryTerms}>
              <SelectTrigger id="po-delivery-terms">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {DELIVERY_TERMS.map((t) => (
                  <SelectItem key={t} value={t}>
                    {t}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="po-godown">Deliver To</Label>
            <Select value={deliveryGodownId || undefined} onValueChange={(v) => setDeliveryGodownId(v)}>
              <SelectTrigger id="po-godown">
                <SelectValue placeholder="Select godown" />
              </SelectTrigger>
              <SelectContent>
                {godowns.map((g) => (
                  <SelectItem key={g.id} value={g.id}>
                    {g.name}, {g.city}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {create.fieldErrors.deliveryGodownId && (
              <p className="text-[11.5px] text-destructive">{create.fieldErrors.deliveryGodownId}</p>
            )}
          </div>
        </div>
      </SectionCard>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <div className="xl:col-span-8">
          <SectionCard
            title="Items"
            action={
              <Button variant="outline" size="sm" onClick={addLine}>
                <Plus />
                Add Item
              </Button>
            }
          >
            {lines.length === 0 ? (
              <div className="p-8 text-center">
                <p className="text-[13.5px] text-muted-foreground">
                  No items yet.{" "}
                  <button type="button" onClick={addLine} className="font-medium text-primary hover:underline">
                    Add an item
                  </button>
                  .
                </p>
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="pl-4">Product</TableHead>
                    <TableHead className="w-20 text-right">Qty</TableHead>
                    <TableHead className="w-28 text-right">Unit Price</TableHead>
                    <TableHead className="w-20 text-right">Disc %</TableHead>
                    <TableHead className="w-20 text-right">GST %</TableHead>
                    <TableHead className="w-28 text-right">Total</TableHead>
                    <TableHead className="w-10 pr-3" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {lines.map((line, index) => {
                    const lineTotals = computeLine({
                      quantity: line.quantity,
                      unitPrice: line.unitPrice,
                      discountPct: line.discountPct,
                      gstRate: line.gstRate,
                      cessRate: 0,
                    });
                    const err = (field: string) => create.fieldErrors[`lines.${index}.${field}`];
                    return (
                      <TableRow key={line.key} className="hover:bg-transparent">
                        <TableCell className="max-w-[240px] pl-4 align-top whitespace-normal">
                          <Select
                            value={line.productVariantId || undefined}
                            onValueChange={(v) => handleProductChange(line.key, v)}
                          >
                            <SelectTrigger size="sm">
                              <SelectValue placeholder="Select product" />
                            </SelectTrigger>
                            <SelectContent>
                              {products.map((p) => (
                                <SelectItem key={p.id} value={p.id}>
                                  {p.name} · {p.sku}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <span className="mt-1 block text-caption text-muted-foreground tabular">
                            {line.sku && `${line.sku} · ${line.uomCode}`}
                          </span>
                          {err("productVariantId") && (
                            <p className="text-[11px] text-destructive">{err("productVariantId")}</p>
                          )}
                        </TableCell>

                        <TableCell className="align-top">
                          <Input
                            type="number"
                            min={0}
                            value={line.quantity}
                            onChange={(e) => updateLine(line.key, { quantity: Number(e.target.value) })}
                            className="h-8.5 text-right tabular"
                          />
                          {err("quantity") && <p className="text-[11px] text-destructive">{err("quantity")}</p>}
                        </TableCell>
                        <TableCell className="align-top">
                          <Input
                            type="number"
                            min={0}
                            value={line.unitPrice}
                            onChange={(e) => updateLine(line.key, { unitPrice: Number(e.target.value) })}
                            className="h-8.5 text-right tabular"
                          />
                          {err("unitPrice") && <p className="text-[11px] text-destructive">{err("unitPrice")}</p>}
                        </TableCell>
                        <TableCell className="align-top">
                          <Input
                            type="number"
                            min={0}
                            max={100}
                            value={line.discountPct}
                            onChange={(e) => updateLine(line.key, { discountPct: Number(e.target.value) })}
                            className="h-8.5 text-right tabular"
                          />
                          {err("discountPct") && (
                            <p className="text-[11px] text-destructive">{err("discountPct")}</p>
                          )}
                        </TableCell>
                        <TableCell className="align-top">
                          <Input
                            type="number"
                            min={0}
                            value={line.gstRate}
                            onChange={(e) => updateLine(line.key, { gstRate: Number(e.target.value) })}
                            className="h-8.5 text-right tabular"
                          />
                        </TableCell>
                        <TableCell className="align-top text-right">
                          <span className="block pt-2 font-medium text-foreground tabular">
                            {formatCurrency(lineTotals.lineTotal)}
                          </span>
                          <span className="block text-caption text-muted-foreground tabular">
                            net {formatCurrency(lineTotals.lineNet)}
                          </span>
                        </TableCell>
                        <TableCell className="pr-3 align-top">
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            aria-label="Remove line"
                            className="mt-1 text-muted-foreground hover:text-destructive"
                            onClick={() => removeLine(line.key)}
                          >
                            <Trash2 />
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </SectionCard>
        </div>

        <div className="space-y-4 xl:col-span-4">
          <SectionCard title="Summary" description={interStateNote}>
            <div className="p-4">
              <div className="mb-3 space-y-1.5">
                <Label htmlFor="po-freight">Freight</Label>
                <Input
                  id="po-freight"
                  type="number"
                  min={0}
                  value={freight}
                  onChange={(e) => setFreight(Number(e.target.value))}
                  className="text-right tabular"
                />
              </div>
              <TaxSummary money={totals} taxRows={taxRows} />
            </div>
          </SectionCard>

          <div className="rounded-xl border border-border bg-card p-4">
            <p className="text-[12px] font-medium text-muted-foreground">Actions</p>
            <div className="mt-2.5 flex flex-col gap-2">
              <Button
                variant="outline"
                disabled={create.isPending || lines.length === 0}
                onClick={() => create.run(buildInput("draft"))}
              >
                <Save />
                Save Draft
              </Button>
              <Button
                disabled={create.isPending || lines.length === 0}
                onClick={() => create.run(buildInput("pending_approval"))}
              >
                <Send />
                Save &amp; Submit for Approval
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
