"use client";

import * as React from "react";
import { ExternalLink, FileSpreadsheet, FileText, FileUp, ImageIcon, Loader2, Trash2 } from "lucide-react";

import { FormError } from "@/components/common/async-state";
import { ConfirmButton } from "@/components/common/confirm-dialog";
import { PermissionGate } from "@/components/common/permission-gate";
import { SectionCard } from "@/components/common/section-card";
import { Button } from "@/components/ui/button";
import { useAttachments, useRemoveAttachment, useUploadAttachment } from "@/hooks/use-documents";
import { ATTACHMENT_ACCEPT, type AttachableRecordType } from "@/lib/api/documents.api";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Id, PermissionCode } from "@/types";

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function fileIcon(extension: string) {
  if (["jpg", "jpeg", "png", "webp"].includes(extension)) return ImageIcon;
  if (extension === "xlsx" || extension === "xls" || extension === "csv") return FileSpreadsheet;
  return FileText;
}

/** Click to browse or drop files on it. Hands the files over; uploading is the caller's job. */
export function FileDropZone({
  onFiles,
  title,
  hint,
  disabled,
  busy,
}: {
  onFiles: (files: File[]) => void;
  title: string;
  hint: string;
  disabled?: boolean;
  busy?: boolean;
}) {
  const [dragging, setDragging] = React.useState(false);
  return (
    <label
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        if (!disabled && e.dataTransfer.files.length) onFiles(Array.from(e.dataTransfer.files));
      }}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-border bg-muted/40 px-6 py-7 text-center transition-colors hover:border-primary/45 hover:bg-primary-subtle/35",
        dragging && "border-primary/60 bg-primary-subtle/45",
        disabled && "pointer-events-none opacity-60",
      )}
    >
      <input
        type="file"
        multiple
        accept={ATTACHMENT_ACCEPT}
        className="hidden"
        disabled={disabled}
        data-testid="attachment-input"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          // Cleared so choosing the same file again still fires.
          e.target.value = "";
          if (files.length) onFiles(files);
        }}
      />
      {busy ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : (
        <FileUp className="size-5 text-muted-foreground" strokeWidth={1.9} />
      )}
      <span className="mt-2 text-[13.5px] font-medium text-foreground">{busy ? "Uploading..." : title}</span>
      <span className="mt-0.5 text-caption text-muted-foreground">{hint}</span>
    </label>
  );
}

/**
 * Files attached to a saved record — a GRN's delivery challan, invoice or
 * photos. Each link is signed and expires in minutes (BR-DOC-03).
 */
export function AttachmentsCard({
  linkedType,
  linkedId,
  editPermissions,
  title = "Documents",
  description,
  dropTitle,
  notice,
}: {
  linkedType: AttachableRecordType;
  linkedId: Id;
  editPermissions: PermissionCode[];
  title?: string;
  description?: string;
  dropTitle: string;
  /** Shown above the list — e.g. files that failed to upload when the record was saved. */
  notice?: string | null;
}) {
  const files = useAttachments(linkedType, linkedId);
  const upload = useUploadAttachment();
  const remove = useRemoveAttachment(files.refresh);
  const [uploading, setUploading] = React.useState(false);

  async function onFiles(chosen: File[]) {
    setUploading(true);
    for (const file of chosen) {
      if ((await upload.run({ linkedType, linkedId, file })) === undefined) break;
    }
    setUploading(false);
    files.refresh();
  }

  const list = files.data ?? [];

  return (
    <SectionCard title={title} description={description} className="print:hidden">
      <div className="space-y-3 p-4">
        {notice && <FormError message={notice} />}
        {list.length > 0 && (
          <ul className="divide-y divide-border rounded-lg border border-border" data-testid="attachments">
            {list.map((file) => {
              const Icon = fileIcon(file.extension);
              return (
                <li key={file.linkId} className="flex items-center gap-3 px-3 py-2.5" data-testid="attachment">
                  <a
                    href={file.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex size-10 shrink-0 items-center justify-center overflow-hidden rounded-md border border-border bg-muted text-muted-foreground"
                    aria-label={`Open ${file.filename}`}
                  >
                    {file.isImage ? (
                      // eslint-disable-next-line @next/next/no-img-element -- signed S3 URL, not an optimisable asset
                      <img src={file.url} alt={file.filename} className="size-full object-cover" />
                    ) : (
                      <Icon className="size-4.5" />
                    )}
                  </a>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13.5px] font-medium text-foreground">{file.filename}</span>
                    <span className="block text-caption text-muted-foreground">
                      {formatFileSize(file.sizeBytes)} · {formatDate(file.uploadedAt)}
                      {file.uploadedByName && ` · ${file.uploadedByName}`}
                    </span>
                  </span>
                  <Button variant="ghost" size="icon" className="size-7" asChild>
                    <a href={file.url} target="_blank" rel="noopener noreferrer" aria-label={`Download ${file.filename}`}>
                      <ExternalLink className="size-3.5" />
                    </a>
                  </Button>
                  <PermissionGate anyOf={editPermissions}>
                    <ConfirmButton
                      variant="ghost"
                      size="icon"
                      className="size-7"
                      tone="destructive"
                      aria-label={`Remove ${file.filename}`}
                      title={`Remove ${file.filename}?`}
                      description="The file is removed from this record. This cannot be undone."
                      confirmLabel="Remove"
                      onConfirm={() => remove.run({ linkedType, linkedId, linkId: file.linkId }).then(() => undefined)}
                    >
                      <Trash2 className="size-3.5" />
                    </ConfirmButton>
                  </PermissionGate>
                </li>
              );
            })}
          </ul>
        )}
        {files.isLoading && <p className="text-caption text-muted-foreground">Loading files...</p>}
        <PermissionGate
          anyOf={editPermissions}
          fallback={
            !files.isLoading && list.length === 0 ? (
              <p className="text-caption text-muted-foreground">No documents attached.</p>
            ) : null
          }
        >
          <FileDropZone
            onFiles={onFiles}
            busy={uploading}
            disabled={uploading}
            title={dropTitle}
            hint="Drag & drop files here or click to browse (PDF, Word, Excel, images)"
          />
        </PermissionGate>
        <FormError message={upload.error ?? remove.error ?? files.error} />
      </div>
    </SectionCard>
  );
}
