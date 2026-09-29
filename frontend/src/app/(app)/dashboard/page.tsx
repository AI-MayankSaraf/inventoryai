"use client";

import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  ClipboardList,
  IndianRupee,
  Package,
  PackageX,
} from "lucide-react";

import { StockStatusChart } from "@/components/dashboard/stock-status-chart";
import { LowStockTable } from "@/components/dashboard/low-stock-table";
import { RecentActivity } from "@/components/dashboard/recent-activity";
import { ProcurementOverview } from "@/components/dashboard/procurement-overview";
import { KpiCard } from "@/components/common/kpi-card";
import { PageHeader } from "@/components/common/page-header";
import { SectionCard } from "@/components/common/section-card";
import { Button } from "@/components/ui/button";
import { AsyncBoundary } from "@/components/common/async-state";
import { useDashboard } from "@/hooks/use-ops";
import { useSession } from "@/hooks/use-session";
import { formatCurrency, formatDate, formatNumber, greeting } from "@/lib/format";

export default function DashboardPage() {
  const { user } = useSession();
  // One query feeds every tile, the chart, the low-stock table and the feed, so
  // a KPI can never disagree with the list behind it (I12).
  const state = useDashboard();
  const today = new Date();

  return (
    <AsyncBoundary state={state}>
      {({ kpis, stockStatus, lowStock, activity, procurement }) => (
    <div className="space-y-5">
      <PageHeader
        title={`${greeting(today)}, ${user?.fullName ?? "there"}`}
        description="Here's what's happening in your business today."
        actions={
          <div className="text-right">
            <p className="text-caption text-muted-foreground">Today</p>
            <p className="text-[13.5px] font-medium text-foreground">
              {formatDate(today)}
            </p>
          </div>
        }
      />

      {/* ---------- KPIs ---------- */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Total SKUs"
          value={formatNumber(kpis.totalSkus)}
          hint={`${kpis.skusAddedThisMonth} added this month`}
          icon={Package}
          tone="default"
        />
        <KpiCard
          label="Low Stock Items"
          value={formatNumber(kpis.lowStockItems)}
          hint={`${kpis.outOfStock} of them are out of stock`}
          icon={AlertTriangle}
          tone="warning"
        />
        <KpiCard
          label="Pending POs"
          value={formatNumber(kpis.pendingPos)}
          hint={`${formatCurrency(kpis.poValuePending)} awaiting delivery`}
          icon={ClipboardList}
          tone="info"
        />
        <KpiCard
          label="Inventory Value"
          value={formatCurrency(kpis.inventoryValue)}
          hint={`Across ${kpis.godownCount} godowns`}
          icon={IndianRupee}
          tone="success"
        />
      </div>

      {/* ---------- Stock status + low stock ---------- */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <SectionCard
          title="Stock Status"
          description="Share of SKUs by availability"
          className="lg:col-span-4"
          footer={
            <span>
              {kpis.outOfStock} out of stock · {kpis.lowStockItems} below reorder point
            </span>
          }
        >
          <StockStatusChart data={stockStatus} />
        </SectionCard>

        <SectionCard
          title="Low Stock Items"
          description="Below reorder point — action needed"
          className="lg:col-span-8"
          action={
            <Button variant="ghost" size="sm" asChild>
              <Link href="/inventory/low-stock">
                View all
                <ArrowRight />
              </Link>
            </Button>
          }
          footer={
            <span>
              Showing {lowStock.length} of {kpis.lowStockItems} items below reorder point
            </span>
          }
        >
          <LowStockTable rows={lowStock} />
        </SectionCard>
      </div>

      {/* ---------- Procurement + activity ---------- */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <SectionCard
          title="Procurement Overview"
          description="Where your purchase pipeline stands"
          className="lg:col-span-5"
        >
          <ProcurementOverview stats={procurement} />
        </SectionCard>

        <SectionCard
          title="Recent Activity"
          description="Latest documents and alerts"
          className="lg:col-span-7"
          action={
            <Button variant="ghost" size="sm" asChild>
              <Link href="/reports">
                View all
                <ArrowRight />
              </Link>
            </Button>
          }
        >
          <RecentActivity items={activity} />
        </SectionCard>
      </div>

      {/* ---------- Out of stock callout ---------- */}
      <div className="flex flex-col gap-3 rounded-xl border border-destructive-subtle bg-destructive-subtle/60 px-4 py-3.5 sm:flex-row sm:items-center">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-destructive-subtle text-destructive-subtle-foreground">
          <PackageX className="size-4" strokeWidth={2} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[13.5px] font-medium text-destructive-subtle-foreground">
            {kpis.outOfStock} products are completely out of stock
          </p>
          <p className="text-caption text-destructive-subtle-foreground/85">
            Raise an RFQ now so replenishment is not delayed further.
          </p>
        </div>
        <Button size="sm" variant="destructive" asChild className="shrink-0">
          <Link href="/procurement/rfq">Create RFQ</Link>
        </Button>
      </div>
    </div>
      )}
    </AsyncBoundary>
  );
}
