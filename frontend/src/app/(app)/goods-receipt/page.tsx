import type { Metadata } from "next";

import { GrnListScreen } from "@/components/procurement/grn-list-screen";

export const metadata: Metadata = {
  title: "Goods Receipt",
  description: "Material received against your purchase orders.",
};

export default function GoodsReceiptPage() {
  return <GrnListScreen />;
}
