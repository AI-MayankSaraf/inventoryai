"use client";

import { useRouter } from "next/navigation";
import { Building2, FileText, Package, Send } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useSupplierSession } from "@/hooks/use-supplier-session";
import { formatCurrency, formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

const STATUS_STYLE: Record<string, string> = {
  quoted: "bg-primary-subtle text-primary-subtle-foreground",
  under_review: "bg-warning-subtle text-warning-subtle-foreground",
  draft: "bg-muted text-muted-foreground",
  approved: "bg-success-subtle text-success-subtle-foreground",
};

function StatusPill({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[11.5px] font-medium capitalize",
        STATUS_STYLE[status] ?? "bg-muted text-muted-foreground",
      )}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}

function EmptyRow({ label }: { label: string }) {
  return <p className="px-4 py-6 text-center text-caption text-muted-foreground">{label}</p>;
}

/**
 * The whole point of "selected company context": this screen renders
 * different content purely because `useSupplierSession().activity` is
 * derived from the currently selected company, with no other prop or route
 * param driving it.
 */
export function SupplierDashboard() {
  const router = useRouter();
  const { principal, selectedCompany, activity, activityLoading, activityError } = useSupplierSession();
  const day = (value: string | null) => (value ? formatDate(value) : "—");

  if (!principal || !selectedCompany) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
        <Building2 className="size-8 text-muted-foreground" strokeWidth={1.6} />
        <p className="text-body text-muted-foreground">Pick a company to see its activity.</p>
        <Button variant="outline" onClick={() => router.push("/supplier-portal/select-company")}>
          Choose a company
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-section text-foreground">Working with {selectedCompany.name}</h1>
        <p className="mt-1 text-body text-muted-foreground">
          {[selectedCompany.city, selectedCompany.stateName].filter(Boolean).join(", ")}
          {selectedCompany.city || selectedCompany.stateName ? " · " : ""}Signed in as {principal.contactName}, for{" "}
          {selectedCompany.supplierName}
        </p>
      </div>

      {activityError && (
        <p className="rounded-md bg-destructive-subtle px-3 py-2 text-[13px] text-destructive-subtle-foreground" role="alert">
          {activityError}
        </p>
      )}

      <div className={cn("grid grid-cols-1 gap-4 lg:grid-cols-3", activityLoading && "opacity-60")} aria-busy={activityLoading}>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Send className="size-4 text-muted-foreground" />
              RFQs sent to you
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {activity.rfqs.length === 0 ? (
              <EmptyRow label={`No RFQs from ${selectedCompany.name} yet.`} />
            ) : (
              <ul className="divide-y divide-border">
                {activity.rfqs.map((rfq) => (
                  <li key={rfq.id} className="space-y-1 px-5 pb-4">
                    <div className="flex items-start justify-between gap-2">
                      <span className="font-mono text-[12.5px] text-foreground">{rfq.number}</span>
                      <StatusPill status={rfq.status} />
                    </div>
                    <p className="text-[13px] text-foreground">{rfq.subject}</p>
                    <p className="text-caption text-muted-foreground">
                      {rfq.lineCount} item{rfq.lineCount === 1 ? "" : "s"} · Sent {day(rfq.date)} · Needed by {day(rfq.expected)}
                    </p>
                    <p className="text-caption text-muted-foreground">
                      Your reply: <span className="capitalize">{rfq.invitationStatus.replace(/_/g, " ")}</span>
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileText className="size-4 text-muted-foreground" />
              Your quotations
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {activity.quotations.length === 0 ? (
              <EmptyRow label="No quotations submitted yet." />
            ) : (
              <ul className="divide-y divide-border">
                {activity.quotations.map((q) => (
                  <li key={q.id} className="space-y-1 px-5 pb-4">
                    <div className="flex items-start justify-between gap-2">
                      <span className="font-mono text-[12.5px] text-foreground">{q.number}</span>
                      <StatusPill status={q.status} />
                    </div>
                    <p className="text-[13px] text-muted-foreground">
                      {q.rfqNumber ? `Against ${q.rfqNumber} · ` : ""}{formatCurrency(q.totalAmount)}
                    </p>
                    <p className="text-caption text-muted-foreground">
                      Submitted {day(q.date)} · Valid till {day(q.validUntil)}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Package className="size-4 text-muted-foreground" />
              Purchase orders
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {activity.purchaseOrders.length === 0 ? (
              <EmptyRow label="No purchase orders yet." />
            ) : (
              <ul className="divide-y divide-border">
                {activity.purchaseOrders.map((po) => (
                  <li key={po.id} className="space-y-1 px-5 pb-4">
                    <div className="flex items-start justify-between gap-2">
                      <span className="font-mono text-[12.5px] text-foreground">{po.number}</span>
                      <StatusPill status={po.status} />
                    </div>
                    <p className="text-[13px] text-muted-foreground">
                      {po.lineCount} line item{po.lineCount === 1 ? "" : "s"} ·{" "}
                      {formatCurrency(po.totalAmount)} <span className="text-caption">incl. GST</span>
                    </p>
                    <p className="text-caption text-muted-foreground">
                      Raised {day(po.date)} · Expected {day(po.expected)}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <p className="text-caption text-muted-foreground">
        You see purchase orders once {selectedCompany.name} has sent them to you. Questions about an order go to
        your contact there.
      </p>
    </div>
  );
}
