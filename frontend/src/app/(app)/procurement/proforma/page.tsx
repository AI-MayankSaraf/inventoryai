import type { Metadata } from "next";

import { ProformaListScreen } from "@/components/procurement/proforma-list-screen";

export const metadata: Metadata = {
  title: "Proforma Invoices",
  description: "Every supplier proforma, checked against its purchase order.",
};

export default function ProformaListPage() {
  return <ProformaListScreen />;
}
