"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { PageHeader } from "@/components/common/page-header";
import { SupplierInvoiceForm } from "@/components/payables/supplier-invoice-form";
import { Button } from "@/components/ui/button";

export default function CreateSupplierInvoicePage() {
  return (
    <div className="space-y-5">
      <div>
        <Button variant="ghost" size="sm" asChild className="-ml-2 mb-2 text-muted-foreground">
          <Link href="/supplier-invoices">
            <ArrowLeft />
            All Supplier Invoices
          </Link>
        </Button>
        <PageHeader
          title="Enter Supplier Invoice"
          description="Capture what the supplier billed against a purchase order and its receipt"
        />
      </div>

      <SupplierInvoiceForm />
    </div>
  );
}
