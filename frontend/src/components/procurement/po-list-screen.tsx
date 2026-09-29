"use client";

import Link from "next/link";
import { FileText, Plus } from "lucide-react";

import { AsyncBoundary } from "@/components/common/async-state";
import { PageHeader } from "@/components/common/page-header";
import { DataToolbar, TablePagination } from "@/components/common/data-toolbar";
import { FilterSelect } from "@/components/common/filter-select";
import { StatusBadge } from "@/components/common/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useListControls } from "@/hooks/use-api";
import { usePurchaseOrders } from "@/hooks/use-procurement";
import { useSuppliers } from "@/hooks/use-suppliers";
import { statusLabel } from "@/lib/domain/state-machines";
import { formatCurrency, formatDate } from "@/lib/format";
import type { PurchaseOrderStatus } from "@/types";

const PO_STATUSES: PurchaseOrderStatus[] = [
  "draft",
  "pending_approval",
  "approved",
  "sent",
  "acknowledged",
  "partially_received",
  "received",
  "closed",
  "cancelled",
];

export function PoListScreen() {
  const controls = useListControls({ sort: "-poDate" });
  const poState = usePurchaseOrders(controls.params);
  const suppliersState = useSuppliers({});

  const suppliers = suppliersState.data?.items ?? [];
  const statusOptions = PO_STATUSES.map((s) => ({ value: s, label: statusLabel(s) }));

  const pendingValue = (poState.data?.items ?? [])
    .filter((po) => po.status !== "closed" && po.status !== "cancelled")
    .reduce((sum, po) => sum + po.totalAmount, 0);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Purchase Orders"
        description={
          poState.data
            ? `${poState.data.total} order${poState.data.total === 1 ? "" : "s"} · ${formatCurrency(pendingValue)} in the pipeline`
            : undefined
        }
        actions={
          <Button asChild>
            <Link href="/procurement/purchase-orders/new">
              <Plus />
              Create Purchase Order
            </Link>
          </Button>
        }
      />

      <Card className="overflow-hidden">
        <DataToolbar
          searchPlaceholder="Search PO number or supplier..."
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
          state={poState}
          isEmpty={(d) => d.items.length === 0}
          empty={{ icon: FileText, title: "No purchase orders match your search." }}
        >
          {(data) => (
            <>
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="pl-4">PO Number</TableHead>
                    <TableHead>Supplier</TableHead>
                    <TableHead>PO Date</TableHead>
                    <TableHead>Expected Delivery</TableHead>
                    <TableHead className="text-right">Items</TableHead>
                    <TableHead className="text-right">Value</TableHead>
                    <TableHead className="w-[140px]">Received</TableHead>
                    <TableHead className="pr-4">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((po) => (
                    <TableRow key={po.id}>
                      <TableCell className="pl-4">
                        <Link
                          href={`/procurement/purchase-orders/${po.id}`}
                          className="font-mono text-[12.5px] font-medium text-foreground hover:text-primary"
                        >
                          {po.poNumber}
                        </Link>
                      </TableCell>
                      <TableCell className="max-w-[190px] truncate text-foreground">
                        {po.supplierName}
                      </TableCell>
                      <TableCell className="text-muted-foreground">{formatDate(po.poDate)}</TableCell>
                      <TableCell className="text-muted-foreground">
                        <span className="flex items-center gap-1.5">
                          {po.expectedDeliveryDate ? formatDate(po.expectedDeliveryDate) : "—"}
                          {po.isOverdue && <Badge variant="destructive">Overdue</Badge>}
                        </span>
                      </TableCell>
                      <TableCell className="text-right text-muted-foreground tabular">
                        {po.itemCount}
                      </TableCell>
                      <TableCell className="text-right font-medium text-foreground tabular">
                        {formatCurrency(po.totalAmount)}
                      </TableCell>
                      <TableCell>
                        <Progress
                          value={po.receivedPct}
                          indicatorClassName={po.receivedPct >= 100 ? "bg-success" : "bg-primary"}
                        />
                        <span className="mt-1 block text-caption text-muted-foreground tabular">
                          {po.receivedPct}%
                        </span>
                      </TableCell>
                      <TableCell className="pr-4">
                        <StatusBadge status={po.status} />
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
