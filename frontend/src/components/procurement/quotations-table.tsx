"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { StatusBadge, ProvenanceBadge } from "@/components/common/status-badge";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { procurementApi } from "@/lib/api";
import { formatCurrency, formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

export function QuotationsTable({ quotations }: { quotations: procurementApi.QuotationListRow[] }) {
  const router = useRouter();

  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="pl-4">Quotation</TableHead>
          <TableHead>Supplier</TableHead>
          <TableHead>Against RFQ</TableHead>
          <TableHead>Valid Until</TableHead>
          <TableHead className="text-right">Items</TableHead>
          <TableHead className="text-right">Total</TableHead>
          <TableHead>Source</TableHead>
          <TableHead className="pr-4">Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {quotations.map((q) => (
          <TableRow
            key={q.id}
            className="cursor-pointer"
            onClick={() => router.push(`/procurement/quotations/${q.id}`)}
          >
            <TableCell className="pl-4">
              <Link
                href={`/procurement/quotations/${q.id}`}
                onClick={(e) => e.stopPropagation()}
                className="font-mono text-[12.5px] font-medium text-foreground hover:text-primary"
              >
                {q.quotationNumber}
              </Link>
              <span className="block text-caption text-muted-foreground">
                {formatDate(q.quotationDate)}
              </span>
            </TableCell>
            <TableCell className="max-w-[190px] truncate text-foreground">{q.supplierName}</TableCell>
            <TableCell className="font-mono text-[12.5px] text-muted-foreground">
              {q.rfqNumber ?? "—"}
            </TableCell>
            <TableCell className={cn("text-muted-foreground", q.isExpired && "text-destructive")}>
              {q.validUntil ? formatDate(q.validUntil) : "—"}
              {q.isExpired && " · Expired"}
            </TableCell>
            <TableCell className="text-right text-muted-foreground tabular">{q.itemCount}</TableCell>
            <TableCell className="text-right font-medium text-foreground tabular">
              {formatCurrency(q.totalAmount)}
            </TableCell>
            <TableCell>
              {q.source === "ai_extracted" ? (
                <ProvenanceBadge provenance="ai_extracted" confidence={q.extractionConfidence} />
              ) : (
                <Badge variant="neutral">{q.source === "manual" ? "Manual Entry" : q.source}</Badge>
              )}
            </TableCell>
            <TableCell className="pr-4">
              <StatusBadge status={q.status} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
