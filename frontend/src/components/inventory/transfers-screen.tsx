"use client";

import * as React from "react";
import { ArrowLeftRight, ArrowRight } from "lucide-react";

import { AsyncBoundary } from "@/components/common/async-state";
import { DataToolbar, TablePagination } from "@/components/common/data-toolbar";
import { FilterSelect } from "@/components/common/filter-select";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { StockTransferDialog } from "@/components/inventory/stock-transfer-dialog";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useGodowns } from "@/hooks/use-catalog";
import { useListControls } from "@/hooks/use-api";
import { useTransactions, useTransfers } from "@/hooks/use-inventory";
import { formatDate } from "@/lib/format";
import type { Godown, StockTransfer, StockTransferStatus } from "@/types";

const STATUS_OPTIONS: { value: StockTransferStatus; label: string }[] = [
  { value: "draft", label: "Draft" },
  { value: "in_transit", label: "In Transit" },
  { value: "received", label: "Received" },
  { value: "cancelled", label: "Cancelled" },
];

export function TransfersScreen() {
  const controls = useListControls({ sort: "-transferDate" });
  const godownsState = useGodowns();
  const godowns = godownsState.data ?? [];
  const state = useTransfers(controls.params);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Stock Transfers"
        description="Move stock between godowns — every transfer posts a linked pair of ledger entries"
        actions={<StockTransferDialog />}
      />

      <Card className="overflow-hidden">
        <DataToolbar
          searchPlaceholder="Search transfer number, vehicle or LR..."
          searchValue={controls.q}
          onSearchChange={controls.setQ}
          filters={
            <>
              <FilterSelect
                placeholder="All From Godowns"
                options={godowns.map((g) => g.name)}
                value={godowns.find((g) => g.id === controls.filters.fromGodownId)?.name}
                onValueChange={(name) =>
                  controls.setFilter("fromGodownId", godowns.find((g) => g.name === name)?.id)
                }
              />
              <FilterSelect
                placeholder="All To Godowns"
                options={godowns.map((g) => g.name)}
                value={godowns.find((g) => g.id === controls.filters.toGodownId)?.name}
                onValueChange={(name) =>
                  controls.setFilter("toGodownId", godowns.find((g) => g.name === name)?.id)
                }
              />
              <FilterSelect
                placeholder="All Status"
                options={STATUS_OPTIONS.map((o) => o.label)}
                value={STATUS_OPTIONS.find((o) => o.value === controls.filters.status)?.label}
                onValueChange={(label) =>
                  controls.setFilter("status", STATUS_OPTIONS.find((o) => o.label === label)?.value)
                }
              />
            </>
          }
        />

        <AsyncBoundary
          state={state}
          isEmpty={(d) => d.items.length === 0}
          empty={{
            icon: ArrowLeftRight,
            title: "No stock transfers yet",
            description: "Move stock between godowns and it will show up here, with a linked ledger entry at each end.",
          }}
        >
          {(data) => (
            <>
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="pl-4">Transfer #</TableHead>
                    <TableHead>Date</TableHead>
                    <TableHead>From → To</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="pr-4 text-right">Items</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((transfer) => (
                    <TransferRow key={transfer.id} transfer={transfer} godowns={godowns} />
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

function TransferRow({ transfer, godowns }: { transfer: StockTransfer; godowns: Godown[] }) {
  // Every transfer posts a linked TRANSFER_OUT/TRANSFER_IN pair per item — the
  // item count is the number of distinct ledger lines it produced.
  const linesState = useTransactions({ filters: { sourceId: transfer.id }, limit: 500 });
  const itemCount = linesState.data
    ? new Set(linesState.data.items.map((r) => r.sourceLineId).filter(Boolean)).size
    : undefined;

  const fromName = godowns.find((g) => g.id === transfer.fromGodownId)?.name ?? "—";
  const toName = godowns.find((g) => g.id === transfer.toGodownId)?.name ?? "—";

  return (
    <TableRow>
      <TableCell className="pl-4 font-mono text-[12.5px] font-medium text-foreground">
        {transfer.transferNumber}
      </TableCell>
      <TableCell className="text-muted-foreground">{formatDate(transfer.transferDate)}</TableCell>
      <TableCell className="text-foreground">
        <span className="inline-flex items-center gap-1.5">
          {fromName}
          <ArrowRight className="size-3.5 text-muted-foreground" />
          {toName}
        </span>
      </TableCell>
      <TableCell>
        <StatusBadge status={transfer.status} />
      </TableCell>
      <TableCell className="pr-4 text-right text-muted-foreground tabular">
        {itemCount ?? "—"}
      </TableCell>
    </TableRow>
  );
}
