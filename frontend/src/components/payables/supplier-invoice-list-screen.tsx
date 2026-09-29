"use client";

import Link from "next/link";
import { Plus, ReceiptText } from "lucide-react";

import { AsyncBoundary } from "@/components/common/async-state";
import { PageHeader } from "@/components/common/page-header";
import { DataToolbar, TablePagination } from "@/components/common/data-toolbar";
import { FilterSelect } from "@/components/common/filter-select";
import { PermissionGate } from "@/components/common/permission-gate";
import { StatusBadge } from "@/components/common/status-badge";
import { Badge } from "@/components/ui/badge";
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
import { useSupplierInvoices } from "@/hooks/use-invoices";
import { statusLabel } from "@/lib/domain/state-machines";
import { formatCurrency, formatDate } from "@/lib/format";
import type { InvoiceMatchStatus, InvoicePaymentStatus, SupplierInvoiceStatus } from "@/types";

const INVOICE_STATUSES: SupplierInvoiceStatus[] = [
  "draft",
  "under_review",
  "approved",
  "disputed",
  "cancelled",
];
const MATCH_STATUSES: InvoiceMatchStatus[] = ["unmatched", "matched", "variance"];
const PAYMENT_STATUSES: InvoicePaymentStatus[] = ["unpaid", "partially_paid", "paid"];

/**
 * Supplier invoices — the record of what a supplier actually billed, checked
 * against what was ordered and what was received (I1). Every row that fails
 * the three-way match or has slipped past its due date is flagged right here,
 * before anyone opens the document.
 */
export function SupplierInvoiceListScreen() {
  const controls = useListControls({ sort: "-invoiceDate" });
  const invoiceState = useSupplierInvoices(controls.params);

  const statusOptions = INVOICE_STATUSES.map((s) => ({ value: s, label: statusLabel(s) }));
  const matchOptions = MATCH_STATUSES.map((s) => ({ value: s, label: statusLabel(s) }));
  const paymentOptions = PAYMENT_STATUSES.map((s) => ({ value: s, label: statusLabel(s) }));

  const overdueCount = (invoiceState.data?.items ?? []).filter((inv) => inv.isOverdue).length;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Supplier Invoices"
        description={
          invoiceState.data
            ? `${invoiceState.data.total} invoice${invoiceState.data.total === 1 ? "" : "s"}${
                overdueCount ? ` · ${overdueCount} overdue` : ""
              }`
            : "What the supplier billed, checked against the order and the receipt"
        }
        actions={
          <PermissionGate permission="invoice.create">
            <Button asChild>
              <Link href="/supplier-invoices/new">
                <Plus />
                Enter Invoice
              </Link>
            </Button>
          </PermissionGate>
        }
      />

      <Card className="overflow-hidden">
        <DataToolbar
          searchPlaceholder="Search invoice number, supplier, PO or GRN..."
          searchValue={controls.q}
          onSearchChange={controls.setQ}
          filters={
            <>
              <FilterSelect
                placeholder="All Status"
                options={statusOptions.map((o) => o.label)}
                value={statusOptions.find((o) => o.value === controls.filters.status)?.label}
                onValueChange={(label) =>
                  controls.setFilter("status", statusOptions.find((o) => o.label === label)?.value)
                }
              />
              <FilterSelect
                placeholder="All Match Status"
                options={matchOptions.map((o) => o.label)}
                className="w-[168px]"
                value={matchOptions.find((o) => o.value === controls.filters.matchStatus)?.label}
                onValueChange={(label) =>
                  controls.setFilter("matchStatus", matchOptions.find((o) => o.label === label)?.value)
                }
              />
              <FilterSelect
                placeholder="All Payment Status"
                options={paymentOptions.map((o) => o.label)}
                className="w-[172px]"
                value={paymentOptions.find((o) => o.value === controls.filters.paymentStatus)?.label}
                onValueChange={(label) =>
                  controls.setFilter("paymentStatus", paymentOptions.find((o) => o.label === label)?.value)
                }
              />
            </>
          }
        />

        <AsyncBoundary
          state={invoiceState}
          isEmpty={(d) => d.items.length === 0}
          empty={{ icon: ReceiptText, title: "No supplier invoices match your search." }}
        >
          {(data) => (
            <>
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="pl-4">Invoice Number</TableHead>
                    <TableHead>Supplier</TableHead>
                    <TableHead>Invoice Date</TableHead>
                    <TableHead>Due Date</TableHead>
                    <TableHead>PO</TableHead>
                    <TableHead>GRN</TableHead>
                    <TableHead className="text-right">Total</TableHead>
                    <TableHead>Match</TableHead>
                    <TableHead>Payment</TableHead>
                    <TableHead className="pr-4">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((inv) => (
                    <TableRow key={inv.id}>
                      <TableCell className="pl-4">
                        <Link
                          href={`/supplier-invoices/${inv.id}`}
                          className="font-mono text-[12.5px] font-medium text-foreground hover:text-primary"
                        >
                          {inv.invoiceNumber}
                        </Link>
                      </TableCell>
                      <TableCell className="max-w-[190px] truncate text-foreground">
                        {inv.supplierName}
                      </TableCell>
                      <TableCell className="text-muted-foreground">{formatDate(inv.invoiceDate)}</TableCell>
                      <TableCell className="text-muted-foreground">
                        <span className="flex items-center gap-1.5">
                          {inv.dueDate ? formatDate(inv.dueDate) : "—"}
                          {inv.isOverdue && <Badge variant="destructive">Overdue</Badge>}
                        </span>
                      </TableCell>
                      <TableCell className="font-mono text-[12.5px] text-muted-foreground">
                        {inv.poNumber ?? "—"}
                      </TableCell>
                      <TableCell className="font-mono text-[12.5px] text-muted-foreground">
                        {inv.grnNumber ?? "—"}
                      </TableCell>
                      <TableCell className="text-right font-medium text-foreground tabular">
                        {formatCurrency(inv.totalAmount)}
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={inv.matchStatus} />
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={inv.paymentStatus} />
                      </TableCell>
                      <TableCell className="pr-4">
                        <StatusBadge status={inv.status} />
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
