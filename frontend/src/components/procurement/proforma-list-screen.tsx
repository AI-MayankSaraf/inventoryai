"use client";

import Link from "next/link";
import { FileUp, ReceiptText } from "lucide-react";

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
import { useListControls } from "@/hooks/use-api";
import { useProformas } from "@/hooks/use-procurement";
import { useSuppliers } from "@/hooks/use-suppliers";
import { statusLabel } from "@/lib/domain/state-machines";
import { formatCurrency, formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ProformaStatus } from "@/types";

const PROFORMA_STATUSES: ProformaStatus[] = [
  "pending",
  "under_review",
  "approved",
  "rejected",
  "paid",
  "completed",
  "cancelled",
];

export function ProformaListScreen() {
  const controls = useListControls({ sort: "-proformaDate" });
  const proformaState = useProformas(controls.params);
  const suppliersState = useSuppliers({});

  const suppliers = suppliersState.data?.items ?? [];
  const statusOptions = PROFORMA_STATUSES.map((s) => ({ value: s, label: statusLabel(s) }));

  return (
    <div className="space-y-5">
      <PageHeader
        title="Proforma Invoices"
        description="Supplier advance bills, checked against the purchase order before you pay"
        actions={
          <Button variant="outline" asChild>
            <Link href="/ai-documents">
              <FileUp />
              Upload Proforma
            </Link>
          </Button>
        }
      />

      <Card className="overflow-hidden">
        <DataToolbar
          searchPlaceholder="Search proforma number or supplier..."
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
          state={proformaState}
          isEmpty={(d) => d.items.length === 0}
          empty={{
            icon: ReceiptText,
            title: "No proforma invoices yet",
            description:
              "Upload a supplier's proforma to check it against the purchase order before you pay an advance.",
            action: (
              <Button asChild>
                <Link href="/ai-documents">Upload Proforma</Link>
              </Button>
            ),
          }}
        >
          {(data) => (
            <>
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="pl-4">Proforma Number</TableHead>
                    <TableHead>Supplier</TableHead>
                    <TableHead>Date</TableHead>
                    <TableHead>PO Reference</TableHead>
                    <TableHead className="text-right">Total</TableHead>
                    <TableHead className="text-right">Variance</TableHead>
                    <TableHead className="pr-4">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((p) => {
                    const exceedsPo = p.varianceAmount > 0.5;
                    return (
                      <TableRow key={p.id} className={cn(exceedsPo && "bg-warning-subtle/30")}>
                        <TableCell className="pl-4">
                          <Link
                            href={`/procurement/proforma/${p.id}`}
                            className="font-mono text-[12.5px] font-medium text-foreground hover:text-primary"
                          >
                            {p.proformaNumber}
                          </Link>
                        </TableCell>
                        <TableCell className="max-w-[190px] truncate text-foreground">
                          {p.supplierName}
                        </TableCell>
                        <TableCell className="text-muted-foreground">{formatDate(p.proformaDate)}</TableCell>
                        <TableCell className="font-mono text-[12.5px] text-muted-foreground">
                          {p.poNumber ?? "—"}
                        </TableCell>
                        <TableCell className="text-right font-medium text-foreground tabular">
                          {formatCurrency(p.totalAmount)}
                        </TableCell>
                        <TableCell className="text-right tabular">
                          {p.hasVariance ? (
                            <Badge variant={exceedsPo ? "warning" : "neutral"}>
                              {p.varianceAmount > 0 ? "+" : ""}
                              {formatCurrency(p.varianceAmount, true)}
                            </Badge>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </TableCell>
                        <TableCell className="pr-4">
                          <StatusBadge status={p.status} />
                        </TableCell>
                      </TableRow>
                    );
                  })}
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
