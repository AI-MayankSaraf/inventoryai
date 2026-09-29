"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { PageHeader } from "@/components/common/page-header";
import { GrnForm } from "@/components/procurement/grn-form";
import { Button } from "@/components/ui/button";

/**
 * Edit a draft goods receipt. Only a draft gets here — the detail screen
 * offers this action for nothing else, and the backend refuses it for a
 * confirmed receipt (BR-GRN-08: corrections are reversals).
 */
export default function EditGrnPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);

  return (
    <div className="space-y-5">
      <div>
        <Button variant="ghost" size="sm" asChild className="-ml-2 mb-2 text-muted-foreground print:hidden">
          <Link href={`/goods-receipt/${id}`}>
            <ArrowLeft />
            Back to receipt
          </Link>
        </Button>
        <PageHeader
          title="Edit Goods Receipt"
          description="Change the quantities, transport details or remarks before confirming"
        />
      </div>

      <GrnForm goodsReceiptId={id} />
    </div>
  );
}
