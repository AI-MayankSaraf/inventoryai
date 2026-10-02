"use client";

/** Feature hooks for stored documents, the AI review queue and schema mappings. */

import { useCallback } from "react";
import { documentsApi } from "@/lib/api";
import type { DocumentProcessingStatus, Id, ListParams } from "@/types";
import { useApiMutation, useApiQuery } from "./use-api";

/** Queued or being read by the worker — the screen should keep asking. */
export function isBeingRead(status: DocumentProcessingStatus | undefined): boolean {
  return status === "queued" || status === "processing" || status === "uploaded";
}

export function useDocuments(params: ListParams) {
  return useApiQuery(["documents", params], () => documentsApi.listDocuments(params), {
    // Refresh the list while anything on it is still being read.
    pollWhile: (data) => (data?.items.some((d) => isBeingRead(d.processingStatus)) ? 3000 : false),
  });
}

export function useDocument(documentId: Id | undefined) {
  return useApiQuery(
    ["document", documentId],
    () => documentsApi.getDocument(documentId!),
    { enabled: !!documentId },
  );
}

export function useExtraction(documentId: Id | undefined, options: { enabled?: boolean } = {}) {
  return useApiQuery(
    ["extraction", documentId],
    () => documentsApi.getExtraction(documentId!),
    { enabled: !!documentId && (options.enabled ?? true) },
  );
}

/** Follows the worker: asks again every 1.5 s until the document is read. */
export function useDocumentJobStatus(documentId: Id | undefined) {
  return useApiQuery(
    ["document-job-status", documentId],
    () => documentsApi.getDocumentJobStatus(documentId!),
    {
      enabled: !!documentId,
      pollWhile: (job) => (job && isBeingRead(job.processingStatus) ? 1500 : false),
    },
  );
}

export function useRetryExtraction(onSuccess?: () => void) {
  return useApiMutation(documentsApi.retryExtraction, { onSuccess });
}

export function useDeleteDocument(onSuccess?: () => void) {
  return useApiMutation(documentsApi.deleteDocument, { onSuccess });
}

export function useSourceDocuments(linkedType: documentsApi.LinkedRecordType, linkedId: Id | undefined) {
  return useApiQuery(
    ["source-documents", linkedType, linkedId],
    () => documentsApi.getSourceDocuments(linkedType, linkedId!),
    { enabled: !!linkedId },
  );
}

export function useAttachments(linkedType: documentsApi.AttachableRecordType, linkedId: Id) {
  return useApiQuery(["attachments", linkedType, linkedId], () =>
    documentsApi.listAttachments(linkedType, linkedId),
  );
}

export function useUploadAttachment(onSuccess?: () => void) {
  return useApiMutation(documentsApi.uploadAttachment, { onSuccess: () => onSuccess?.() });
}

export function useRemoveAttachment(onSuccess?: () => void) {
  return useApiMutation(documentsApi.removeAttachment, { onSuccess: () => onSuccess?.() });
}

export function useUploadDocument(onSuccess?: (result: { document: { id: Id } }) => void) {
  return useApiMutation(documentsApi.uploadDocument, { onSuccess });
}

export function useConfirmLineMatch(onSuccess?: () => void) {
  const action = useCallback(
    (input: { extractedLineId: Id; productVariantId: Id; saveAlias?: boolean }) =>
      documentsApi.confirmLineMatch(input.extractedLineId, input.productVariantId, {
        saveAlias: input.saveAlias,
      }),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

export function useSkipExtractedLine(onSuccess?: () => void) {
  const action = useCallback(
    (input: { extractedLineId: Id; reason: string }) =>
      documentsApi.skipExtractedLine(input.extractedLineId, input.reason),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

export function useCorrectExtractedField(onSuccess?: () => void) {
  const action = useCallback(
    (input: { fieldId: Id; value: string }) => documentsApi.correctExtractedField(input.fieldId, input.value),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

export function useApproveExtraction(onSuccess?: (result: { promotedToId: Id }) => void) {
  const action = useCallback(
    (input: { documentId: Id; rfqId?: Id | null }) =>
      documentsApi.approveExtraction(input.documentId, { rfqId: input.rfqId }),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

export function useRejectExtraction(onSuccess?: () => void) {
  const action = useCallback(
    (input: { documentId: Id; reason: string }) => documentsApi.rejectExtraction(input.documentId, input.reason),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

export function useSuggestMatches(onSuccess?: () => void) {
  return useApiMutation(documentsApi.suggestMatches, { onSuccess });
}

export function useSchemaMappings(params: ListParams) {
  return useApiQuery(["schema-mappings", params], () => documentsApi.listSchemaMappings(params));
}

export function useSchemaMapping(mappingId: Id | undefined) {
  return useApiQuery(
    ["schema-mapping", mappingId],
    () => documentsApi.getSchemaMapping(mappingId!),
    { enabled: !!mappingId },
  );
}

export function useUpdateMappingField(mappingId: Id | undefined, onSuccess?: () => void) {
  const action = useCallback(
    (input: { fieldId: Id; patch: Parameters<typeof documentsApi.updateMappingField>[2] }) =>
      documentsApi.updateMappingField(mappingId!, input.fieldId, input.patch),
    [mappingId],
  );
  return useApiMutation(action, { onSuccess });
}

export function useConfirmSchemaMapping(onSuccess?: () => void) {
  return useApiMutation(documentsApi.confirmSchemaMapping, { onSuccess });
}

export function useAssistantSuggestions() {
  return useApiQuery(["assistant-suggestions"], () => documentsApi.getAssistantSuggestions());
}

export function useAssistant() {
  return useApiMutation(documentsApi.askAssistant);
}

/* Product embeddings */

export function useEmbeddingStatus(enabled = true) {
  return useApiQuery(["embedding-status"], () => documentsApi.getEmbeddingStatus(), { enabled });
}

export function useRebuildEmbeddings(onSuccess?: () => void) {
  return useApiMutation(documentsApi.rebuildEmbeddings, { onSuccess: () => onSuccess?.() });
}
