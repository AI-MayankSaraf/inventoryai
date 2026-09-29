"use client";

import * as React from "react";
import Link from "next/link";
import { Plus, Send } from "lucide-react";

import { AsyncBoundary } from "@/components/common/async-state";
import { DataToolbar, TablePagination } from "@/components/common/data-toolbar";
import { FilterSelect } from "@/components/common/filter-select";
import { PageHeader } from "@/components/common/page-header";
import { PermissionGate } from "@/components/common/permission-gate";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useListControls } from "@/hooks/use-api";
import { useRfqs } from "@/hooks/use-procurement";
import { ImportRfqButton } from "@/components/procurement/rfq-import-dialog";
import { formatCurrency, formatDate } from "@/lib/format";
import type { RfqStatus } from "@/types";

const STATUS_OPTIONS: { value: RfqStatus; label: string }[] = [
  { value: "draft", label: "Draft" },
  { value: "sent", label: "Sent" },
  { value: "partially_quoted", label: "Partially Quoted" },
  { value: "quoted", label: "Quoted" },
  { value: "closed", label: "Closed" },
  { value: "cancelled", label: "Cancelled" },
];

export function RfqListScreen() {
  const controls = useListControls({ sort: "-rfqDate" });
  const state = useRfqs(controls.params);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Request for Quotation"
        description="Ask suppliers to quote before you commit to a purchase order"
        actions={
          <div className="flex gap-2">
            <PermissionGate permission="rfq.import">
              <ImportRfqButton />
            </PermissionGate>
            <PermissionGate permission="rfq.create">
              <Button asChild>
                <Link href="/procurement/rfq/new">
                  <Plus />
                  Create RFQ
                </Link>
              </Button>
            </PermissionGate>
          </div>
        }
      />

      <Card className="overflow-hidden">
        <DataToolbar
          searchPlaceholder="Search RFQ number or subject..."
          searchValue={controls.q}
          onSearchChange={controls.setQ}
          filters={
            <FilterSelect
              placeholder="All Status"
              options={STATUS_OPTIONS.map((o) => o.label)}
              value={STATUS_OPTIONS.find((o) => o.value === controls.filters.status)?.label}
              onValueChange={(label) =>
                controls.setFilter("status", STATUS_OPTIONS.find((o) => o.label === label)?.value)
              }
            />
          }
        />

        <AsyncBoundary
          state={state}
          empty={{
            icon: Send,
            title: "No RFQs yet",
            description: "Send your first request for quotation and compare supplier prices side by side.",
            action: (
              <PermissionGate permission="rfq.create">
                <Button asChild>
                  <Link href="/procurement/rfq/new">Create Your First RFQ</Link>
                </Button>
              </PermissionGate>
            ),
          }}
          isEmpty={(data) => data.items.length === 0}
        >
          {(data) => (
            <>
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="pl-4">RFQ Number</TableHead>
                    <TableHead>Subject</TableHead>
                    <TableHead>Date</TableHead>
                    <TableHead>Expected Delivery</TableHead>
                    <TableHead>Deliver To</TableHead>
                    <TableHead className="text-right">Items</TableHead>
                    <TableHead className="text-right">Suppliers</TableHead>
                    <TableHead className="text-right">Quotes</TableHead>
                    <TableHead className="text-right">Est. Value</TableHead>
                    <TableHead className="pr-4">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((rfq) => (
                    <TableRow key={rfq.id}>
                      <TableCell className="pl-4">
                        <Link
                          href={`/procurement/rfq/${rfq.id}`}
                          className="font-mono text-[12.5px] font-medium text-foreground hover:text-primary"
                        >
                          {rfq.rfqNumber}
                        </Link>
                      </TableCell>
                      <TableCell className="max-w-[260px] truncate font-medium text-foreground">
                        {rfq.subject}
                      </TableCell>
                      <TableCell className="text-muted-foreground">{formatDate(rfq.rfqDate)}</TableCell>
                      <TableCell className="text-muted-foreground">
                        {rfq.expectedDeliveryDate ? formatDate(rfq.expectedDeliveryDate) : "—"}
                      </TableCell>
                      <TableCell className="text-muted-foreground">{rfq.godownName || "—"}</TableCell>
                      <TableCell className="text-right text-muted-foreground tabular">
                        {rfq.itemCount}
                      </TableCell>
                      <TableCell className="text-right text-muted-foreground tabular">
                        {rfq.supplierCount}
                      </TableCell>
                      <TableCell className="text-right tabular">
                        {rfq.quotesReceived}/{rfq.supplierCount}
                      </TableCell>
                      <TableCell className="text-right text-foreground tabular">
                        {rfq.estimatedValue > 0 ? formatCurrency(rfq.estimatedValue) : "—"}
                      </TableCell>
                      <TableCell className="pr-4">
                        <StatusBadge status={rfq.status} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              <TablePagination page={1} pageSize={Math.max(data.items.length, 1)} total={data.total} />
            </>
          )}
        </AsyncBoundary>
      </Card>
    </div>
  );
}
