import type { Metadata } from "next";

import { TransfersScreen } from "@/components/inventory/transfers-screen";

export const metadata: Metadata = {
  title: "Stock Transfers",
  description: "Every transfer between godowns, and the linked ledger entries it posted.",
};

export default function TransfersPage() {
  return <TransfersScreen />;
}
