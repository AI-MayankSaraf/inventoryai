"use client";

import { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import { PageHeader } from "@/components/common/page-header";
import { PurchaseReturnForm } from "@/components/payables/purchase-return-form";
import { Button } from "@/components/ui/button";

function CreatePurchaseReturn() {
  // Raised from a GRN's detail screen, which passes its id.
  const goodsReceiptId = useSearchParams().get("goodsReceiptId") ?? undefined;

  return (
    <div className="space-y-5">
      <div>
        <Button variant="ghost" size="sm" asChild className="-ml-2 mb-2 text-muted-foreground">
          <Link href="/purchase-returns">
            <ArrowLeft />
            All Purchase Returns
          </Link>
        </Button>
        <PageHeader
          title="Raise Purchase Return"
          description="Send rejected or excess goods back to the supplier"
        />
      </div>

      <PurchaseReturnForm goodsReceiptId={goodsReceiptId} />
    </div>
  );
}

export default function CreatePurchaseReturnPage() {
  return (
    <Suspense fallback={null}>
      <CreatePurchaseReturn />
    </Suspense>
  );
}
