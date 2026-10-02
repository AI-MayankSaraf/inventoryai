"use client";

import * as React from "react";
import { ExternalLink, FileSpreadsheet, FileText, ImageIcon, Trash2, Upload } from "lucide-react";

import { FormError } from "@/components/common/async-state";
import { ConfirmButton } from "@/components/common/confirm-dialog";
import { EmptyState } from "@/components/common/empty-state";
import { PermissionGate } from "@/components/common/permission-gate";
import { SectionCard } from "@/components/common/section-card";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { useProductFiles, useRemoveProductFile, useUploadProductFile } from "@/hooks/use-catalog";
import { PRODUCT_FILE_ACCEPT, type ProductFile } from "@/lib/api/catalog.api";
import { formatDate } from "@/lib/format";
import type { Id } from "@/types";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Product photos, spec sheets and certificates. Files are private: every
 * link here is signed and expires in minutes (BR-DOC-03).
 */
export function ProductFilesCard({ variantId }: { variantId: Id }) {
  const files = useProductFiles(variantId);
  const upload = useUploadProductFile(variantId, files.refresh);
  const remove = useRemoveProductFile(files.refresh);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const pick = () => inputRef.current?.click();

  const onChosen = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const chosen = Array.from(event.target.files ?? []);
    // Cleared first, so picking the same file again after an error still
    // fires a change event.
    event.target.value = "";
    for (const file of chosen) {
      if ((await upload.run(file)) === undefined) break;
    }
  };

  const uploadButton = (
    <PermissionGate permission="product.update">
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={PRODUCT_FILE_ACCEPT}
        className="hidden"
        onChange={onChosen}
        data-testid="product-file-input"
      />
      <Button variant="outline" size="sm" onClick={pick} disabled={upload.isPending}>
        <Upload />
        {upload.isPending ? "Uploading..." : "Upload file"}
      </Button>
    </PermissionGate>
  );

  const list = files.data ?? [];

  return (
    <SectionCard title="Images & Documents" action={list.length > 0 ? uploadButton : undefined}>
      {files.isLoading ? (
        <p className="px-4 py-8 text-center text-[13px] text-muted-foreground">Loading files...</p>
      ) : list.length === 0 ? (
        <EmptyState
          icon={ImageIcon}
          title="No files yet"
          description="Product photos, spec sheets and certificates will appear here."
          action={uploadButton}
          className="py-8"
        />
      ) : (
        <ul className="divide-y divide-border">
          {list.map((file) => (
            <FileRow
              key={file.id}
              file={file}
              onRemove={() => remove.run(file.id).then(() => undefined)}
            />
          ))}
        </ul>
      )}
      <FormError message={upload.error ?? remove.error ?? files.error} className="m-3" />
    </SectionCard>
  );
}

function FileRow({
  file,
  onRemove,
}: {
  file: ProductFile;
  onRemove: () => Promise<void>;
}) {
  const Icon = file.isImage ? ImageIcon : file.extension === "xlsx" ? FileSpreadsheet : FileText;
  return (
    <li className="flex items-center gap-3 px-4 py-3" data-testid="product-file">
      <a
        href={file.url}
        target="_blank"
        rel="noopener noreferrer"
        className="flex size-12 shrink-0 items-center justify-center overflow-hidden rounded-md border border-border bg-muted text-muted-foreground"
        aria-label={`Open ${file.filename}`}
      >
        {file.isImage ? (
          // eslint-disable-next-line @next/next/no-img-element -- signed S3 URL, not an optimisable asset
          <img src={file.url} alt={file.filename} className="size-full object-cover" />
        ) : (
          <Icon className="size-5" />
        )}
      </a>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="truncate text-[13.5px] font-medium text-foreground">{file.filename}</span>
          {file.isPrimary && <StatusBadge status="active" label="Main photo" />}
        </span>
        <span className="block text-caption text-muted-foreground">
          {formatSize(file.sizeBytes)} · {formatDate(file.uploadedAt)}
          {file.uploadedByName && ` · ${file.uploadedByName}`}
        </span>
      </span>
      <Button variant="ghost" size="icon" className="size-7" asChild>
        <a href={file.url} target="_blank" rel="noopener noreferrer" aria-label={`Download ${file.filename}`}>
          <ExternalLink className="size-3.5" />
        </a>
      </Button>
      <PermissionGate permission="product.update">
        <ConfirmButton
          variant="ghost"
          size="icon"
          className="size-7"
          tone="destructive"
          aria-label={`Remove ${file.filename}`}
          title={`Remove ${file.filename}?`}
          description="The file is removed from this product. This cannot be undone."
          confirmLabel="Remove"
          onConfirm={onRemove}
        >
          <Trash2 className="size-3.5" />
        </ConfirmButton>
      </PermissionGate>
    </li>
  );
}
