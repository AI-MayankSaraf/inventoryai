"use client";

import Link from "next/link";
import { CornerUpLeft } from "lucide-react";

import { AsyncBoundary } from "@/components/common/async-state";
import { PageHeader } from "@/components/common/page-header";
import { DataToolbar, TablePagination } from "@/components/common/data-toolbar";
import { FilterSelect } from "@/components/common/filter-select";
import { StatusBadge } from "@/components/common/status-badge";
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
import { usePurchaseReturns } from "@/hooks/use-invoices";
import { statusLabel } from "@/lib/domain/state-machines";
import { formatCurrency, formatDate } from "@/lib/format";
import type { PurchaseReturnStatus, ReturnReason } from "@/types";

const RETURN_STATUSES: PurchaseReturnStatus[] = ["draft", "sent", "accepted", "credited", "cancelled"];

/** Not exported by the API layer — kept local to the return screens that display it. */
export const RETURN_REASON_LABELS: Record<ReturnReason, string> = {
  damaged: "Damaged",
  expired: "Expired",
  wrong_product: "Wrong product",
  wrong_variant: "Wrong variant",
  quality_rejected: "Quality rejected",
  excess_supply: "Excess supply",
  other: "Other",
};

const RETURN_REASONS = Object.keys(RETURN_REASON_LABELS) as ReturnReason[];

/**
 * Purchase returns — the record that stock actually left when goods were
 * rejected (I2). A confirmed return posts a negative inventory transaction,
 * so this list is also the audit trail for that stock movement.
 */
export function PurchaseReturnListScreen() {
  const controls = useListControls({ sort: "-returnDate" });
  const returnState = usePurchaseReturns(controls.params);

  const statusOptions = RETURN_STATUSES.map((s) => ({ value: s, label: statusLabel(s) }));
  const reasonOptions = RETURN_REASONS.map((r) => ({ value: r, label: RETURN_REASON_LABELS[r] }));

  return (
    <div className="space-y-5">
      <PageHeader
        title="Purchase Returns"
        description={
          returnState.data
            ? `${returnState.data.total} return${returnState.data.total === 1 ? "" : "s"}`
            : "Goods sent back to a supplier, and the stock movement that recorded it"
        }
      />

      <Card className="overflow-hidden">
        <DataToolbar
          searchPlaceholder="Search return number, supplier, GRN or debit note..."
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
                placeholder="All Reasons"
                options={reasonOptions.map((o) => o.label)}
                className="w-[172px]"
                value={reasonOptions.find((o) => o.value === controls.filters.reason)?.label}
                onValueChange={(label) =>
                  controls.setFilter("reason", reasonOptions.find((o) => o.label === label)?.value)
                }
              />
            </>
          }
        />

        <AsyncBoundary
          state={returnState}
          isEmpty={(d) => d.items.length === 0}
          empty={{ icon: CornerUpLeft, title: "No purchase returns match your search." }}
        >
          {(data) => (
            <>
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="pl-4">Return Number</TableHead>
                    <TableHead>Date</TableHead>
                    <TableHead>Supplier</TableHead>
                    <TableHead>GRN</TableHead>
                    <TableHead>PO</TableHead>
                    <TableHead>Reason</TableHead>
                    <TableHead className="text-right">Items</TableHead>
                    <TableHead className="text-right">Total</TableHead>
                    <TableHead className="pr-4">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((ret) => (
                    <TableRow key={ret.id}>
                      <TableCell className="pl-4">
                        <Link
                          href={`/purchase-returns/${ret.id}`}
                          className="font-mono text-[12.5px] font-medium text-foreground hover:text-primary"
                        >
                          {ret.returnNumber}
                        </Link>
                      </TableCell>
                      <TableCell className="text-muted-foreground">{formatDate(ret.returnDate)}</TableCell>
                      <TableCell className="max-w-[190px] truncate text-foreground">
                        {ret.supplierName}
                      </TableCell>
                      <TableCell className="font-mono text-[12.5px] text-muted-foreground">
                        {ret.grnNumber ?? "—"}
                      </TableCell>
                      <TableCell className="font-mono text-[12.5px] text-muted-foreground">
                        {ret.poNumber ?? "—"}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {RETURN_REASON_LABELS[ret.reason]}
                      </TableCell>
                      <TableCell className="text-right text-muted-foreground tabular">
                        {ret.itemCount}
                      </TableCell>
                      <TableCell className="text-right font-medium text-foreground tabular">
                        {formatCurrency(ret.totalAmount)}
                      </TableCell>
                      <TableCell className="pr-4">
                        <StatusBadge status={ret.status} />
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
