import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { PageHeader } from "@/components/common/page-header";
import { QuotationForm } from "@/components/procurement/quotation-form";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = {
  title: "Enter Quotation",
  description: "Record a supplier quotation that arrived by phone or on paper.",
};

export default function NewQuotationPage() {
  return (
    <div className="space-y-5">
      <div>
        <Button variant="ghost" size="sm" asChild className="-ml-2 mb-2 text-muted-foreground">
          <Link href="/procurement/quotations">
            <ArrowLeft />
            All Quotations
          </Link>
        </Button>
        <PageHeader
          title="Enter a Quotation"
          description="For a quote that arrived by phone, email or on paper — not through the AI pipeline"
        />
      </div>

      <QuotationForm />
    </div>
  );
}
