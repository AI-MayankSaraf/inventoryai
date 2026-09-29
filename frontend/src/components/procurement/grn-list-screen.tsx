"use client";

import Link from "next/link";
import { PackageCheck, Plus, TriangleAlert } from "lucide-react";

import { AsyncBoundary } from "@/components/common/async-state";
import { PageHeader } from "@/components/common/page-header";
import { DataToolbar, TablePagination } from "@/components/common/data-toolbar";
import { FilterSelect } from "@/components/common/filter-select";
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
import { useGodowns } from "@/hooks/use-catalog";
import { useListControls } from "@/hooks/use-api";
import { useGoodsReceipts } from "@/hooks/use-receiving";
import { useSuppliers } from "@/hooks/use-suppliers";
import { statusLabel } from "@/lib/domain/state-machines";
import { formatDate, formatQuantity } from "@/lib/format";
import type { GoodsReceiptStatus } from "@/types";

const GRN_STATUSES: GoodsReceiptStatus[] = [
  "draft",
  "partially_received",
  "received",
  "cancelled",
  "reversed",
];

export function GrnListScreen() {
  const controls = useListControls({ sort: "-grnDate" });
  const grnState = useGoodsReceipts(controls.params);
  const suppliersState = useSuppliers({});
  const godownsState = useGodowns();

  const suppliers = suppliersState.data?.items ?? [];
  const godowns = godownsState.data ?? [];
  const statusOptions = GRN_STATUSES.map((s) => ({ value: s, label: statusLabel(s) }));

  const discrepancyCount = (grnState.data?.items ?? []).filter((g) => g.hasDiscrepancy).length;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Goods Receipt"
        description={
          grnState.data
            ? `${grnState.data.total} receipt${grnState.data.total === 1 ? "" : "s"}${
                discrepancyCount ? ` · ${discrepancyCount} with discrepancies` : ""
              }`
            : "Every delivery checked in against its purchase order"
        }
        actions={
          <Button asChild>
            <Link href="/goods-receipt/new">
              <Plus />
              Create Goods Receipt
            </Link>
          </Button>
        }
      />

      <Card className="overflow-hidden">
        <DataToolbar
          searchPlaceholder="Search GRN number, PO or supplier..."
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
                placeholder="All Godowns"
                options={godowns.map((g) => g.name)}
                value={godowns.find((g) => g.id === controls.filters.godownId)?.name}
                onValueChange={(name) =>
                  controls.setFilter("godownId", godowns.find((g) => g.name === name)?.id)
                }
              />
              <FilterSelect
                placeholder="All Suppliers"
                options={suppliers.map((s) => s.name)}
                className="w-[190px]"
                value={suppliers.find((s) => s.id === controls.filters.supplierId)?.name}
                onValueChange={(name) =>
                  controls.setFilter("supplierId", suppliers.find((s) => s.name === name)?.id)
                }
              />
            </>
          }
        />

        <AsyncBoundary
          state={grnState}
          isEmpty={(d) => d.items.length === 0}
          empty={{ icon: PackageCheck, title: "No goods receipts match your search." }}
        >
          {(data) => (
            <>
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="pl-4">GRN Number</TableHead>
                    <TableHead>Date</TableHead>
                    <TableHead>Supplier</TableHead>
                    <TableHead>Related PO</TableHead>
                    <TableHead>Godown</TableHead>
                    <TableHead className="text-right">Items</TableHead>
                    <TableHead className="text-right">Accepted</TableHead>
                    <TableHead>Discrepancy</TableHead>
                    <TableHead className="pr-4">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((grn) => (
                    <TableRow key={grn.id}>
                      <TableCell className="pl-4">
                        <Link
                          href={`/goods-receipt/${grn.id}`}
                          className="font-mono text-[12.5px] font-medium text-foreground hover:text-primary"
                        >
                          {grn.grnNumber}
                        </Link>
                      </TableCell>
                      <TableCell className="text-muted-foreground">{formatDate(grn.grnDate)}</TableCell>
                      <TableCell className="max-w-[190px] truncate text-foreground">
                        {grn.supplierName}
                      </TableCell>
                      <TableCell className="font-mono text-[12.5px] text-muted-foreground">
                        {grn.poNumber ?? "—"}
                      </TableCell>
                      <TableCell className="text-muted-foreground">{grn.godownName}</TableCell>
                      <TableCell className="text-right text-muted-foreground tabular">
                        {grn.itemCount}
                      </TableCell>
                      <TableCell className="text-right font-medium text-foreground tabular">
                        {formatQuantity(grn.acceptedTotal, 2)}
                      </TableCell>
                      <TableCell>
                        {grn.hasDiscrepancy ? (
                          <Badge variant="warning">
                            <TriangleAlert />
                            Discrepancy
                          </Badge>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell className="pr-4">
                        <StatusBadge status={grn.status} />
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
