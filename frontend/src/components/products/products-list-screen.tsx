"use client";

import * as React from "react";
import { FileUp, Package } from "lucide-react";

import { AsyncBoundary } from "@/components/common/async-state";
import { DataToolbar, TablePagination } from "@/components/common/data-toolbar";
import { FilterSelect } from "@/components/common/filter-select";
import { PageHeader } from "@/components/common/page-header";
import { ProductFormDialog } from "@/components/products/product-form-dialog";
import { ProductTable } from "@/components/products/product-table";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useListControls } from "@/hooks/use-api";
import { useBrands, useCategories, useProducts } from "@/hooks/use-catalog";

export function ProductsListScreen() {
  const controls = useListControls({ sort: "name" });
  const state = useProducts(controls.params);
  const categories = useCategories();
  const brands = useBrands();

  return (
    <div className="space-y-5">
      <PageHeader
        title="Products / SKUs"
        description="Manage your product catalog"
        actions={
          <>
            <Button variant="outline">
              <FileUp />
              Import Excel
            </Button>
            {/* Without this, a newly created product doesn't appear until
                the user navigates away and back — the list's own query has
                no way to know the dialog's mutation happened. */}
            <ProductFormDialog onSaved={() => state.refresh()} />
          </>
        }
      />

      <Card className="overflow-hidden">
        <DataToolbar
          searchPlaceholder="Search by SKU, name, brand..."
          searchValue={controls.q}
          onSearchChange={controls.setQ}
          filters={
            <>
              <FilterSelect
                placeholder="All Categories"
                options={(categories.data ?? []).map((c) => c.name)}
                value={controls.filters.categoryName}
                onValueChange={(v) => controls.setFilter("categoryName", v)}
              />
              <FilterSelect
                placeholder="All Brands"
                options={(brands.data ?? []).map((b) => b.name)}
                value={controls.filters.brandName}
                onValueChange={(v) => controls.setFilter("brandName", v)}
              />
            </>
          }
        />

        <AsyncBoundary
          state={state}
          empty={{
            icon: Package,
            title: "No products yet",
            description: "Add your first SKU to get started.",
          }}
          isEmpty={(data) => data.items.length === 0}
        >
          {(data) => (
            <>
              <ProductTable products={data.items} onSaved={() => state.refresh()} />
              <TablePagination page={1} pageSize={Math.max(data.items.length, 1)} total={data.total} />
            </>
          )}
        </AsyncBoundary>
      </Card>
    </div>
  );
}
