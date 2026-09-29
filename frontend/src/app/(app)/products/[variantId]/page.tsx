"use client";

import { use } from "react";

import { ProductDetailScreen } from "@/components/products/product-detail-screen";

export default function ProductDetailPage({
  params,
}: {
  params: Promise<{ variantId: string }>;
}) {
  const { variantId } = use(params);
  return <ProductDetailScreen variantId={decodeURIComponent(variantId)} />;
}
