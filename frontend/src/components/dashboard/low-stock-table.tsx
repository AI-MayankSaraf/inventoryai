import Link from "next/link";
import { FilePlus2 } from "lucide-react";

import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { DashboardSummary } from "@/types";

type LowStockRow = DashboardSummary["lowStock"][number];
import { cn } from "@/lib/utils";

export function LowStockTable({ rows }: { rows: LowStockRow[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="pl-4">Product</TableHead>
          <TableHead>SKU</TableHead>
          <TableHead>Godown</TableHead>
          <TableHead className="text-right">Current</TableHead>
          <TableHead className="text-right">Reorder At</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="w-10 pr-3" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={`${row.productVariantId}-${row.godownName}`}>
            <TableCell className="max-w-[210px] truncate pl-4 font-medium text-foreground">
              {row.productName}
            </TableCell>
            <TableCell className="text-muted-foreground">{row.sku}</TableCell>
            <TableCell className="text-muted-foreground">{row.godownName}</TableCell>
            <TableCell
              className={cn(
                "text-right font-semibold tabular",
                row.status === "out_of_stock"
                  ? "text-destructive"
                  : "text-warning-subtle-foreground",
              )}
            >
              {row.currentStock}
            </TableCell>
            <TableCell className="text-right text-muted-foreground tabular">
              {row.reorderPoint}
            </TableCell>
            <TableCell>
              <StatusBadge status={row.status} />
            </TableCell>
            <TableCell className="pr-3">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Create RFQ for ${row.productName}`}
                    asChild
                  >
                    <Link href="/procurement/rfq">
                      <FilePlus2 />
                    </Link>
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Create RFQ</TooltipContent>
              </Tooltip>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
