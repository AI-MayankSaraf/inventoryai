"use client";

import { useRouter } from "next/navigation";
import { Info } from "lucide-react";

import { AsyncBoundary, FormError } from "@/components/common/async-state";
import { PageHeader } from "@/components/common/page-header";
import { SectionCard } from "@/components/common/section-card";
import { DocumentDropzone } from "@/components/documents/document-dropzone";
import { DocumentTable } from "@/components/documents/document-table";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card } from "@/components/ui/card";
import { useListControls } from "@/hooks/use-api";
import {
  useDeleteDocument,
  useDocuments,
  useRetryExtraction,
  useUploadDocument,
} from "@/hooks/use-documents";

export default function AiDocumentsPage() {
  const router = useRouter();
  const controls = useListControls({ sort: "-uploadedAt" });
  const state = useDocuments(controls.params);

  const upload = useUploadDocument((result) => {
    router.push(`/ai-documents/review/${result.document.id}`);
  });
  const retry = useRetryExtraction(state.refresh);
  const remove = useDeleteDocument(state.refresh);

  async function handleFiles(files: File[]) {
    // The server stores the file and queues it; a background worker reads
    // it. The review screen shows its progress.
    for (const file of files) {
      await upload.run({ file });
    }
  }

  const needsReview = (state.data?.items ?? []).filter(
    (d) => d.processingStatus === "review_required" || d.processingStatus === "extracted",
  ).length;

  return (
    <div className="space-y-5">
      <PageHeader
        title="AI Document Processing"
        description="Upload a supplier quotation, proforma, invoice or challan — AI reads it and you approve the result"
      />

      <Card className="p-4">
        <DocumentDropzone onFiles={handleFiles} />
        <FormError message={upload.error ?? retry.error ?? remove.error} className="mt-3" />
        {upload.data?.duplicateOf && (
          <p className="mt-3 rounded-lg border border-border bg-muted/50 px-3 py-2 text-body text-muted-foreground">
            This file has the same content as{" "}
            <span className="font-medium text-foreground">
              {upload.data.duplicateOf.originalFilename}
            </span>
            , uploaded earlier. It was not processed again.
          </p>
        )}
      </Card>

      <Alert variant="ai">
        <Info />
        <AlertDescription>
          The file is read on the server right after you upload it — usually within seconds, a
          minute for a long scanned PDF: the document type, the supplier, the header fields and every
          line are extracted, and each line is matched against your own catalogue. Nothing enters your inventory or purchase records until you review and approve
          it — and the totals are recalculated from the lines you approve, never taken from the
          printed page.
        </AlertDescription>
      </Alert>

      <SectionCard
        title="Uploaded Documents"
        description={
          needsReview > 0
            ? `${needsReview} document${needsReview === 1 ? "" : "s"} waiting for your review`
            : "All documents processed"
        }
      >
        <AsyncBoundary state={state}>
          {(data) => (
            <DocumentTable
              documents={data.items}
              onRetry={(documentId) => {
                void retry.run(documentId);
              }}
              onDelete={async (documentId) => {
                await remove.run(documentId);
              }}
            />
          )}
        </AsyncBoundary>
      </SectionCard>
    </div>
  );
}
