"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { CalendarDays, Plus, Save, Send, Trash2, X } from "lucide-react";

import { ConfirmButton } from "@/components/common/confirm-dialog";
import { FormError } from "@/components/common/async-state";
import { PrintHeader } from "@/components/common/print-header";
import { PermissionGate } from "@/components/common/permission-gate";
import { SectionCard } from "@/components/common/section-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
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
import { useCreateRfq } from "@/hooks/use-procurement";
import { useSuppliers } from "@/hooks/use-suppliers";
import { SupplierFormDialog } from "@/components/suppliers/supplier-form-dialog";
import { formatCurrency } from "@/lib/format";
import { PREVIEW_NUMBER_NOTE } from "@/lib/domain/numbering";
import type { procurementApi } from "@/lib/api";
import type { Id } from "@/types";

let nextRowKey = 1;

interface LineRow {
  key: string;
  productVariantId: Id | "";
  quantity: number;
  uomId: Id | "";
  expectedPrice: number;
  remarks: string;
}

function blankLine(): LineRow {
  return { key: `l${nextRowKey++}`, productVariantId: "", quantity: 1, uomId: "", expectedPrice: 0, remarks: "" };
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

export function RfqForm() {
  const router = useRouter();

  const previewNumber = useNextDocumentNumber("rfq");
  const company = useCompanySettings();
  const productsState = useProducts({ limit: 500, sort: "name" });
  const uomsState = useUoms();
  const godownsState = useGodowns();
  const suppliersState = useSuppliers({ limit: 200 });

  const products = productsState.data?.items ?? [];
  const uoms = uomsState.data ?? [];
  const godowns = godownsState.data ?? [];
  const suppliers = (suppliersState.data?.items ?? []).filter((s) => s.status === "active");

  const [subject, setSubject] = React.useState("");
  const [rfqDate, setRfqDate] = React.useState(todayIso());
  const [expectedDeliveryDate, setExpectedDeliveryDate] = React.useState("");
  const [deliveryGodownId, setDeliveryGodownId] = React.useState<Id | "">("");
  const [notes, setNotes] = React.useState(
    "Please provide your best price, delivery period and payment terms. Quote GST separately.",
  );
  const [supplierIds, setSupplierIds] = React.useState<Id[]>([]);
  const [items, setItems] = React.useState<LineRow[]>(() => [blankLine()]);

  const create = useCreateRfq((rfq) => router.push(`/procurement/rfq/${rfq.id}`));

  const estimatedValue = items.reduce((sum, item) => sum + item.quantity * item.expectedPrice, 0);

  function updateItem(key: string, patch: Partial<LineRow>) {
    setItems((prev) => prev.map((item) => (item.key === key ? { ...item, ...patch } : item)));
  }

  function handleProductChange(key: string, productVariantId: Id) {
    const product = products.find((p) => p.id === productVariantId);
    const uom = uoms.find((u) => u.code === product?.uomCode);
    updateItem(key, {
      productVariantId,
      uomId: uom?.id ?? "",
      expectedPrice: product?.purchasePrice ?? 0,
    });
  }

  function addItem() {
    setItems((prev) => [...prev, blankLine()]);
  }

  function fieldError(index: number, field: string): string | undefined {
    return create.fieldErrors[`items.${index}.${field}`];
  }

  function buildInput(): procurementApi.RfqInput {
    return {
      subject: subject.trim(),
      rfqDate,
      expectedDeliveryDate: expectedDeliveryDate || null,
      deliveryGodownId: deliveryGodownId || null,
      notes,
      supplierIds,
      items: items
        .filter((item) => item.productVariantId)
        .map((item) => ({
          productVariantId: item.productVariantId as Id,
          quantity: item.quantity,
          uomId: item.uomId as Id,
          expectedPrice: item.expectedPrice,
          remarks: item.remarks || undefined,
        })),
      createdFrom: "manual",
    };
  }

  function submit(sendNow: boolean) {
    create.run({ data: buildInput(), sendNow });
  }

  const address = company.data
    ? [company.data.company.addressLine1, company.data.company.addressLine2, company.data.company.city]
        .filter(Boolean)
        .join(", ")
    : undefined;

  return (
    <div className="space-y-4">
      <PrintHeader
        company={company.data?.company.name ?? ""}
        gstin={company.data?.company.gstin}
        address={address}
        email={company.data?.company.email}
        phone={company.data?.company.phone}
        docLabel={`Request for Quotation — ${previewNumber}`}
      />

      <FormError message={create.error} fieldErrors={create.fieldErrors} />

      <SectionCard title="Basic Information">
        <div className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-1.5">
            <Label htmlFor="rfq-number">
              RFQ Number <span className="font-normal text-muted-foreground">(preview)</span>
            </Label>
            <Input id="rfq-number" value={previewNumber} readOnly className="bg-muted tabular" />
            <p className="text-[11px] text-muted-foreground">{PREVIEW_NUMBER_NOTE}</p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rfq-date">RFQ Date</Label>
            <div className="relative">
              <Input
                id="rfq-date"
                type="date"
                value={rfqDate}
                onChange={(e) => setRfqDate(e.target.value)}
                className="pr-9"
              />
              <CalendarDays className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground" />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rfq-delivery">Expected Delivery Date</Label>
            <div className="relative">
              <Input
                id="rfq-delivery"
                type="date"
                value={expectedDeliveryDate}
                onChange={(e) => setExpectedDeliveryDate(e.target.value)}
                className="pr-9"
              />
              <CalendarDays className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground" />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rfq-godown">Deliver To</Label>
            <Select value={deliveryGodownId} onValueChange={(v) => setDeliveryGodownId(v)}>
              <SelectTrigger id="rfq-godown">
                <SelectValue placeholder="Select godown" />
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

          <div className="space-y-1.5 sm:col-span-2 lg:col-span-4">
            <Label htmlFor="rfq-subject">Subject</Label>
            <Input
              id="rfq-subject"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder="What is this RFQ for?"
            />
            {create.fieldErrors.subject && (
              <p className="text-[12px] text-destructive">{create.fieldErrors.subject}</p>
            )}
          </div>
        </div>
      </SectionCard>

      <SectionCard
        title="Select Suppliers"
        description="Quotations will be requested from everyone selected"
      >
        <div className="space-y-3 p-4">
          <div className="flex flex-wrap gap-2">
            {supplierIds.map((id) => {
              const supplier = suppliers.find((s) => s.id === id);
              return (
                <span
                  key={id}
                  className="inline-flex items-center gap-1.5 rounded-md border border-primary/25 bg-primary-subtle px-2.5 py-1 text-[12.5px] font-medium text-primary-subtle-foreground"
                >
                  {supplier?.name ?? id}
                  <button
                    type="button"
                    aria-label={`Remove ${supplier?.name ?? id}`}
                    onClick={() => setSupplierIds((prev) => prev.filter((s) => s !== id))}
                    className="rounded transition-colors hover:bg-primary/15"
                  >
                    <X className="size-3.5" />
                  </button>
                </span>
              );
            })}
            {supplierIds.length === 0 && (
              <p className="text-[13px] text-muted-foreground">
                No suppliers selected yet — pick at least one below.
              </p>
            )}
          </div>
          {create.fieldErrors.suppliers && (
            <p className="text-[12px] text-destructive">{create.fieldErrors.suppliers}</p>
          )}

          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <Select
              value=""
              onValueChange={(value) =>
                setSupplierIds((prev) => (prev.includes(value) ? prev : [...prev, value]))
              }
            >
              <SelectTrigger className="sm:max-w-[340px]">
                <SelectValue placeholder="Add a supplier..." />
              </SelectTrigger>
              <SelectContent>
                {suppliers.map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.name} · {s.city}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <PermissionGate permission="supplier.create">
              <SupplierFormDialog
                trigger={
                  <Button variant="outline" size="sm" data-testid="rfq-form-new-supplier">
                    <Plus />
                    Add new supplier
                  </Button>
                }
                onSaved={(created) => {
                  // Straight onto this RFQ — the reason it was created.
                  suppliersState.refresh();
                  setSupplierIds((prev) => (prev.includes(created.id) ? prev : [...prev, created.id]));
                }}
              />
            </PermissionGate>
          </div>
        </div>
      </SectionCard>

      <SectionCard
        title="Items"
        description="Pick a product from your catalogue for each line"
        action={
          <Button variant="outline" size="sm" onClick={addItem}>
            <Plus />
            Add Item
          </Button>
        }
      >
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-10 pl-4">#</TableHead>
              <TableHead>Product</TableHead>
              <TableHead className="w-[104px] text-right">Qty</TableHead>
              <TableHead className="w-28">Unit</TableHead>
              <TableHead className="w-32 text-right">Expected Price</TableHead>
              <TableHead className="w-28 text-right">Value</TableHead>
              <TableHead className="w-10 pr-3" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item, index) => {
              const product = products.find((p) => p.id === item.productVariantId);
              const uom = uoms.find((u) => u.id === item.uomId);
              return (
                <TableRow key={item.key} className="hover:bg-transparent">
                  <TableCell className="pl-4 align-top text-muted-foreground tabular">
                    <span className="inline-block pt-2.5">{index + 1}</span>
                  </TableCell>

                  <TableCell className="align-top whitespace-normal">
                    <Select
                      value={item.productVariantId || undefined}
                      onValueChange={(v) => handleProductChange(item.key, v)}
                    >
                      <SelectTrigger>
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
                    {product && (
                      <span className="mt-1 block text-caption text-muted-foreground">
                        {product.sku} · {uom?.code ?? product.uomCode}
                      </span>
                    )}
                    {fieldError(index, "quantity") && (
                      <p className="mt-1 text-[11.5px] text-destructive">{fieldError(index, "quantity")}</p>
                    )}
                  </TableCell>

                  <TableCell className="align-top">
                    <Input
                      type="number"
                      min={1}
                      value={item.quantity}
                      onChange={(e) => updateItem(item.key, { quantity: Number(e.target.value) })}
                      className="text-right tabular"
                    />
                  </TableCell>

                  <TableCell className="align-top text-muted-foreground">
                    <span className="inline-block pt-2.5">{uom?.code ?? "—"}</span>
                  </TableCell>

                  <TableCell className="align-top">
                    <Input
                      type="number"
                      min={0}
                      value={item.expectedPrice}
                      onChange={(e) => updateItem(item.key, { expectedPrice: Number(e.target.value) })}
                      className="text-right tabular"
                    />
                  </TableCell>

                  <TableCell className="align-top text-right font-medium text-foreground tabular">
                    <span className="inline-block pt-2.5">
                      {formatCurrency(item.quantity * item.expectedPrice)}
                    </span>
                  </TableCell>

                  <TableCell className="pr-3 align-top">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Remove item"
                      className="mt-1 text-muted-foreground hover:text-destructive"
                      onClick={() => setItems((prev) => prev.filter((i) => i.key !== item.key))}
                    >
                      <Trash2 />
                    </Button>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>

        {create.fieldErrors.items && (
          <p className="px-4 pt-2 text-[12px] text-destructive">{create.fieldErrors.items}</p>
        )}

        <div className="flex items-center justify-between border-t border-border px-4 py-3">
          <span className="text-[13px] text-muted-foreground">
            {items.length} item{items.length === 1 ? "" : "s"} · estimated value
          </span>
          <span className="text-[15px] font-semibold text-foreground tabular">
            {formatCurrency(estimatedValue)}
          </span>
        </div>
      </SectionCard>

      <SectionCard title="Notes to Suppliers">
        <div className="p-4">
          <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} />
        </div>
      </SectionCard>

      <div className="sticky bottom-0 z-20 flex flex-col gap-2 rounded-xl border border-border bg-card/95 px-4 py-3 shadow-elevated backdrop-blur sm:flex-row sm:items-center">
        <p className="text-[13px] text-muted-foreground">
          Sending to <span className="font-medium text-foreground">{supplierIds.length}</span> supplier
          {supplierIds.length === 1 ? "" : "s"} · {items.length} items
        </p>
        <div className="flex items-center gap-2 sm:ml-auto">
          <Button variant="outline" onClick={() => submit(false)} disabled={create.isPending}>
            <Save />
            Save Draft
          </Button>
          <ConfirmButton
            title="Send this RFQ to your suppliers?"
            description={`${supplierIds.length} supplier${supplierIds.length === 1 ? "" : "s"} will be emailed a request for quotation.`}
            confirmLabel="Send"
            disabled={create.isPending || supplierIds.length === 0}
            onConfirm={() => submit(true)}
          >
            <Send />
            {create.isPending ? "Sending..." : "Send RFQ"}
          </ConfirmButton>
        </div>
      </div>
    </div>
  );
}
