import type { Metadata } from "next";

import { SupplierInvoiceListScreen } from "@/components/payables/supplier-invoice-list-screen";

export const metadata: Metadata = {
  title: "Supplier Invoices",
  description: "What suppliers billed, checked against the order and the receipt.",
};

export default function SupplierInvoicesPage() {
  return <SupplierInvoiceListScreen />;
}
