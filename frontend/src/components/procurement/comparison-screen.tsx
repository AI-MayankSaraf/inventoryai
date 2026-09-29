"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { GitCompareArrows } from "lucide-react";

import { AsyncBoundary } from "@/components/common/async-state";
import { PageHeader } from "@/components/common/page-header";
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
import { useRfqs } from "@/hooks/use-procurement";
import { formatCurrency, formatDate } from "@/lib/format";

/**
 * A comparison is always scoped to one RFQ — this is the chooser that gets
 * you there: every RFQ that has at least one quotation in, ready to compare.
 */
export function ComparisonScreen() {
  const router = useRouter();
  const controls = useListControls({ sort: "-rfqDate" });
  const state = useRfqs(controls.params);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Quotation Comparison"
        description="Pick an RFQ with quotes in to compare suppliers side by side"
      />

      <Card className="overflow-hidden">
        <AsyncBoundary
          state={state}
          empty={{
            icon: GitCompareArrows,
            title: "No RFQs to compare yet",
            description: "Once suppliers respond to an RFQ, it will show up here.",
          }}
          isEmpty={(data) => data.items.filter((r) => r.quotesReceived > 0).length === 0}
        >
          {(data) => {
            const rows = data.items.filter((r) => r.quotesReceived > 0);
            return (
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="pl-4">RFQ Number</TableHead>
                    <TableHead>Subject</TableHead>
                    <TableHead>Date</TableHead>
                    <TableHead className="text-right">Suppliers</TableHead>
                    <TableHead className="text-right">Quotes In</TableHead>
                    <TableHead className="text-right">Est. Value</TableHead>
                    <TableHead className="pr-4">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((rfq) => (
                    <TableRow
                      key={rfq.id}
                      className="cursor-pointer"
                      onClick={() => router.push(`/procurement/comparison/${rfq.id}`)}
                    >
                      <TableCell className="pl-4">
                        <Link
                          href={`/procurement/comparison/${rfq.id}`}
                          onClick={(e) => e.stopPropagation()}
                          className="font-mono text-[12.5px] font-medium text-foreground hover:text-primary"
                        >
                          {rfq.rfqNumber}
                        </Link>
                      </TableCell>
                      <TableCell className="max-w-[260px] truncate font-medium text-foreground">
                        {rfq.subject}
                      </TableCell>
                      <TableCell className="text-muted-foreground">{formatDate(rfq.rfqDate)}</TableCell>
                      <TableCell className="text-right text-muted-foreground tabular">
                        {rfq.supplierCount}
                      </TableCell>
                      <TableCell className="text-right tabular">
                        {rfq.quotesReceived}/{rfq.supplierCount}
                      </TableCell>
                      <TableCell className="text-right text-foreground tabular">
                        {formatCurrency(rfq.estimatedValue)}
                      </TableCell>
                      <TableCell className="pr-4">
                        <StatusBadge status={rfq.status} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            );
          }}
        </AsyncBoundary>
      </Card>
    </div>
  );
}
