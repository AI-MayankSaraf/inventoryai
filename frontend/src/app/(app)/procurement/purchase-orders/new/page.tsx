import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { PageHeader } from "@/components/common/page-header";
import { PrintButton } from "@/components/common/print-button";
import { PoForm } from "@/components/procurement/po-form";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = {
  title: "Create Purchase Order",
  description: "Raise a new purchase order.",
};

export default function CreatePoPage() {
  return (
    <div className="space-y-5">
      <div>
        <Button variant="ghost" size="sm" asChild className="-ml-2 mb-2 text-muted-foreground">
          <Link href="/procurement/purchase-orders">
            <ArrowLeft />
            All Purchase Orders
          </Link>
        </Button>
        <PageHeader
          title="Create Purchase Order"
          description="Link an RFQ to pull in its items, or add items manually"
          actions={<PrintButton />}
        />
      </div>

      <PoForm />
    </div>
  );
}
