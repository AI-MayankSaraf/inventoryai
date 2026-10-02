"use client";

import Link from "next/link";
import {
  CircleCheck,
  CircleX,
  Clock,
  Copy,
  FileSpreadsheet,
  FileText,
  ImageIcon,
  Loader2,
  Trash2,
  type LucideIcon,
} from "lucide-react";

import { ConfidenceMeter } from "@/components/ai/ai-provenance";
import { ConfirmButton } from "@/components/common/confirm-dialog";
import { PermissionGate } from "@/components/common/permission-gate";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { documentsApi } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { DocumentProcessingStatus, FileExtension } from "@/types";

type DocumentRow = Awaited<ReturnType<typeof documentsApi.listDocuments>>["items"][number];

const FILE_ICONS: Record<FileExtension, LucideIcon> = {
  xlsx: FileSpreadsheet,
  xls: FileSpreadsheet,
  csv: FileSpreadsheet,
  pdf: FileText,
  docx: FileText,
  jpg: ImageIcon,
  jpeg: ImageIcon,
  png: ImageIcon,
  webp: ImageIcon,
};

const STATE: Record<
  DocumentProcessingStatus,
  { label: string; variant: React.ComponentProps<typeof Badge>["variant"]; icon: LucideIcon }
> = {
  uploaded: { label: "Uploaded", variant: "neutral", icon: Clock },
  queued: { label: "Queued", variant: "neutral", icon: Clock },
  processing: { label: "Processing", variant: "info", icon: Loader2 },
  extracted: { label: "Extracted", variant: "warning", icon: Clock },
  review_required: { label: "Needs review", variant: "warning", icon: Clock },
  approved: { label: "Approved", variant: "success", icon: CircleCheck },
  rejected: { label: "Rejected", variant: "destructive", icon: CircleX },
  failed: { label: "Failed", variant: "destructive", icon: CircleX },
  duplicate: { label: "Duplicate", variant: "neutral", icon: Copy },
};

const TYPE_LABELS: Record<string, string> = {
  supplier_quotation: "Supplier Quotation",
  proforma_invoice: "Proforma Invoice",
  tax_invoice: "Tax Invoice",
  delivery_challan: "Delivery Challan",
  rate_list: "Rate List",
  price_revision: "Price Revision",
  purchase_order: "Purchase Order",
  other: "Other",
  unrecognised: "Unrecognised",
};

/** Approved documents back a business record, and one being read is in the
 * worker's hands; the server refuses both, so the button is not offered. */
function deletable(status: DocumentProcessingStatus): boolean {
  return !["approved", "queued", "processing", "uploaded"].includes(status);
}

export function DocumentTable({
  documents,
  onRetry,
  onDelete,
}: {
  documents: DocumentRow[];
  onRetry?: (documentId: string) => void;
  onDelete?: (documentId: string) => void | Promise<void>;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="pl-4">File</TableHead>
          <TableHead>Supplier</TableHead>
          <TableHead>Document Type</TableHead>
          <TableHead>Uploaded</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>AI Confidence</TableHead>
          <TableHead className="pr-4 text-right">Action</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {documents.map((doc) => {
          const FileIcon = FILE_ICONS[doc.fileExtension] ?? FileText;
          const state = STATE[doc.processingStatus];
          const StateIcon = state.icon;
          const needsReview =
            doc.processingStatus === "review_required" || doc.processingStatus === "extracted";

          return (
            <TableRow key={doc.id}>
              <TableCell className="pl-4">
                <span className="flex items-center gap-3">
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-muted text-muted-foreground">
                    <FileIcon className="size-4" strokeWidth={1.9} />
                  </span>
                  <span className="min-w-0">
                    <span className="block max-w-[230px] truncate font-medium text-foreground">
                      {doc.originalFilename}
                    </span>
                    <span className="block text-caption text-muted-foreground tabular">
                      {doc.sizeKb > 1024 ? `${(doc.sizeKb / 1024).toFixed(1)} MB` : `${doc.sizeKb} KB`}
                      {doc.itemsFound != null && ` · ${doc.itemsFound} items`}
                    </span>
                  </span>
                </span>
              </TableCell>

              <TableCell className="text-foreground">
                {doc.supplierId ? (
                  doc.supplierDisplayName
                ) : (
                  <span className="text-muted-foreground italic">Not identified</span>
                )}
              </TableCell>

              <TableCell className="text-muted-foreground">
                {TYPE_LABELS[doc.documentType] ?? doc.documentType}
              </TableCell>

              <TableCell className="text-muted-foreground">{formatDate(doc.uploadedAt)}</TableCell>

              <TableCell>
                <Badge variant={state.variant} className="gap-1">
                  <StateIcon
                    className={doc.processingStatus === "processing" ? "animate-spin" : undefined}
                  />
                  {state.label}
                </Badge>
                {doc.processingStatus === "processing" && (
                  <span className="mt-1.5 block w-[160px]">
                    <Progress value={doc.processingProgress ?? 0} />
                    <span className="mt-1 block text-[11px] text-muted-foreground">
                      {doc.processingStage}
                    </span>
                  </span>
                )}
                {doc.processingStatus === "failed" && doc.errorMessage && (
                  <span className="mt-1 block max-w-[220px] text-[11px] text-destructive">
                    {doc.errorMessage}
                  </span>
                )}
                {doc.processingStatus === "duplicate" && (
                  <span className="mt-1 block text-[11px] text-muted-foreground">
                    Same content as an earlier upload
                  </span>
                )}
              </TableCell>

              <TableCell>
                {doc.extractionConfidence != null ? (
                  <ConfidenceMeter value={doc.extractionConfidence} />
                ) : (
                  <span className="text-[12.5px] text-muted-foreground">—</span>
                )}
              </TableCell>

              <TableCell className="pr-4 text-right">
                {needsReview ? (
                  <Button size="sm" asChild>
                    <Link href={`/ai-documents/review/${doc.id}`}>Review</Link>
                  </Button>
                ) : doc.processingStatus === "approved" || doc.processingStatus === "rejected" ? (
                  <Button variant="outline" size="sm" asChild>
                    <Link href={`/ai-documents/review/${doc.id}`}>View</Link>
                  </Button>
                ) : doc.processingStatus === "failed" ? (
                  <Button variant="outline" size="sm" onClick={() => onRetry?.(doc.id)}>
                    Retry
                  </Button>
                ) : doc.processingStatus === "duplicate" ? (
                  <span className="text-[12.5px] text-muted-foreground">Skipped</span>
                ) : (
                  <span className="text-[12.5px] text-muted-foreground">Waiting…</span>
                )}
                {onDelete && deletable(doc.processingStatus) && (
                  <PermissionGate permission="document.delete">
                    <ConfirmButton
                      title="Delete this document?"
                      description={
                        <>
                          <span className="font-medium">{doc.originalFilename}</span> and what AI read
                          from it will be deleted. This cannot be undone. A document that became a
                          quotation, proforma or invoice is kept as that record&apos;s evidence.
                        </>
                      }
                      confirmLabel="Delete"
                      tone="destructive"
                      variant="ghost"
                      size="sm"
                      className="ml-1 text-muted-foreground"
                      aria-label={`Delete ${doc.originalFilename}`}
                      onConfirm={() => onDelete(doc.id)}
                    >
                      <Trash2 />
                    </ConfirmButton>
                  </PermissionGate>
                )}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
