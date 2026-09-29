import type { Metadata } from "next";

import { TransactionsScreen } from "@/components/inventory/transactions-screen";

export const metadata: Metadata = {
  title: "Inventory Transactions",
  description: "Every stock movement, with its source document.",
};

export default function TransactionsPage() {
  return <TransactionsScreen />;
}
