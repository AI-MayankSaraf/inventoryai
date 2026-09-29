"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { CalendarDays, Info } from "lucide-react";

import { FormError } from "@/components/common/async-state";
import { SectionCard } from "@/components/common/section-card";
import { TaxSummary } from "@/components/procurement/tax-summary";
import { Alert, AlertDescription } from "@/components/ui/alert";
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
import { useGoodsReceipt, useGoodsReceipts } from "@/hooks/use-receiving";
import { useCreateSupplierInvoice } from "@/hooks/use-invoices";
import { usePurchaseOrder, usePurchaseOrders } from "@/hooks/use-procurement";
import { useSuppliers } from "@/hooks/use-suppliers";
import { computeDocumentTotals, computeLine, taxBreakdown } from "@/lib/domain/money";
import { formatCurrency, formatQuantity } from "@/lib/format";
import type { invoicesApi } from "@/lib/api";
import type { Id, InvoiceType, TaxableLine } from "@/types";

const INVOICE_TYPES: { value: InvoiceType; label: string }[] = [
  { value: "tax_invoice", label: "Tax Invoice" },
  { value: "bill_of_supply", label: "Bill of Supply" },
  { value: "debit_note", label: "Debit Note" },
  { value: "credit_note", label: "Credit Note" },
];

interface DraftLine {
  key: string;
  purchaseOrderItemId: Id;
  goodsReceiptItemId: Id;
  productVariantId: Id;
  sku: string;
  productName: string;
  uomId: Id;
  uomCode: string;
  poUnitPrice: number;
  grnAcceptedQuantity: number;
  quantity: number;
  unitPrice: number;
  discountPct: number;
  gstRate: number;
}

const today = () => new Date().toISOString().slice(0, 10);

/**
 * Enter a supplier invoice.
 *
 * The invoice number here is the SUPPLIER's — never generated, so there is no
 * number preview on this form (unlike every other document). Lines are built
 * by intersecting a purchase order's items with a confirmed goods receipt's
 * accepted quantities, so every line carries both `purchaseOrderItemId` and
 * `goodsReceiptItemId` — without them the three-way match has nothing to
 * compare against. Quantity and rate stay editable because the point of this
 * screen is to capture what the supplier actually billed, even when it
 * disagrees with the order or the receipt.
 */
export function SupplierInvoiceForm() {
  const router = useRouter();

  const [supplierId, setSupplierId] = React.useState<Id | "">("");
  const [poId, setPoId] = React.useState<Id | "">("");
  const [grnId, setGrnId] = React.useState<Id | "">("");
  const [lines, setLines] = React.useState<DraftLine[]>([]);

  const [invoiceNumber, setInvoiceNumber] = React.useState("");
  const [invoiceDate, setInvoiceDate] = React.useState(today());
  const [dueDate, setDueDate] = React.useState("");
  const [invoiceType, setInvoiceType] = React.useState<InvoiceType>("tax_invoice");
  const [ewayBillNumber, setEwayBillNumber] = React.useState("");
  const [irn, setIrn] = React.useState("");
  const [freight, setFreight] = React.useState(0);
  const [otherCharges, setOtherCharges] = React.useState(0);
  const [tdsAmount, setTdsAmount] = React.useState(0);
  const [notes, setNotes] = React.useState("");

  const suppliersState = useSuppliers({});
  const posState = usePurchaseOrders({ filters: { supplierId: supplierId || undefined }, limit: 200, sort: "-poDate" });
  const grnsState = useGoodsReceipts({ filters: { purchaseOrderId: poId || undefined }, limit: 200 });
  const poDetailState = usePurchaseOrder(poId || undefined);
  const grnDetailState = useGoodsReceipt(grnId || undefined);

  const create = useCreateSupplierInvoice((invoice) => router.push(`/supplier-invoices/${invoice.id}`));

  const suppliers = suppliersState.data?.items ?? [];
  const supplier = suppliers.find((s) => s.id === supplierId);
  const orders = React.useMemo(
    () => (posState.data?.items ?? []).filter((po) => !["draft", "cancelled"].includes(po.status)),
    [posState.data],
  );
  const selectedPo = orders.find((po) => po.id === poId);
  const receipts = React.useMemo(
    () =>
      (grnsState.data?.items ?? []).filter(
        (g) => g.status === "received" || g.status === "partially_received",
      ),
    [grnsState.data],
  );
  const selectedGrn = receipts.find((g) => g.id === grnId);

  // Lines are rebuilt from the PO's items and the GRN's accepted quantities
  // whenever the chosen GRN changes — each PO line without a matching
  // accepted GRN line is left out, since there is nothing to bill yet.
  React.useEffect(() => {
    if (!poDetailState.data || !grnDetailState.data) {
      setLines([]);
      return;
    }
    const grnItems = grnDetailState.data.items;
    const next: DraftLine[] = [];
    for (const poItem of poDetailState.data.items) {
      const grnItem = grnItems.find((g) => g.purchaseOrderItemId === poItem.id);
      if (!grnItem || grnItem.acceptedQuantity <= 0) continue;
      next.push({
        key: poItem.id,
        purchaseOrderItemId: poItem.id,
        goodsReceiptItemId: grnItem.id,
        productVariantId: poItem.productVariantId,
        sku: poItem.sku,
        productName: poItem.productName,
        uomId: poItem.uomId,
        uomCode: poItem.uomCode,
        poUnitPrice: poItem.unitPrice,
        grnAcceptedQuantity: grnItem.acceptedQuantity,
        quantity: grnItem.acceptedQuantity,
        unitPrice: poItem.unitPrice,
        discountPct: poItem.discountPct,
        gstRate: poItem.gstRate,
      });
    }
    setLines(next);
  }, [poDetailState.data, grnDetailState.data]);

  function updateLine(key: string, patch: Partial<DraftLine>) {
    setLines((prev) => prev.map((l) => (l.key === key ? { ...l, ...patch } : l)));
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
    otherCharges,
    supplierStateCode: supplier?.stateCode,
    placeOfSupplyStateCode: selectedPo?.placeOfSupplyStateCode,
  });
  const taxRows = taxBreakdown(taxableLines, totals.isInterState);

  const fieldError = (key: string) => create.fieldErrors[key];

  function buildInput(): invoicesApi.SupplierInvoiceInput {
    return {
      invoiceNumber: invoiceNumber.trim(),
      invoiceDate,
      dueDate: dueDate || null,
      supplierId: supplierId as Id,
      purchaseOrderId: poId || null,
      goodsReceiptId: grnId || null,
      invoiceType,
      ewayBillNumber: ewayBillNumber || undefined,
      irn: irn || undefined,
      freightAmount: freight,
      otherCharges,
      tdsAmount,
      notes: notes || undefined,
      lines: lines.map((l) => ({
        productVariantId: l.productVariantId,
        purchaseOrderItemId: l.purchaseOrderItemId,
        goodsReceiptItemId: l.goodsReceiptItemId,
        quantity: l.quantity,
        uomId: l.uomId,
        unitPrice: l.unitPrice,
        discountPct: l.discountPct,
        gstRate: l.gstRate,
      })),
    };
  }

  return (
    <div className="space-y-4">
      <FormError message={create.error} fieldErrors={create.fieldErrors} />

      <SectionCard
        title="Bill against a Purchase Order & Receipt"
        description="Pick the supplier, then the PO they billed against, then the confirmed receipt whose accepted quantities the invoice will be compared to"
      >
        <div className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-3">
          <div className="space-y-1.5">
            <Label htmlFor="inv-supplier">Supplier</Label>
            <Select
              value={supplierId || undefined}
              onValueChange={(v) => {
                setSupplierId(v);
                setPoId("");
                setGrnId("");
              }}
            >
              <SelectTrigger id="inv-supplier">
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
            {fieldError("supplierId") && <p className="text-caption text-destructive">{fieldError("supplierId")}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="inv-po">Purchase Order</Label>
            <Select
              value={poId || undefined}
              onValueChange={(v) => {
                setPoId(v);
                setGrnId("");
              }}
              disabled={!supplierId}
            >
              <SelectTrigger id="inv-po">
                <SelectValue placeholder={supplierId ? "Select PO" : "Select a supplier first"} />
              </SelectTrigger>
              <SelectContent>
                {orders.map((po) => (
                  <SelectItem key={po.id} value={po.id}>
                    {po.poNumber} · {formatCurrency(po.totalAmount)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="inv-grn">Goods Receipt</Label>
            <Select value={grnId || undefined} onValueChange={setGrnId} disabled={!poId}>
              <SelectTrigger id="inv-grn">
                <SelectValue placeholder={poId ? "Select GRN" : "Select a PO first"} />
              </SelectTrigger>
              <SelectContent>
                {receipts.map((g) => (
                  <SelectItem key={g.id} value={g.id}>
                    {g.grnNumber}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {poId && receipts.length === 0 && (
              <p className="text-caption text-muted-foreground">No confirmed receipts against this PO yet.</p>
            )}
          </div>
        </div>
        {selectedGrn && (
          <p className="border-t border-border px-4 py-2.5 text-[12.5px] text-muted-foreground">
            {lines.length > 0
              ? `${lines.length} line${lines.length === 1 ? "" : "s"} loaded from ${selectedGrn.grnNumber}'s accepted quantities.`
              : `${selectedGrn.grnNumber} has nothing accepted yet — nothing to bill.`}
          </p>
        )}
      </SectionCard>

      <SectionCard title="Invoice Details">
        <div className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-1.5">
            <Label htmlFor="inv-number">Invoice Number (supplier&apos;s)</Label>
            <Input
              id="inv-number"
              value={invoiceNumber}
              onChange={(e) => setInvoiceNumber(e.target.value)}
              placeholder="As printed on the supplier's invoice"
            />
            {fieldError("invoiceNumber") && (
              <p className="text-caption text-destructive">{fieldError("invoiceNumber")}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="inv-date">Invoice Date</Label>
            <div className="relative">
              <Input
                id="inv-date"
                type="date"
                value={invoiceDate}
                onChange={(e) => setInvoiceDate(e.target.value)}
                className="pr-9"
              />
              <CalendarDays className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground" />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="inv-due">Due Date</Label>
            <Input id="inv-due" type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
            {fieldError("dueDate") && <p className="text-caption text-destructive">{fieldError("dueDate")}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="inv-type">Invoice Type</Label>
            <Select value={invoiceType} onValueChange={(v) => setInvoiceType(v as InvoiceType)}>
              <SelectTrigger id="inv-type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {INVOICE_TYPES.map((t) => (
                  <SelectItem key={t.value} value={t.value}>
                    {t.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="inv-eway">E-way Bill</Label>
            <Input
              id="inv-eway"
              value={ewayBillNumber}
              onChange={(e) => setEwayBillNumber(e.target.value)}
              className="tabular"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="inv-irn">IRN</Label>
            <Input id="inv-irn" value={irn} onChange={(e) => setIrn(e.target.value)} className="tabular" />
          </div>
          <div className="space-y-1.5 sm:col-span-2 lg:col-span-2">
            <Label htmlFor="inv-notes">Notes</Label>
            <Input id="inv-notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>
        </div>
      </SectionCard>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <div className="xl:col-span-8">
          <SectionCard
            title="Items"
            description="Billed quantity and rate are editable — the point is to capture what the supplier actually charged"
          >
            {lines.length === 0 ? (
              <div className="p-8 text-center">
                <p className="text-[13.5px] text-muted-foreground">
                  Pick a supplier, PO and goods receipt above to load billable lines.
                </p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead className="pl-4">Product</TableHead>
                      <TableHead className="text-right">GRN Accepted</TableHead>
                      <TableHead className="w-24 text-right">Billed Qty</TableHead>
                      <TableHead className="text-right">PO Rate</TableHead>
                      <TableHead className="w-28 text-right">Billed Rate</TableHead>
                      <TableHead className="w-20 text-right">GST %</TableHead>
                      <TableHead className="pr-4 text-right">Total</TableHead>
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
                          <TableCell className="max-w-[220px] pl-4 align-top">
                            <span className="block truncate pt-2 font-medium text-foreground">
                              {line.productName}
                            </span>
                            <span className="block font-mono text-caption text-muted-foreground">
                              {line.sku} · {line.uomCode}
                            </span>
                          </TableCell>
                          <TableCell className="align-top text-right">
                            <span className="block pt-2 text-muted-foreground tabular">
                              {formatQuantity(line.grnAcceptedQuantity, 2)}
                            </span>
                          </TableCell>
                          <TableCell className="align-top">
                            <Input
                              type="number"
                              min={0}
                              value={line.quantity}
                              onChange={(e) => updateLine(line.key, { quantity: Number(e.target.value) })}
                              className="h-8.5 text-right tabular"
                            />
                            {err("quantity") && <p className="mt-1 text-caption text-destructive">{err("quantity")}</p>}
                          </TableCell>
                          <TableCell className="align-top text-right">
                            <span className="block pt-2 text-muted-foreground tabular">
                              {formatCurrency(line.poUnitPrice)}
                            </span>
                          </TableCell>
                          <TableCell className="align-top">
                            <Input
                              type="number"
                              min={0}
                              value={line.unitPrice}
                              onChange={(e) => updateLine(line.key, { unitPrice: Number(e.target.value) })}
                              className="h-8.5 text-right tabular"
                            />
                            {err("unitPrice") && <p className="mt-1 text-caption text-destructive">{err("unitPrice")}</p>}
                          </TableCell>
                          <TableCell className="align-top text-right">
                            <span className="block pt-2 tabular">{line.gstRate}%</span>
                          </TableCell>
                          <TableCell className="pr-4 align-top text-right">
                            <span className="block pt-2 font-medium text-foreground tabular">
                              {formatCurrency(lineTotals.lineTotal)}
                            </span>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            )}
          </SectionCard>
        </div>

        <div className="space-y-4 xl:col-span-4">
          <SectionCard title="Summary">
            <div className="space-y-3 p-4">
              <div className="space-y-1.5">
                <Label htmlFor="inv-freight">Freight</Label>
                <Input
                  id="inv-freight"
                  type="number"
                  min={0}
                  value={freight}
                  onChange={(e) => setFreight(Number(e.target.value))}
                  className="text-right tabular"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="inv-other">Other Charges</Label>
                <Input
                  id="inv-other"
                  type="number"
                  min={0}
                  value={otherCharges}
                  onChange={(e) => setOtherCharges(Number(e.target.value))}
                  className="text-right tabular"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="inv-tds">TDS Amount</Label>
                <Input
                  id="inv-tds"
                  type="number"
                  min={0}
                  value={tdsAmount}
                  onChange={(e) => setTdsAmount(Number(e.target.value))}
                  className="text-right tabular"
                />
              </div>
              <div className="border-t border-border pt-3">
                <TaxSummary money={totals} taxRows={taxRows} />
              </div>
            </div>
          </SectionCard>

          <Alert variant="info">
            <Info />
            <AlertDescription>
              Saving runs the three-way match immediately, comparing this invoice against the PO rate and the GRN
              accepted quantity on every line.
            </AlertDescription>
          </Alert>

          <Button
            className="w-full"
            disabled={create.isPending || lines.length === 0 || !invoiceNumber.trim() || !supplierId}
            onClick={() => create.run(buildInput())}
          >
            {create.isPending ? "Saving..." : "Save Invoice"}
          </Button>
        </div>
      </div>
    </div>
  );
}
