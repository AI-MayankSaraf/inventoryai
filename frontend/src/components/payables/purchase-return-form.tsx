"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { CalendarDays, CornerUpLeft, Info } from "lucide-react";

import { FormError } from "@/components/common/async-state";
import { PermissionGate } from "@/components/common/permission-gate";
import { SectionCard } from "@/components/common/section-card";
import { RETURN_REASON_LABELS } from "@/components/payables/purchase-return-list-screen";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
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
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useCreatePurchaseReturn } from "@/hooks/use-invoices";
import { useGoodsReceipt, useGoodsReceipts, useReturnableLines } from "@/hooks/use-receiving";
import { GRN_ISSUE_LABELS } from "@/lib/api/receiving.api";
import { computeLine, round2 } from "@/lib/domain/money";
import { PREVIEW_NUMBER_NOTE } from "@/lib/domain/numbering";
import { useNextDocumentNumber } from "@/hooks/use-admin";
import { formatCurrency, formatDate, formatQuantity } from "@/lib/format";
import type { GrnIssueType, Id, ReturnReason } from "@/types";

interface DraftLine {
  goodsReceiptItemId: Id;
  sku: string;
  productName: string;
  uomCode: string;
  unitPrice: number;
  gstRate: number;
  issueType: GrnIssueType;
  rejectedQuantity: number;
  alreadyReturned: number;
  returnableQuantity: number;
  suggestedQuantity: number;
  quantity: number;
  reason: ReturnReason;
  remarks: string;
}

function suggestReason(issueType: GrnIssueType): ReturnReason {
  switch (issueType) {
    case "damaged":
      return "damaged";
    case "expired":
      return "expired";
    case "wrong_product":
      return "wrong_product";
    case "wrong_variant":
      return "wrong_variant";
    case "excess":
      return "excess_supply";
    default:
      return "quality_rejected";
  }
}

const RETURN_REASONS = Object.keys(RETURN_REASON_LABELS) as ReturnReason[];
const today = () => new Date().toISOString().slice(0, 10);

/**
 * Raise a purchase return.
 *
 * Reached either from a GRN's detail screen (`?goodsReceiptId=...`), or, when
 * no receipt is pre-selected, by picking a confirmed one here. Every line
 * comes from `useReturnableLines`, which already explains *why* it can be
 * returned — the rejected quantity, what has already gone back, and what is
 * still returnable — so this form only ever asks for a quantity within that
 * limit. Confirming immediately posts a negative inventory transaction (I2);
 * saving a draft does not move any stock.
 */
export function PurchaseReturnForm({ goodsReceiptId }: { goodsReceiptId?: string }) {
  const router = useRouter();

  const [grnId, setGrnId] = React.useState<string | undefined>(goodsReceiptId);
  const [lines, setLines] = React.useState<DraftLine[]>([]);
  const [returnDate, setReturnDate] = React.useState(today());
  const [reason, setReason] = React.useState<ReturnReason>("quality_rejected");
  const [ewayBillNumber, setEwayBillNumber] = React.useState("");
  const [remarks, setRemarks] = React.useState("");

  const confirmedReceiptsState = useGoodsReceipts({ filters: { status: "received" }, limit: 200, sort: "-grnDate" });
  const grnDetailState = useGoodsReceipt(grnId);
  const returnableState = useReturnableLines(grnId);

  const create = useCreatePurchaseReturn((ret) => router.push(`/purchase-returns/${ret.id}`));

  React.useEffect(() => {
    if (!returnableState.data) {
      setLines([]);
      return;
    }
    setLines(
      returnableState.data.map((line) => ({
        goodsReceiptItemId: line.goodsReceiptItemId,
        sku: line.sku,
        productName: line.productName,
        uomCode: line.uomCode,
        unitPrice: line.unitPrice,
        gstRate: line.gstRate,
        issueType: line.issueType,
        rejectedQuantity: line.rejectedQuantity,
        alreadyReturned: line.alreadyReturned,
        returnableQuantity: line.returnableQuantity,
        suggestedQuantity: line.suggestedQuantity,
        quantity: line.suggestedQuantity,
        reason: suggestReason(line.issueType),
        remarks: "",
      })),
    );
  }, [returnableState.data]);

  function updateLine(goodsReceiptItemId: Id, patch: Partial<DraftLine>) {
    setLines((prev) => prev.map((l) => (l.goodsReceiptItemId === goodsReceiptItemId ? { ...l, ...patch } : l)));
  }

  const activeLines = lines.filter((l) => l.quantity > 0);
  const totalQuantity = round2(activeLines.reduce((sum, l) => sum + l.quantity, 0));
  const totalValue = round2(
    activeLines.reduce(
      (sum, l) => sum + computeLine({ quantity: l.quantity, unitPrice: l.unitPrice, gstRate: l.gstRate }).lineTotal,
      0,
    ),
  );

  const numberPreview = useNextDocumentNumber("return");
  const godownName = grnDetailState.data?.godownName ?? "the receiving godown";
  const fieldError = (key: string) => create.fieldErrors[key];

  function buildInput() {
    return {
      goodsReceiptId: grnId as Id,
      returnDate,
      reason,
      remarks: remarks || undefined,
      ewayBillNumber: ewayBillNumber || undefined,
      lines: activeLines.map((l) => ({
        goodsReceiptItemId: l.goodsReceiptItemId,
        quantity: l.quantity,
        reason: l.reason,
        remarks: l.remarks || undefined,
      })),
    };
  }

  return (
    <div className="space-y-4">
      <FormError message={create.error} fieldErrors={create.fieldErrors} />

      <SectionCard
        title="Goods Receipt"
        description="Every returnable line is read from this confirmed receipt"
      >
        <div className="p-4">
          {goodsReceiptId ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div className="space-y-1.5">
                <Label>GRN Number</Label>
                <Input value={grnDetailState.data?.goodsReceipt.grnNumber ?? "…"} readOnly className="bg-muted font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label>Supplier</Label>
                <Input value={grnDetailState.data?.supplierName ?? ""} readOnly className="bg-muted" />
              </div>
              <div className="space-y-1.5">
                <Label>Related PO</Label>
                <Input value={grnDetailState.data?.poNumber ?? "—"} readOnly className="bg-muted" />
              </div>
            </div>
          ) : (
            <div className="max-w-[420px] space-y-1.5">
              <Label htmlFor="return-grn">Confirmed Goods Receipt</Label>
              <Select
                value={grnId}
                onValueChange={(v) => setGrnId(v)}
              >
                <SelectTrigger id="return-grn">
                  <SelectValue placeholder="Select the receipt to return against..." />
                </SelectTrigger>
                <SelectContent>
                  {(confirmedReceiptsState.data?.items ?? []).map((g) => (
                    <SelectItem key={g.id} value={g.id}>
                      {g.grnNumber} · {g.supplierName} · {formatDate(g.grnDate)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {fieldError("goodsReceiptId") && (
                <p className="text-caption text-destructive">{fieldError("goodsReceiptId")}</p>
              )}
            </div>
          )}
        </div>
      </SectionCard>

      <SectionCard title="Return Details">
        <div className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-1.5">
            <Label htmlFor="return-number">
              Return Number <span className="font-normal text-muted-foreground">(preview)</span>
            </Label>
            <Input id="return-number" value={numberPreview} readOnly className="bg-muted" />
            <p className="text-caption text-muted-foreground">{PREVIEW_NUMBER_NOTE}</p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="return-date">Return Date</Label>
            <div className="relative">
              <Input
                id="return-date"
                type="date"
                value={returnDate}
                onChange={(e) => setReturnDate(e.target.value)}
                className="pr-9"
              />
              <CalendarDays className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground" />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="return-reason">Reason</Label>
            <Select value={reason} onValueChange={(v) => setReason(v as ReturnReason)}>
              <SelectTrigger id="return-reason">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {RETURN_REASONS.map((r) => (
                  <SelectItem key={r} value={r}>
                    {RETURN_REASON_LABELS[r]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="return-eway">E-way Bill</Label>
            <Input
              id="return-eway"
              value={ewayBillNumber}
              onChange={(e) => setEwayBillNumber(e.target.value)}
              className="tabular"
            />
          </div>
          <div className="space-y-1.5 sm:col-span-2 lg:col-span-4">
            <Label htmlFor="return-remarks">Remarks</Label>
            <Textarea
              id="return-remarks"
              value={remarks}
              onChange={(e) => setRemarks(e.target.value)}
              placeholder="Optional note for the supplier or for your own records"
            />
          </div>
        </div>
      </SectionCard>

      <SectionCard
        title="Returnable Lines"
        description="Only lines with something rejected or still returnable are listed, with why each one qualifies"
      >
        {!grnId ? (
          <div className="p-8 text-center">
            <p className="text-[13.5px] text-muted-foreground">Select a goods receipt above to load its lines.</p>
          </div>
        ) : lines.length === 0 ? (
          <div className="p-8 text-center">
            <p className="text-[13.5px] text-muted-foreground">
              Nothing on this receipt is still returnable — every rejected unit has already gone back.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="pl-4">Product</TableHead>
                  <TableHead>Why Returnable</TableHead>
                  <TableHead className="text-right">Rejected</TableHead>
                  <TableHead className="text-right">Already Returned</TableHead>
                  <TableHead className="text-right">Returnable</TableHead>
                  <TableHead className="w-24 text-right">Return Qty</TableHead>
                  <TableHead className="w-[160px]">Line Reason</TableHead>
                  <TableHead className="pr-4 text-right">Line Total</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {lines.map((line) => {
                  const lineTotal = computeLine({
                    quantity: line.quantity,
                    unitPrice: line.unitPrice,
                    gstRate: line.gstRate,
                  }).lineTotal;
                  return (
                    <TableRow key={line.goodsReceiptItemId} className="hover:bg-transparent">
                      <TableCell className="max-w-[200px] pl-4 align-top">
                        <span className="block truncate pt-2 font-medium text-foreground">{line.productName}</span>
                        <span className="block font-mono text-caption text-muted-foreground">
                          {line.sku} · {line.uomCode}
                        </span>
                      </TableCell>
                      <TableCell className="align-top">
                        <span className="mt-2 inline-block">
                          <Badge variant={line.issueType === "damaged" || line.issueType === "expired" ? "destructive" : "warning"}>
                            {GRN_ISSUE_LABELS[line.issueType]}
                          </Badge>
                        </span>
                      </TableCell>
                      <TableCell className="align-top text-right">
                        <span className="block pt-2 text-muted-foreground tabular">
                          {formatQuantity(line.rejectedQuantity, 2)}
                        </span>
                      </TableCell>
                      <TableCell className="align-top text-right">
                        <span className="block pt-2 text-muted-foreground tabular">
                          {formatQuantity(line.alreadyReturned, 2)}
                        </span>
                      </TableCell>
                      <TableCell className="align-top text-right">
                        <span className="block pt-2 font-medium text-foreground tabular">
                          {formatQuantity(line.returnableQuantity, 2)}
                        </span>
                      </TableCell>
                      <TableCell className="align-top">
                        <Input
                          type="number"
                          min={0}
                          max={line.returnableQuantity}
                          value={line.quantity}
                          onChange={(e) =>
                            updateLine(line.goodsReceiptItemId, {
                              quantity: Math.min(Number(e.target.value), line.returnableQuantity),
                            })
                          }
                          className="h-8.5 text-right tabular"
                        />
                      </TableCell>
                      <TableCell className="align-top">
                        <Select
                          value={line.reason}
                          onValueChange={(v) => updateLine(line.goodsReceiptItemId, { reason: v as ReturnReason })}
                        >
                          <SelectTrigger size="sm">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {RETURN_REASONS.map((r) => (
                              <SelectItem key={r} value={r}>
                                {RETURN_REASON_LABELS[r]}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </TableCell>
                      <TableCell className="pr-4 align-top text-right">
                        <span className="block pt-2 font-medium tabular">{formatCurrency(lineTotal)}</span>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}

        {lines.length > 0 && (
          <div className="flex flex-wrap items-center gap-3 border-t border-border px-4 py-3">
            <span className="text-[13px] text-muted-foreground">
              {activeLines.length} of {lines.length} line{lines.length === 1 ? "" : "s"} selected ·{" "}
              {formatQuantity(totalQuantity, 2)} units · {formatCurrency(totalValue)}
            </span>
          </div>
        )}
      </SectionCard>

      <Alert variant="info">
        <Info />
        <AlertDescription>
          Confirming this return posts a negative inventory transaction for every selected line right away and
          removes those units from stock at {godownName}. Saving as a draft does not move any stock.
        </AlertDescription>
      </Alert>

      <div className="sticky bottom-0 z-20 flex flex-col gap-2 rounded-xl border border-border bg-card/95 px-4 py-3 shadow-elevated backdrop-blur sm:flex-row sm:items-center">
        <p className="text-[13px] text-muted-foreground">
          {activeLines.length === 0
            ? "Set a quantity on at least one line to continue"
            : `${formatQuantity(totalQuantity, 2)} units across ${activeLines.length} line${activeLines.length === 1 ? "" : "s"}`}
        </p>
        <div className="flex items-center gap-2 sm:ml-auto">
          <PermissionGate permission="return.create">
            <Button
              variant="outline"
              disabled={create.isPending || !grnId || activeLines.length === 0}
              onClick={() => create.run({ data: buildInput(), confirmNow: false })}
            >
              Save Draft
            </Button>
          </PermissionGate>
          <PermissionGate permission="return.create">
            <Button
              disabled={create.isPending || !grnId || activeLines.length === 0}
              onClick={() => create.run({ data: buildInput(), confirmNow: true })}
            >
              <CornerUpLeft />
              {create.isPending ? "Confirming..." : "Confirm Return — Removes Stock"}
            </Button>
          </PermissionGate>
        </div>
      </div>
    </div>
  );
}
