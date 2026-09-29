"use client";

import Link from "next/link";
import { ArrowRight, FileSpreadsheet, Info } from "lucide-react";

import { AsyncBoundary, FormError } from "@/components/common/async-state";
import { PageHeader } from "@/components/common/page-header";
import { PermissionButton } from "@/components/common/permission-gate";
import { SectionCard } from "@/components/common/section-card";
import { StatusBadge } from "@/components/common/status-badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { useListControls } from "@/hooks/use-api";
import {
  useConfirmSchemaMapping,
  useSchemaMapping,
  useSchemaMappings,
  useUpdateMappingField,
} from "@/hooks/use-documents";
import { formatDate } from "@/lib/format";
import type { MappingTransform } from "@/types";

/**
 * Schema mappings.
 *
 * Suppliers send the same information under different column headings. A
 * mapping records, once, which of a supplier's columns means which *business*
 * field — `unit_price`, not "Basic Rate" — so the next file from that supplier
 * imports without review. Mapping to canonical business meaning rather than to
 * physical column names is what makes the mapping reusable when the supplier
 * reorders or renames their columns.
 */

const TRANSFORMS: { value: MappingTransform; label: string }[] = [
  { value: "none", label: "No change" },
  { value: "trim", label: "Trim spaces" },
  { value: "upper", label: "Upper case" },
  { value: "strip_currency", label: "Strip ₹ and commas" },
  { value: "parse_indian_number", label: "Parse 1,00,000 format" },
  { value: "percent_to_decimal", label: "Percent → number" },
  { value: "date_ddmmyyyy", label: "Date dd-mm-yyyy" },
  { value: "multiply", label: "Multiply by factor" },
];

const FORMAT_LABELS: Record<string, string> = {
  xlsx: "Excel",
  csv: "CSV",
  pdf_table: "PDF table",
  docx: "Word",
};

export function SchemaMappingsScreen() {
  const controls = useListControls({ sort: "-lastUsedAt" });
  const state = useSchemaMappings(controls.params);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Schema Mappings"
        description="How each supplier's file columns map to your business fields"
      />

      <Alert variant="ai">
        <Info />
        <AlertDescription>
          A confirmed mapping is what lets the next file from that supplier import without review.
          Columns are mapped to what they <span className="font-medium">mean</span> — unit price,
          quantity, HSN — so the mapping still works when the supplier renames or reorders them.
        </AlertDescription>
      </Alert>

      <SectionCard title="Mappings" description="One per supplier and document format">
        <AsyncBoundary
          state={state}
          isEmpty={(data) => data.items.length === 0}
          empty={{
            icon: FileSpreadsheet,
            title: "No mappings yet",
            description:
              "A mapping is proposed the first time a supplier sends a spreadsheet, and becomes reusable once you confirm it.",
          }}
        >
          {(data) => (
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="pl-4">Mapping</TableHead>
                  <TableHead>Supplier</TableHead>
                  <TableHead>Document</TableHead>
                  <TableHead>Format</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Used</TableHead>
                  <TableHead className="text-right">Success</TableHead>
                  <TableHead className="pr-4 text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((mapping) => (
                  <TableRow key={mapping.id}>
                    <TableCell className="pl-4">
                      <span className="block font-medium text-foreground">{mapping.mappingName}</span>
                      <span className="block max-w-[280px] truncate font-mono text-caption text-muted-foreground">
                        {mapping.columnSignature}
                      </span>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {mapping.supplierName ?? "Any supplier"}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {mapping.documentType.replace(/_/g, " ")}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {FORMAT_LABELS[mapping.fileFormat] ?? mapping.fileFormat}
                    </TableCell>
                    <TableCell>
                      <StatusBadge
                        status={mapping.status === "proposed" ? "under_review" : mapping.status === "confirmed" ? "approved" : "inactive"}
                        label={
                          mapping.status === "proposed"
                            ? "Needs confirming"
                            : mapping.status === "confirmed"
                              ? "Confirmed"
                              : "Deprecated"
                        }
                      />
                    </TableCell>
                    <TableCell className="text-right text-muted-foreground tabular">
                      {mapping.usageCount}
                      {mapping.lastUsedAt && (
                        <span className="block text-caption">{formatDate(mapping.lastUsedAt)}</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right text-muted-foreground tabular">
                      {mapping.usageCount > 0 ? `${mapping.successRate}%` : "—"}
                    </TableCell>
                    <TableCell className="pr-4 text-right">
                      <Button variant="outline" size="sm" asChild>
                        <Link href={`/schema-mappings/${mapping.id}`}>
                          {mapping.status === "proposed" ? "Review" : "Open"}
                          <ArrowRight />
                        </Link>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </AsyncBoundary>
      </SectionCard>
    </div>
  );
}

export function SchemaMappingDetailScreen({ mappingId }: { mappingId: string }) {
  const state = useSchemaMapping(mappingId);
  // Re-read after every edit: the server decides what is still unmapped and
  // whether the layout can be confirmed, and the banner reads those.
  const updateField = useUpdateMappingField(mappingId, () => state.refresh());
  const confirmMapping = useConfirmSchemaMapping(() => state.refresh());

  return (
    <AsyncBoundary state={state}>
      {(detail) => {
        const locked = detail.mapping.status === "deprecated";

        return (
          <div className="space-y-4">
            <FormError message={confirmMapping.error ?? updateField.error} />

            <SectionCard
              title={detail.mapping.mappingName}
              description={`${detail.mapping.supplierName ?? "Any supplier"} · ${
                FORMAT_LABELS[detail.mapping.fileFormat] ?? detail.mapping.fileFormat
              } · header row ${detail.mapping.headerRowIndex}, data from row ${detail.mapping.dataStartRow}`}
              action={
                <div className="flex items-center gap-2">
                  <StatusBadge
                    status={
                      detail.mapping.status === "proposed"
                        ? "under_review"
                        : detail.mapping.status === "confirmed"
                          ? "approved"
                          : "inactive"
                    }
                    label={
                      detail.mapping.status === "proposed"
                        ? "Needs confirming"
                        : detail.mapping.status === "confirmed"
                          ? "Confirmed"
                          : "Deprecated"
                    }
                  />
                  <PermissionButton
                    permission="ai.manage_mappings"
                    size="sm"
                    disabled={locked || confirmMapping.isPending}
                    onClick={() => confirmMapping.run(mappingId)}
                  >
                    {detail.mapping.status === "confirmed" ? "Re-confirm" : "Confirm mapping"}
                  </PermissionButton>
                </div>
              }
            >
              {detail.unmappedRequired.length > 0 && (
                <div className="border-b border-border bg-warning-subtle/50 px-4 py-2.5">
                  <p className="text-body text-warning-subtle-foreground">
                    Still to map: {detail.unmappedRequired.join(", ")}. The importer needs{" "}
                    {detail.unmappedRequired.length > 1 ? "these fields" : "this field"} before the
                    mapping can be confirmed.
                  </p>
                </div>
              )}

              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="pl-4">Their column</TableHead>
                    <TableHead>Sample values</TableHead>
                    <TableHead className="w-[240px]">Means (business field)</TableHead>
                    <TableHead className="w-[190px]">Transform</TableHead>
                    <TableHead className="pr-4 text-right">Confidence</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {detail.fields.map((field) => (
                    <TableRow key={field.id}>
                      <TableCell className="pl-4">
                        <span className="block font-medium text-foreground">
                          {field.sourceColumn}
                        </span>
                        <span className="block text-caption text-muted-foreground">
                          column {field.sourceColumnIndex + 1}
                        </span>
                      </TableCell>

                      <TableCell className="text-muted-foreground">
                        <span className="flex flex-wrap gap-1">
                          {(field.sampleValues ?? []).map((sample, i) => (
                            <Badge key={i} variant="outline" className="font-mono">
                              {sample}
                            </Badge>
                          ))}
                        </span>
                      </TableCell>

                      <TableCell>
                        <Select
                          value={field.canonicalFieldCode || "__none"}
                          disabled={locked}
                          onValueChange={(value) =>
                            updateField.run({
                              fieldId: field.id,
                              patch: { canonicalFieldCode: value === "__none" ? "" : value },
                            })
                          }
                        >
                          <SelectTrigger size="sm">
                            <SelectValue placeholder="Not mapped" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="__none">Ignore this column</SelectItem>
                            {detail.canonicalFields.map((canonical) => (
                              <SelectItem key={canonical.code} value={canonical.code}>
                                {canonical.label}
                                {canonical.isRequired ? " *" : ""}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </TableCell>

                      <TableCell>
                        <Select
                          value={field.transform}
                          disabled={locked || !field.canonicalFieldCode}
                          onValueChange={(value) =>
                            updateField.run({
                              fieldId: field.id,
                              patch: { transform: value as MappingTransform },
                            })
                          }
                        >
                          <SelectTrigger size="sm">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {TRANSFORMS.map((transform) => (
                              <SelectItem key={transform.value} value={transform.value}>
                                {transform.label}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </TableCell>

                      <TableCell className="pr-4 text-right text-muted-foreground tabular">
                        {field.confirmedAt ? "Confirmed" : `${Math.round(field.confidence)}%`}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              <div className="border-t border-border px-4 py-3">
                <p className="text-caption text-muted-foreground">
                  Fields marked * are required for this document type. Confirming records who
                  agreed the mapping, and subsequent files from{" "}
                  {detail.mapping.supplierName ?? "this supplier"} reuse it automatically.
                </p>
              </div>
            </SectionCard>

            {detail.sampleDocument && (
              <SectionCard title="Sample document" description="What this mapping was learned from">
                <div className="flex items-center gap-3 p-4">
                  <FileSpreadsheet className="size-4 text-muted-foreground" />
                  <span className="text-body text-foreground">
                    {detail.sampleDocument.originalFilename}
                  </span>
                  <Button variant="outline" size="sm" asChild className="ml-auto">
                    <Link href={`/ai-documents/review/${detail.sampleDocument.id}`}>
                      Open extraction
                    </Link>
                  </Button>
                </div>
              </SectionCard>
            )}
          </div>
        );
      }}
    </AsyncBoundary>
  );
}
