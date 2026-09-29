import type { Metadata } from "next";

import { CurrentStockScreen } from "@/components/inventory/current-stock-screen";

export const metadata: Metadata = {
  title: "Current Stock",
  description: "Real-time inventory across all godowns.",
};

export default function CurrentStockPage() {
  return <CurrentStockScreen />;
}
