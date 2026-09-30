"use client";

import * as React from "react";
import { Download, FileText } from "lucide-react";

import { FormError } from "@/components/common/async-state";
import { PermissionGate } from "@/components/common/permission-gate";
import { SectionCard } from "@/components/common/section-card";
import { Button } from "@/components/ui/button";
import { useSourceDocuments } from "@/hooks/use-documents";
import { documentsApi, errorMessage } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { Id } from "@/types";

/**
 * "Source document": the uploaded file a quotation, proforma or invoice was
 * read from. Renders nothing for a record typed in by hand. The file opens
 * through a 5-minute signed link, fetched when the button is pressed.
 */
export function SourceDocumentsCard({
  linkedType,
  linkedId,
}: {
  linkedType: documentsApi.LinkedRecordType;
  linkedId: Id;
}) {
  const sources = useSourceDocuments(linkedType, linkedId);
  const [opening, setOpening] = React.useState<Id | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  if (!sources.data?.length) return null;

  async function open(documentId: Id) {
    setOpening(documentId);
    setError(null);
    try {
      window.open(await documentsApi.getDownloadLink(documentId), "_blank", "noopener");
    } catch (e) {
      setError(errorMessage(e, "Could not open the file."));
    } finally {
      setOpening(null);
    }
  }

  return (
    <SectionCard
      title="Source document"
      description="The uploaded file this record was read from"
      bodyClassName="px-4 py-3"
    >
      <ul className="space-y-2" data-testid="source-documents">
        {sources.data.map((doc) => (
          <li key={doc.id} className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2">
              <FileText className="size-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0">
                <p className="truncate text-body font-medium">{doc.originalFilename}</p>
                {doc.uploadedAt && (
                  <p className="text-caption text-muted-foreground">Uploaded {formatDate(doc.uploadedAt)}</p>
                )}
              </div>
            </div>
            <PermissionGate permission="document.download">
              <Button
                variant="outline"
                size="sm"
                onClick={() => void open(doc.id)}
                disabled={opening === doc.id}
                aria-label={`Open ${doc.originalFilename}`}
              >
                <Download />
                Open
              </Button>
            </PermissionGate>
          </li>
        ))}
      </ul>
      <FormError message={error} className="mt-2" />
    </SectionCard>
  );
}
