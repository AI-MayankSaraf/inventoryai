import type { Metadata } from "next";

import { PurchaseReturnListScreen } from "@/components/payables/purchase-return-list-screen";

export const metadata: Metadata = {
  title: "Purchase Returns",
  description: "Goods sent back to a supplier, and the stock movement that recorded it.",
};

export default function PurchaseReturnsPage() {
  return <PurchaseReturnListScreen />;
}
