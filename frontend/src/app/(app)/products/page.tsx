import type { Metadata } from "next";

import { ProductsListScreen } from "@/components/products/products-list-screen";

export const metadata: Metadata = {
  title: "Products",
  description: "Manage your product catalog.",
};

export default function ProductsPage() {
  return <ProductsListScreen />;
}
