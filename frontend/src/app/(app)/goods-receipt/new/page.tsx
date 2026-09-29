"use client";

import { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import { PageHeader } from "@/components/common/page-header";
import { PrintButton } from "@/components/common/print-button";
import { GrnForm } from "@/components/procurement/grn-form";
import { Button } from "@/components/ui/button";

function CreateGrn() {
  // A receipt can be started from a PO's detail screen, which passes its id.
  const purchaseOrderId = useSearchParams().get("purchaseOrderId") ?? undefined;

  return (
    <div className="space-y-5">
      <div>
        <Button
          variant="ghost"
          size="sm"
          asChild
          className="-ml-2 mb-2 text-muted-foreground print:hidden"
        >
          <Link href="/goods-receipt">
            <ArrowLeft />
            All Goods Receipts
          </Link>
        </Button>
        <PageHeader
          title="Create Goods Receipt"
          description="Receive and verify the delivered items"
          actions={<PrintButton />}
        />
      </div>

      <GrnForm purchaseOrderId={purchaseOrderId} />
    </div>
  );
}

export default function CreateGrnPage() {
  return (
    <Suspense fallback={null}>
      <CreateGrn />
    </Suspense>
  );
}
