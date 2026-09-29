import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { PageHeader } from "@/components/common/page-header";
import { PrintButton } from "@/components/common/print-button";
import { RfqForm } from "@/components/procurement/rfq-form";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = {
  title: "Create RFQ",
  description: "Request quotation from suppliers.",
};

export default function CreateRfqPage() {
  return (
    <div className="space-y-5">
      <div>
        <Button variant="ghost" size="sm" asChild className="-ml-2 mb-2 text-muted-foreground">
          <Link href="/procurement/rfq">
            <ArrowLeft />
            All RFQs
          </Link>
        </Button>
        <PageHeader
          title="Create RFQ"
          description="Request quotation from suppliers"
          actions={<PrintButton />}
        />
      </div>

      <RfqForm />
    </div>
  );
}
