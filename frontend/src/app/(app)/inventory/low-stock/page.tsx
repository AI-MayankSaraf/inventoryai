import type { Metadata } from "next";

import { PageHeader } from "@/components/common/page-header";
import { LowStockScreen } from "@/components/inventory/low-stock-screen";

export const metadata: Metadata = {
  title: "Low Stock",
  description: "Products below their reorder point, with a suggested order quantity.",
};

export default function LowStockPage() {
  return (
    <div className="space-y-5">
      <PageHeader
        title="Low Stock"
        description="Products below their reorder point — select items below to build an RFQ"
      />

      <LowStockScreen />
    </div>
  );
}
