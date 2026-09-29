import type { Metadata } from "next";

import { QuotationsListScreen } from "@/components/procurement/quotations-list-screen";

export const metadata: Metadata = {
  title: "Supplier Quotations",
  description: "Quotations received from your suppliers.",
};

export default function QuotationsPage() {
  return <QuotationsListScreen />;
}
