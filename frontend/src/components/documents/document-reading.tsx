"use client";

import { FileSearch, RotateCcw, TriangleAlert } from "lucide-react";

import { FormError } from "@/components/common/async-state";
import { PermissionGate } from "@/components/common/permission-gate";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useRetryExtraction } from "@/hooks/use-documents";
import type { DocumentJobStatus } from "@/types";

/**
 * Shown on the review screen until the worker has read the document: the
 * upload returns as soon as the file is stored, and reading it (OCR of a
 * scanned PDF especially) happens in the background. The stage and
 * percentage are the worker's own, not a timer.
 */
export function DocumentReading({
  job,
  onRetried,
}: {
  job: DocumentJobStatus;
  onRetried: () => void;
}) {
  const retry = useRetryExtraction(onRetried);

  if (job.processingStatus === "failed") {
    return (
      <Card className="space-y-4 p-6">
        <Alert variant="destructive">
          <TriangleAlert />
          <AlertDescription>
            <span className="font-medium">This document could not be read.</span>{" "}
            {job.error?.message || "No reason was recorded."}
          </AlertDescription>
        </Alert>
        <FormError message={retry.error} />
        <PermissionGate permission="ai.review">
          <Button onClick={() => void retry.run(job.documentId)} disabled={retry.isPending}>
            <RotateCcw />
            {retry.isPending ? "Queuing…" : "Try reading it again"}
          </Button>
        </PermissionGate>
      </Card>
    );
  }

  const queued = job.processingStatus !== "processing";
  return (
    <Card className="space-y-4 p-6" data-testid="document-reading" aria-live="polite">
      <div className="flex items-center gap-3">
        <FileSearch className="size-5 text-primary" />
        <div>
          <p className="font-medium">{queued ? "Waiting to be read…" : "Reading the document…"}</p>
          <p className="text-body text-muted-foreground">
            {queued
              ? "It is next in line. This page updates by itself."
              : `${job.processingStage ?? "Working"} — scanned pages take a few seconds each. This page updates by itself.`}
          </p>
        </div>
      </div>
      <Progress value={queued ? 2 : Math.max(job.processingProgress, 5)} aria-label="Reading progress" />
    </Card>
  );
}
