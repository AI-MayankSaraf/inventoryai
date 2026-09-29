"use client";

import Link from "next/link";
import { FileText, Plus } from "lucide-react";

import { AsyncBoundary } from "@/components/common/async-state";
import { DataToolbar, TablePagination } from "@/components/common/data-toolbar";
import { FilterSelect } from "@/components/common/filter-select";
import { PageHeader } from "@/components/common/page-header";
import { PermissionGate } from "@/components/common/permission-gate";
import { QuotationsTable } from "@/components/procurement/quotations-table";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useListControls } from "@/hooks/use-api";
import { useQuotations } from "@/hooks/use-procurement";
import type { QuotationSource, QuotationStatus } from "@/types";

const STATUS_OPTIONS: { value: QuotationStatus; label: string }[] = [
  { value: "draft", label: "Draft" },
  { value: "under_review", label: "Under Review" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "expired", label: "Expired" },
  { value: "superseded", label: "Superseded" },
  { value: "converted", label: "Converted" },
];

const SOURCE_OPTIONS: { value: QuotationSource; label: string }[] = [
  { value: "ai_extracted", label: "AI Extracted" },
  { value: "manual", label: "Manual Entry" },
  { value: "email", label: "Email" },
  { value: "portal", label: "Portal" },
];

export function QuotationsListScreen() {
  const controls = useListControls({ sort: "-quotationDate" });
  const state = useQuotations(controls.params);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Supplier Quotations"
        description="Everything your suppliers have quoted, however they sent it"
        actions={
          <PermissionGate permission="quotation.create">
            <Button asChild>
              <Link href="/procurement/quotations/new">
                <Plus />
                Enter a Quotation
              </Link>
            </Button>
          </PermissionGate>
        }
      />

      <Card className="overflow-hidden">
        <DataToolbar
          searchPlaceholder="Search quotation number or supplier..."
          searchValue={controls.q}
          onSearchChange={controls.setQ}
          filters={
            <>
              <FilterSelect
                placeholder="All Status"
                options={STATUS_OPTIONS.map((o) => o.label)}
                value={STATUS_OPTIONS.find((o) => o.value === controls.filters.status)?.label}
                onValueChange={(label) =>
                  controls.setFilter("status", STATUS_OPTIONS.find((o) => o.label === label)?.value)
                }
              />
              <FilterSelect
                placeholder="All Sources"
                options={SOURCE_OPTIONS.map((o) => o.label)}
                value={SOURCE_OPTIONS.find((o) => o.value === controls.filters.source)?.label}
                onValueChange={(label) =>
                  controls.setFilter("source", SOURCE_OPTIONS.find((o) => o.label === label)?.value)
                }
              />
            </>
          }
        />

        <AsyncBoundary
          state={state}
          empty={{
            icon: FileText,
            title: "No quotations yet",
            description: "Quotations arrive from AI-extracted documents or you can enter one by hand.",
          }}
          isEmpty={(data) => data.items.length === 0}
        >
          {(data) => (
            <>
              <QuotationsTable quotations={data.items} />
              <TablePagination page={1} pageSize={Math.max(data.items.length, 1)} total={data.total} />
            </>
          )}
        </AsyncBoundary>
      </Card>
    </div>
  );
}
