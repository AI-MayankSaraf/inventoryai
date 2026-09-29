"use client";

import * as React from "react";
import Link from "next/link";
import { Truck } from "lucide-react";

import { AsyncBoundary } from "@/components/common/async-state";
import { DataToolbar, TablePagination } from "@/components/common/data-toolbar";
import { FilterSelect } from "@/components/common/filter-select";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { SupplierFormDialog } from "@/components/suppliers/supplier-form-dialog";
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
import { useSuppliers } from "@/hooks/use-suppliers";

export function SuppliersListScreen() {
  const controls = useListControls({ sort: "name" });
  const state = useSuppliers(controls.params);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Suppliers"
        description="Manage your supplier list"
        actions={<SupplierFormDialog onSaved={() => state.refresh()} />}
      />

      <Card className="overflow-hidden">
        <DataToolbar
          searchPlaceholder="Search by name, GST, city..."
          searchValue={controls.q}
          onSearchChange={controls.setQ}
          filters={
            <>
              <FilterSelect
                placeholder="All Types"
                options={(state.data?.facets?.supplierType ?? []).map((f) => f.value)}
                value={controls.filters.supplierType}
                onValueChange={(v) => controls.setFilter("supplierType", v)}
              />
              <FilterSelect
                placeholder="All States"
                options={(state.data?.facets?.stateName ?? []).map((f) => f.value)}
                value={controls.filters.stateName}
                onValueChange={(v) => controls.setFilter("stateName", v)}
              />
              <FilterSelect
                placeholder="All Status"
                options={["active", "inactive"]}
                value={controls.filters.status}
                onValueChange={(v) => controls.setFilter("status", v)}
              />
            </>
          }
        />

        <AsyncBoundary
          state={state}
          empty={{
            icon: Truck,
            title: "No suppliers yet",
            description: "Add your first supplier to get started.",
          }}
          isEmpty={(data) => data.items.length === 0}
        >
          {(data) => (
            <>
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="pl-4">Supplier Name</TableHead>
                    <TableHead>GSTIN</TableHead>
                    <TableHead>City</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Contact Person</TableHead>
                    <TableHead>Phone</TableHead>
                    <TableHead className="pr-4">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((supplier) => (
                    <TableRow key={supplier.id}>
                      <TableCell className="pl-4">
                        <Link
                          href={`/suppliers/${supplier.id}`}
                          className="block max-w-[230px] truncate font-medium text-foreground hover:text-primary"
                        >
                          {supplier.name}
                        </Link>
                        <span className="text-caption text-muted-foreground">
                          {supplier.productsSupplied} products · {supplier.paymentTerms}
                        </span>
                      </TableCell>
                      <TableCell className="font-mono text-[12.5px] text-muted-foreground">
                        {supplier.gstin ?? <span className="font-sans italic">Unregistered</span>}
                      </TableCell>
                      <TableCell className="text-foreground">{supplier.city}</TableCell>
                      <TableCell className="text-muted-foreground">{supplier.supplierType}</TableCell>
                      <TableCell className="text-foreground">{supplier.primaryContactName}</TableCell>
                      <TableCell className="text-muted-foreground tabular">{supplier.phone}</TableCell>
                      <TableCell className="pr-4">
                        <StatusBadge status={supplier.status} />
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
