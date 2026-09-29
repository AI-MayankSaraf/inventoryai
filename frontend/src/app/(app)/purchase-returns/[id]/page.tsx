"use client";

import { use } from "react";

import { PurchaseReturnDetailScreen } from "@/components/payables/purchase-return-detail-screen";

export default function PurchaseReturnDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return <PurchaseReturnDetailScreen id={id} />;
}
