import type { Metadata } from "next";

import { SuppliersListScreen } from "@/components/suppliers/suppliers-list-screen";

export const metadata: Metadata = {
  title: "Suppliers",
  description: "Manage your supplier list.",
};

export default function SuppliersPage() {
  return <SuppliersListScreen />;
}
