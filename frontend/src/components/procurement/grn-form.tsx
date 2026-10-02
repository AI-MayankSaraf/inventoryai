"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  CalendarDays,
  Import,
  Info,
  PackageSearch,
  TriangleAlert,
  Truck,
  X,
} from "lucide-react";

import { FormError } from "@/components/common/async-state";
import { AttachmentsCard, FileDropZone, fileIcon, formatFileSize } from "@/components/documents/attachments";
import { ConfirmButton } from "@/components/common/confirm-dialog";
import { PermissionGate } from "@/components/common/permission-gate";
import { PrintHeader } from "@/components/common/print-header";
import { SectionCard } from "@/components/common/section-card";
import { StatusBadge } from "@/components/common/status-badge";
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
import { useGodowns } from "@/hooks/use-catalog";
import { usePurchaseOrders } from "@/hooks/use-procurement";
import {
  useCreateGoodsReceipt,
  useGoodsReceipt,
  useReceiptLines,
  useUpdateDraftGoodsReceipt,
} from "@/hooks/use-receiving";
import { useSession } from "@/hooks/use-session";
import { documentsApi } from "@/lib/api";
import { GRN_ISSUE_LABELS } from "@/lib/api/receiving.api";
import { PREVIEW_NUMBER_NOTE } from "@/lib/domain/numbering";
import { useNextDocumentNumber } from "@/hooks/use-admin";
import { useUnsavedChangesGuard } from "@/lib/unsaved-changes";
import { cn } from "@/lib/utils";
import type { GrnIssueType, PurchaseOrderStatus, ReceiptLine } from "@/types";

/** POs goods can be received against — mirrors the server's BR-GRN-12 list. */
const RECEIVABLE_PO_STATUSES: PurchaseOrderStatus[] = ["approved", "sent", "acknowledged", "partially_received"];

/**
 * Goods receipt entry.
 *
 * The correction this form exists to make: the quantity column starts from the
 * **pending balance**, not the ordered quantity. A PO line for 10 that has
 * already had 8 received shows 2 pending, so receiving the same goods twice is
 * visibly impossible rather than merely discouraged (C10, BR-GRN-03).
 *
 * Nothing here posts stock. Confirming calls the receiving service, which
 * posts the ledger rows, advances the PO, records variances and raises alerts
 * in one operation — and the receipt's detail screen then shows exactly what
 * that did.
 */

interface LineDraft {
  purchaseOrderItemId: string;
  productVariantId: string;
  sku: string;
  productName: string;
  uomId: string;
  uomCode: string;
  orderedQuantity: number;
  previouslyReceivedQuantity: number;
  pendingQuantity: number;
  requiresBatch: boolean;
  receivedQuantity: number;
  acceptedQuantity: number;
  issueType: GrnIssueType;
  rejectionReason: string;
  remarks: string;
  batchNumber: string;
  manufacturedOn: string;
  expiresOn: string;
}

function toDraft(line: ReceiptLine): LineDraft {
  return {
    purchaseOrderItemId: line.purchaseOrderItemId,
    productVariantId: line.productVariantId,
    sku: line.sku,
    productName: line.productName,
    uomId: line.uomId,
    uomCode: line.uomCode,
    orderedQuantity: line.orderedQuantity,
    previouslyReceivedQuantity: line.previouslyReceivedQuantity,
    pendingQuantity: line.pendingQuantity,
    requiresBatch: line.requiresBatch,
    receivedQuantity: line.suggestedReceivedQuantity,
    acceptedQuantity: line.suggestedReceivedQuantity,
    issueType: "none",
    rejectionReason: "",
    remarks: "",
    batchNumber: "",
    manufacturedOn: "",
    expiresOn: "",
  };
}

/** Compared against the PENDING balance, not the original order quantity. */
function detectIssue(line: LineDraft): GrnIssueType {
  if (!["none", "short", "excess"].includes(line.issueType)) return line.issueType;
  if (line.receivedQuantity < line.pendingQuantity) return "short";
  if (line.receivedQuantity > line.pendingQuantity) return "excess";
  return "none";
}

const today = () => new Date().toISOString().slice(0, 10);

export function GrnForm({
  purchaseOrderId,
  goodsReceiptId,
}: {
  purchaseOrderId?: string;
  /** Set to edit an existing draft instead of creating a new receipt. */
  goodsReceiptId?: string;
}) {
  const router = useRouter();
  const { user } = useSession();
  const isEdit = !!goodsReceiptId;

  const [poId, setPoId] = React.useState<string | undefined>(purchaseOrderId);
  const [lines, setLines] = React.useState<LineDraft[]>([]);
  const [importedFrom, setImportedFrom] = React.useState<string | null>(null);
  const [dirty, setDirty] = React.useState(false);
  const [header, setHeader] = React.useState({
    grnDate: today(),
    godownId: "",
    vehicleNumber: "",
    transporterName: "",
    lrNumber: "",
    ewayBillNumber: "",
    supplierChallanNumber: "",
    supplierChallanDate: "",
    remarks: "",
  });

  const ordersQuery = usePurchaseOrders({ limit: 200, sort: "-poDate" });
  const receiptLines = useReceiptLines(poId);
  const godownsQuery = useGodowns();
  // Edit mode: the draft itself, loaded once and used to seed the form.
  const draftQuery = useGoodsReceipt(goodsReceiptId);
  const draft = draftQuery.data;
  const [seeded, setSeeded] = React.useState(false);

  const openOrders = React.useMemo(
    () =>
      (ordersQuery.data?.items ?? []).filter(
        // The server's own list (`_PO_LINKABLE_STATUSES`, BR-GRN-12). A
        // "not draft/cancelled/closed" check let a PO still awaiting
        // approval through, and saving then failed.
        (po) => RECEIVABLE_PO_STATUSES.includes(po.status) && po.receivedPct < 100,
      ),
    [ordersQuery.data],
  );
  const selectedPo = openOrders.find((po) => po.id === poId);

  // The PO's delivery godown is the default receiving location.
  React.useEffect(() => {
    if (selectedPo && !header.godownId) {
      setHeader((prev) => ({ ...prev, godownId: selectedPo.deliveryGodownId }));
    }
  }, [selectedPo, header.godownId]);

  React.useEffect(() => {
    // Creating: importing a PO replaces the lines with its pending balance.
    // Editing: the draft's own lines are the truth, so this must not run.
    if (isEdit) return;
    if (receiptLines.data) {
      setLines(receiptLines.data.filter((l) => l.pendingQuantity > 0).map(toDraft));
      setImportedFrom(selectedPo?.poNumber ?? null);
    }
  }, [isEdit, receiptLines.data, selectedPo?.poNumber]);

  // Seed the form from the draft being edited — once, so typing is not
  // overwritten by a background refresh.
  React.useEffect(() => {
    if (!isEdit || seeded || !draft) return;
    const grn = draft.goodsReceipt;
    setPoId(grn.purchaseOrderId ?? undefined);
    setHeader({
      grnDate: grn.grnDate.slice(0, 10),
      godownId: grn.godownId,
      vehicleNumber: grn.vehicleNumber ?? "",
      transporterName: grn.transporterName ?? "",
      lrNumber: grn.lrNumber ?? "",
      ewayBillNumber: grn.ewayBillNumber ?? "",
      supplierChallanNumber: grn.supplierChallanNumber ?? "",
      supplierChallanDate: grn.supplierChallanDate ?? "",
      remarks: grn.remarks ?? "",
    });
    setLines(
      draft.items.map((item) => ({
        purchaseOrderItemId: item.purchaseOrderItemId ?? "",
        productVariantId: item.productVariantId,
        sku: item.sku,
        productName: item.productName,
        uomId: item.uomId,
        uomCode: item.uomCode,
        orderedQuantity: item.orderedQuantity ?? item.receivedQuantity,
        previouslyReceivedQuantity: item.previouslyReceivedQuantity ?? 0,
        // A draft holds no stock, so the PO line's pending balance still
        // includes what this receipt is claiming.
        pendingQuantity: Math.max(
          0,
          (item.orderedQuantity ?? item.receivedQuantity) - (item.previouslyReceivedQuantity ?? 0),
        ),
        requiresBatch: !!item.batchNumber,
        receivedQuantity: item.receivedQuantity,
        acceptedQuantity: item.acceptedQuantity,
        issueType: item.issueType,
        rejectionReason: item.rejectionReason ?? "",
        remarks: item.remarks ?? "",
        batchNumber: item.batchNumber ?? "",
        manufacturedOn: item.manufacturedOn ?? "",
        expiresOn: item.expiresOn ?? "",
      })),
    );
    setImportedFrom(draft.poNumber);
    setSeeded(true);
  }, [isEdit, seeded, draft]);

  // A new receipt does not exist until it is saved, so the files chosen
  // for it wait here and are attached once it has an id.
  const [pendingFiles, setPendingFiles] = React.useState<File[]>([]);
  const [fileProblem, setFileProblem] = React.useState<string | null>(null);
  const [attaching, setAttaching] = React.useState(false);

  function addFiles(chosen: File[]) {
    const problems = chosen.map(documentsApi.attachmentProblem).filter(Boolean);
    setFileProblem(problems.length ? problems.join(" ") : null);
    const ok = chosen.filter((f) => !documentsApi.attachmentProblem(f));
    setPendingFiles((prev) => [
      ...prev,
      ...ok.filter((f) => !prev.some((p) => p.name === f.name && p.size === f.size)),
    ]);
    if (ok.length) setDirty(true);
  }

  const create = useCreateGoodsReceipt(async (grn) => {
    setDirty(false);
    let failed = 0;
    if (pendingFiles.length) {
      setAttaching(true);
      for (const file of pendingFiles) {
        try {
          await documentsApi.uploadAttachment({ linkedType: "goods_receipt", linkedId: grn.id, file });
        } catch {
          failed += 1;
        }
      }
    }
    // The receipt is saved either way; the detail page says which files to add again.
    router.push(`/goods-receipt/${grn.id}${failed ? `?attach_failed=${failed}` : ""}`);
  });
  const saveEdit = useUpdateDraftGoodsReceipt(
    goodsReceiptId ?? "",
    draft?.goodsReceipt.rowVersion ?? 0,
    (grn) => {
      setDirty(false);
      router.push(`/goods-receipt/${grn.id}`);
    },
  );
  const mutation = isEdit ? saveEdit : create;

  useUnsavedChangesGuard(dirty && !mutation.isPending);

  const numberPreview = useNextDocumentNumber("grn");

  function update(index: number, patch: Partial<LineDraft>) {
    setLines((prev) =>
      prev.map((line, i) => {
        if (i !== index) return line;
        const next = { ...line, ...patch };
        next.acceptedQuantity = Math.min(next.acceptedQuantity, next.receivedQuantity);
        next.issueType = detectIssue(next);
        return next;
      }),
    );
    setDirty(true);
  }

  const rejectedOf = (line: LineDraft) =>
    Math.max(0, line.receivedQuantity - line.acceptedQuantity);
  const issues = lines.filter((l) => l.issueType !== "none" || rejectedOf(l) > 0);
  const totalAccepted = lines.reduce((sum, l) => sum + l.acceptedQuantity, 0);
  const allPendingCleared =
    lines.length > 0 && lines.every((l) => l.receivedQuantity >= l.pendingQuantity);
  const godownName =
    godownsQuery.data?.find((g) => g.id === header.godownId)?.name ?? "the selected godown";

  function buildInput() {
    return {
      supplierId: draft?.goodsReceipt.supplierId ?? selectedPo?.supplierId ?? "",
      purchaseOrderId: poId ?? null,
      godownId: header.godownId,
      grnDate: header.grnDate,
      vehicleNumber: header.vehicleNumber,
      transporterName: header.transporterName,
      lrNumber: header.lrNumber,
      ewayBillNumber: header.ewayBillNumber,
      supplierChallanNumber: header.supplierChallanNumber,
      supplierChallanDate: header.supplierChallanDate || null,
      remarks: header.remarks,
      lines: lines.map((line) => ({
        purchaseOrderItemId: line.purchaseOrderItemId,
        productVariantId: line.productVariantId,
        receivedQuantity: line.receivedQuantity,
        acceptedQuantity: line.acceptedQuantity,
        uomId: line.uomId,
        issueType: line.issueType,
        rejectionReason: line.rejectionReason || undefined,
        remarks: line.remarks,
        batch: line.batchNumber
          ? {
              batchNumber: line.batchNumber,
              manufacturedOn: line.manufacturedOn || null,
              expiresOn: line.expiresOn || null,
            }
          : null,
      })),
    };
  }

  const fieldError = (key: string) => mutation.fieldErrors[key];

  return (
    <div className="space-y-4">
      <PrintHeader
        company={user?.companyName ?? "InventoryAI"}
        docLabel={`Goods Receipt Note — ${numberPreview} (internal document)`}
      />

      <FormError message={mutation.error} fieldErrors={mutation.fieldErrors} />

      <SectionCard
        title={isEdit ? "Receiving against" : "Receive against a Purchase Order"}
        description={
          isEdit
            ? "The order a receipt was raised against cannot be changed — cancel the draft and start again instead"
            : "Pick an open PO — its unreceived balance fills in below"
        }
        className="print:hidden"
      >
        <div className="flex flex-col gap-2.5 p-4 sm:flex-row sm:items-end">
          <div className="w-full space-y-1.5 sm:max-w-[420px]">
            <Label htmlFor="grn-import-po">Purchase Order</Label>
            <Select
              value={poId}
              disabled={isEdit}
              onValueChange={(value) => {
                setPoId(value);
                setHeader((prev) => ({ ...prev, godownId: "" }));
                setDirty(true);
              }}
            >
              <SelectTrigger id="grn-import-po">
                <SelectValue placeholder="Select a PO to receive against..." />
              </SelectTrigger>
              <SelectContent>
                {openOrders.map((po) => (
                  <SelectItem key={po.id} value={po.id}>
                    {po.poNumber} · {po.supplierName} · {Math.round(po.receivedPct)}% received
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {importedFrom && lines.length > 0 && (
            <span className="flex items-center gap-1.5 pb-1.5 text-[12.5px] font-medium text-success-subtle-foreground">
              <Import className="size-3.5" />
              {lines.length} line{lines.length === 1 ? "" : "s"} still pending on {importedFrom}
            </span>
          )}
          {importedFrom && lines.length === 0 && (
            <span className="flex items-center gap-1.5 pb-1.5 text-[12.5px] font-medium text-muted-foreground">
              Nothing left to receive on {importedFrom}.
            </span>
          )}
        </div>
      </SectionCard>

      <SectionCard title="Receipt Details">
        <div className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-1.5">
            <Label htmlFor="grn-number">
              GRN Number{!isEdit && <span className="font-normal text-muted-foreground"> (preview)</span>}
            </Label>
            <Input
              id="grn-number"
              value={isEdit ? draft?.goodsReceipt.grnNumber ?? "" : numberPreview}
              readOnly
              className="bg-muted"
            />
            {!isEdit && <p className="text-caption text-muted-foreground">{PREVIEW_NUMBER_NOTE}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="grn-date">Date</Label>
            <div className="relative">
              <Input
                id="grn-date"
                type="date"
                value={header.grnDate}
                onChange={(e) => {
                  setHeader((p) => ({ ...p, grnDate: e.target.value }));
                  setDirty(true);
                }}
                className="pr-9"
              />
              <CalendarDays className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground" />
            </div>
            {fieldError("grnDate") && (
              <p className="text-caption text-destructive">{fieldError("grnDate")}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="grn-supplier">Supplier</Label>
            <Input
              id="grn-supplier"
              value={isEdit ? draft?.supplierName ?? "" : selectedPo?.supplierName ?? ""}
              readOnly
              className="bg-muted"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="grn-po">Related PO</Label>
            <Input
              id="grn-po"
              value={isEdit ? draft?.poNumber ?? "" : selectedPo?.poNumber ?? ""}
              readOnly
              className="bg-muted"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="grn-godown">Godown</Label>
            <Select
              value={header.godownId || undefined}
              onValueChange={(godownId) => {
                setHeader((prev) => ({ ...prev, godownId }));
                setDirty(true);
              }}
            >
              <SelectTrigger id="grn-godown">
                <SelectValue placeholder="Select godown" />
              </SelectTrigger>
              <SelectContent>
                {(godownsQuery.data ?? []).map((godown) => (
                  <SelectItem key={godown.id} value={godown.id}>
                    {godown.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {fieldError("godownId") && (
              <p className="text-caption text-destructive">{fieldError("godownId")}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="grn-received-by">Received By</Label>
            <Input id="grn-received-by" value={user?.fullName ?? ""} readOnly className="bg-muted" />
          </div>
        </div>
      </SectionCard>

      <SectionCard title="Transport Details" description="Needed for GST and dispute handling">
        <div className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-1.5">
            <Label htmlFor="grn-vehicle">Vehicle Number</Label>
            <div className="relative">
              <Input
                id="grn-vehicle"
                value={header.vehicleNumber}
                onChange={(e) => setHeader((p) => ({ ...p, vehicleNumber: e.target.value }))}
                className="pr-9"
              />
              <Truck className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground" />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="grn-transporter">Transporter</Label>
            <Input
              id="grn-transporter"
              value={header.transporterName}
              onChange={(e) => setHeader((p) => ({ ...p, transporterName: e.target.value }))}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="grn-lr">LR Number</Label>
            <Input
              id="grn-lr"
              value={header.lrNumber}
              onChange={(e) => setHeader((p) => ({ ...p, lrNumber: e.target.value }))}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="grn-eway">E-way Bill</Label>
            <Input
              id="grn-eway"
              value={header.ewayBillNumber}
              onChange={(e) => setHeader((p) => ({ ...p, ewayBillNumber: e.target.value }))}
              className="tabular"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="grn-challan">Supplier Challan No.</Label>
            <Input
              id="grn-challan"
              value={header.supplierChallanNumber}
              onChange={(e) => setHeader((p) => ({ ...p, supplierChallanNumber: e.target.value }))}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="grn-challan-date">Challan Date</Label>
            <Input
              id="grn-challan-date"
              type="date"
              value={header.supplierChallanDate}
              onChange={(e) => setHeader((p) => ({ ...p, supplierChallanDate: e.target.value }))}
            />
          </div>
        </div>
      </SectionCard>

      <SectionCard
        title="Items Received"
        description="Quantities start from what is still pending on the PO, not the original order"
      >
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-4">Product</TableHead>
                <TableHead className="w-20 text-right">Ordered</TableHead>
                <TableHead className="w-24 text-right">Already recd.</TableHead>
                <TableHead className="w-20 text-right">Pending</TableHead>
                <TableHead className="w-24 text-right">Received</TableHead>
                <TableHead className="w-24 text-right">Accepted</TableHead>
                <TableHead className="w-20 text-right">Rejected</TableHead>
                <TableHead className="w-[168px]">Issue</TableHead>
                <TableHead className="pr-4">Notes</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {lines.map((line, index) => {
                const rejected = rejectedOf(line);
                const short = line.receivedQuantity < line.pendingQuantity;
                const excess = line.receivedQuantity > line.pendingQuantity;
                const cannotAccept =
                  line.issueType === "wrong_product" || line.issueType === "wrong_variant";

                return (
                  <TableRow key={line.purchaseOrderItemId} className="hover:bg-transparent">
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
                        {line.orderedQuantity}
                      </span>
                    </TableCell>

                    <TableCell className="align-top text-right">
                      <span className="block pt-2 text-muted-foreground tabular">
                        {line.previouslyReceivedQuantity}
                      </span>
                    </TableCell>

                    <TableCell className="align-top text-right">
                      <span className="block pt-2 font-medium text-foreground tabular">
                        {line.pendingQuantity}
                      </span>
                    </TableCell>

                    <TableCell className="align-top">
                      <Input
                        type="number"
                        min={0}
                        aria-label={`Received quantity for ${line.sku}`}
                        value={line.receivedQuantity}
                        onChange={(e) =>
                          update(index, { receivedQuantity: Number(e.target.value) })
                        }
                        className={cn(
                          "h-8.5 text-right tabular",
                          (short || excess) && "border-warning ring-2 ring-warning/20",
                        )}
                      />
                      {fieldError(`lines.${index}.receivedQuantity`) && (
                        <p className="mt-1 text-caption text-destructive">
                          {fieldError(`lines.${index}.receivedQuantity`)}
                        </p>
                      )}
                    </TableCell>

                    <TableCell className="align-top">
                      <Input
                        type="number"
                        min={0}
                        max={line.receivedQuantity}
                        aria-label={`Accepted quantity for ${line.sku}`}
                        value={line.acceptedQuantity}
                        onChange={(e) =>
                          update(index, { acceptedQuantity: Number(e.target.value) })
                        }
                        className={cn("h-8.5 text-right tabular", cannotAccept && "border-destructive")}
                      />
                      {cannotAccept && line.acceptedQuantity > 0 && (
                        <p className="mt-1 text-caption text-destructive">
                          A wrong product can&apos;t go into stock — set this to 0 and raise a
                          return.
                        </p>
                      )}
                      {fieldError(`lines.${index}.acceptedQuantity`) && (
                        <p className="mt-1 text-caption text-destructive">
                          {fieldError(`lines.${index}.acceptedQuantity`)}
                        </p>
                      )}
                    </TableCell>

                    <TableCell className="align-top text-right">
                      <span
                        className={cn(
                          "block pt-2 font-medium tabular",
                          rejected > 0 ? "text-destructive" : "text-muted-foreground",
                        )}
                      >
                        {rejected}
                      </span>
                    </TableCell>

                    <TableCell className="align-top">
                      <Select
                        value={line.issueType}
                        onValueChange={(issueType) =>
                          update(index, { issueType: issueType as GrnIssueType })
                        }
                      >
                        <SelectTrigger size="sm" aria-label={`Issue for ${line.sku}`}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {(Object.keys(GRN_ISSUE_LABELS) as GrnIssueType[]).map((key) => (
                            <SelectItem key={key} value={key}>
                              {GRN_ISSUE_LABELS[key]}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      {short && (
                        <span className="mt-1 flex items-center gap-1 text-[11.5px] font-medium text-warning-subtle-foreground">
                          <TriangleAlert className="size-3" />
                          Short by {line.pendingQuantity - line.receivedQuantity} {line.uomCode}
                        </span>
                      )}
                      {excess && (
                        <span className="mt-1 flex items-center gap-1 text-[11.5px] font-medium text-warning-subtle-foreground">
                          <TriangleAlert className="size-3" />
                          {line.receivedQuantity - line.pendingQuantity} {line.uomCode} more than
                          pending
                        </span>
                      )}
                    </TableCell>

                    <TableCell className="min-w-[220px] space-y-1.5 pr-4 align-top">
                      {rejected > 0 && (
                        <Input
                          value={line.rejectionReason}
                          placeholder="Why was the balance rejected?"
                          aria-label={`Rejection reason for ${line.sku}`}
                          onChange={(e) => update(index, { rejectionReason: e.target.value })}
                          className="h-8.5"
                        />
                      )}
                      {line.requiresBatch && (
                        <div className="space-y-1.5 rounded-md border border-border bg-muted/40 p-2">
                          <Input
                            value={line.batchNumber}
                            placeholder="Batch number (required)"
                            aria-label={`Batch number for ${line.sku}`}
                            onChange={(e) => update(index, { batchNumber: e.target.value })}
                            className="h-8"
                          />
                          <div className="flex gap-1.5">
                            <Input
                              type="date"
                              value={line.manufacturedOn}
                              aria-label={`Manufactured on for ${line.sku}`}
                              onChange={(e) => update(index, { manufacturedOn: e.target.value })}
                              className="h-8 text-[12px]"
                            />
                            <Input
                              type="date"
                              value={line.expiresOn}
                              aria-label={`Expires on for ${line.sku}`}
                              onChange={(e) => update(index, { expiresOn: e.target.value })}
                              className="h-8 text-[12px]"
                            />
                          </div>
                          {fieldError(`lines.${index}.batch`) && (
                            <p className="text-caption text-destructive">
                              {fieldError(`lines.${index}.batch`)}
                            </p>
                          )}
                        </div>
                      )}
                      {/* BR-GRN-05: any line with an issue or a rejected
                          quantity must say what happened, so the note is
                          only optional when the line went to plan. */}
                      <Input
                        value={line.remarks}
                        placeholder={
                          line.issueType !== "none" || rejectedOf(line) > 0
                            ? "Required — what happened?"
                            : "Optional note"
                        }
                        aria-label={`Remarks for ${line.sku}`}
                        onChange={(e) => update(index, { remarks: e.target.value })}
                        className="h-8.5"
                      />
                      {fieldError(`lines.${index}.rejectionReason`) && (
                        <p className="text-caption text-destructive">
                          {fieldError(`lines.${index}.rejectionReason`)}
                        </p>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}

              {lines.length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={9} className="px-4 py-8 text-center text-body text-muted-foreground">
                    Choose a purchase order above to load its pending lines.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>

        {lines.length > 0 && (
          <div className="flex flex-wrap items-center gap-3 border-t border-border px-4 py-3">
            <StatusBadge status={allPendingCleared ? "received" : "partially_received"} />
            <span className="text-[13px] text-muted-foreground">
              {totalAccepted} units will be posted to {godownName}
            </span>
          </div>
        )}
      </SectionCard>

      {issues.length > 0 && (
        <SectionCard
          title="Mismatches Detected"
          description="These become variances against the PO when you confirm"
        >
          <ul className="divide-y divide-border">
            {issues.map((line) => (
              <li key={line.purchaseOrderItemId} className="flex items-start gap-3 px-4 py-3">
                <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg bg-warning-subtle text-warning-subtle-foreground">
                  <TriangleAlert className="size-3.5" strokeWidth={2} />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-[13.5px] font-medium text-foreground">
                    {line.productName} · {GRN_ISSUE_LABELS[line.issueType]}
                  </p>
                  <p className="text-caption text-muted-foreground">
                    {line.pendingQuantity} pending, received {line.receivedQuantity}, accepted{" "}
                    {line.acceptedQuantity}
                    {rejectedOf(line) > 0 && `, rejected ${rejectedOf(line)}`}
                    {line.remarks && ` — ${line.remarks}`}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </SectionCard>
      )}

      {isEdit && goodsReceiptId ? (
        <AttachmentsCard
          linkedType="goods_receipt"
          linkedId={goodsReceiptId}
          editPermissions={["grn.create", "grn.update"]}
          description="Delivery challan, invoice or photos"
          dropTitle="Upload delivery challan, invoice or any document"
        />
      ) : (
        <SectionCard
          title="Documents"
          description="Delivery challan, invoice or photos — attached when you save"
          className="print:hidden"
        >
          <div className="space-y-3 p-4">
            {pendingFiles.length > 0 && (
              <ul className="divide-y divide-border rounded-lg border border-border" data-testid="pending-attachments">
                {pendingFiles.map((file) => {
                  const Icon = fileIcon((file.name.split(".").pop() ?? "").toLowerCase());
                  return (
                    <li key={`${file.name}-${file.size}`} className="flex items-center gap-3 px-3 py-2.5">
                      <Icon className="size-4 shrink-0 text-muted-foreground" />
                      <span className="min-w-0 flex-1 truncate text-[13.5px] text-foreground">{file.name}</span>
                      <span className="text-caption text-muted-foreground">{formatFileSize(file.size)}</span>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-7"
                        aria-label={`Remove ${file.name}`}
                        onClick={() => setPendingFiles((prev) => prev.filter((p) => p !== file))}
                      >
                        <X className="size-3.5" />
                      </Button>
                    </li>
                  );
                })}
              </ul>
            )}
            <FileDropZone
              onFiles={addFiles}
              busy={attaching}
              disabled={attaching}
              title="Upload delivery challan, invoice or any document"
              hint="Drag & drop files here or click to browse (PDF, Word, Excel, images)"
            />
            <FormError message={fileProblem} />
          </div>
        </SectionCard>
      )}

      <Alert variant="info">
        <Info />
        <AlertDescription>
          Confirming posts one inventory transaction per accepted line, advances the purchase
          order&apos;s receipt progress, and records a variance wherever the quantity differs from
          the order. The receipt cannot be edited afterwards — a mistake is corrected with a
          reversing receipt.
        </AlertDescription>
      </Alert>

      <div className="sticky bottom-0 z-20 flex flex-col gap-2 rounded-xl border border-border bg-card/95 px-4 py-3 shadow-elevated backdrop-blur sm:flex-row sm:items-center print:hidden">
        <p className="text-[13px] text-muted-foreground">
          {lines.length === 0
            ? "Select a purchase order to begin"
            : issues.length === 0
              ? "No mismatches — ready to confirm"
              : `${issues.length} mismatch${issues.length === 1 ? "" : "es"} noted on this receipt`}
        </p>
        <div className="flex items-center gap-2 sm:ml-auto">
          {isEdit ? (
            <>
              <Button variant="outline" asChild disabled={mutation.isPending}>
                <Link href={`/goods-receipt/${goodsReceiptId}`}>Cancel</Link>
              </Button>
              <Button
                disabled={mutation.isPending || lines.length === 0}
                onClick={() => saveEdit.run(buildInput())}
              >
                <PackageSearch />
                {mutation.isPending ? "Saving..." : "Save Changes"}
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="outline"
                disabled={create.isPending || lines.length === 0}
                onClick={() => create.run({ data: buildInput(), confirmNow: false })}
              >
                Save Draft
              </Button>
              <PermissionGate permission="grn.confirm">
                <ConfirmButton
                  title="Confirm this goods receipt?"
                  description="This posts an inventory transaction for every accepted line, advances the purchase order and cannot be edited afterwards."
                  confirmLabel="Confirm Receipt"
                  disabled={create.isPending || lines.length === 0}
                  onConfirm={async () => {
                    await create.run({ data: buildInput(), confirmNow: true });
                  }}
                >
                  <PackageSearch />
                  {create.isPending ? "Confirming..." : "Confirm Receipt"}
                </ConfirmButton>
              </PermissionGate>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
