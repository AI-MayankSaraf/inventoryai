"use client";

import * as React from "react";
import Link from "next/link";
import { Eye, MoreHorizontal, PackagePlus, Pencil } from "lucide-react";

import { OwnerOnlyGate } from "@/components/common/permission-gate";
import { StatusBadge } from "@/components/common/status-badge";
import { ProductFormDialog } from "@/components/products/product-form-dialog";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { catalogApi } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import type { StockState } from "@/types";
import { cn } from "@/lib/utils";

/** Same threshold logic the inventory service uses — computed here only for display. */
function stockStatus(totalStock: number, reorderPoint: number): StockState {
  if (totalStock <= 0) return "out_of_stock";
  if (totalStock <= reorderPoint) return "low_stock";
  return "in_stock";
}

export function ProductTable({
  products,
  onSaved,
}: {
  products: catalogApi.ProductListRow[];
  /** Called after an in-row edit saves, so the parent list can refetch — its
   * own query has no other way to learn the edit happened. */
  onSaved?: () => void;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="pl-4">Product</TableHead>
          <TableHead>SKU</TableHead>
          <TableHead>Brand</TableHead>
          <TableHead>Category</TableHead>
          <TableHead>Unit</TableHead>
          <TableHead className="text-right">Stock</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="w-10 pr-3" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {products.map((product) => {
          const status = stockStatus(product.totalStock, product.reorderPoint);
          return (
            <TableRow key={product.id}>
              <TableCell className="pl-4">
                <Link href={`/products/${product.id}`} className="group flex items-center gap-3">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-md border border-border bg-muted text-[17px]">
                    {product.displayEmoji ?? "📦"}
                  </span>
                  <span className="min-w-0">
                    <span className="block max-w-[230px] truncate font-medium text-foreground group-hover:text-primary">
                      {product.name}
                    </span>
                    <span className="block text-caption text-muted-foreground">
                      {product.categoryName || "Uncategorised"}
                    </span>
                  </span>
                </Link>
              </TableCell>
              <TableCell className="font-mono text-[12.5px] text-muted-foreground">
                {product.sku}
              </TableCell>
              <TableCell className="text-foreground">{product.brandName || "—"}</TableCell>
              <TableCell className="text-muted-foreground">{product.categoryName || "—"}</TableCell>
              <TableCell className="text-muted-foreground">{product.uomCode}</TableCell>
              <TableCell
                className={cn(
                  "text-right font-semibold tabular",
                  status === "out_of_stock"
                    ? "text-destructive"
                    : status === "low_stock"
                      ? "text-warning-subtle-foreground"
                      : "text-foreground",
                )}
              >
                {formatNumber(product.totalStock)}
              </TableCell>
              <TableCell>
                <StatusBadge status={status} />
              </TableCell>
              <TableCell className="pr-3">
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${product.name}`}>
                      <MoreHorizontal />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem asChild>
                      <Link href={`/products/${product.id}`}>
                        <Eye />
                        View details
                      </Link>
                    </DropdownMenuItem>
                    <OwnerOnlyGate>
                      <ProductFormDialog
                        variantId={product.id}
                        onSaved={onSaved}
                        trigger={
                          <DropdownMenuItem onSelect={(e) => e.preventDefault()}>
                            <Pencil />
                            Edit product
                          </DropdownMenuItem>
                        }
                      />
                    </OwnerOnlyGate>
                    <DropdownMenuItem asChild>
                      <Link href="/procurement/rfq">
                        <PackagePlus />
                        Create RFQ
                      </Link>
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
