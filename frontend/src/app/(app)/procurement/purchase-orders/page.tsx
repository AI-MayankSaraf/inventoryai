import type { Metadata } from "next";

import { PoListScreen } from "@/components/procurement/po-list-screen";

export const metadata: Metadata = {
  title: "Purchase Orders",
  description: "Every order you have raised with suppliers.",
};

export default function PurchaseOrdersPage() {
  return <PoListScreen />;
}
