"use client";

import { use } from "react";

import { PoDetailScreen } from "@/components/procurement/po-detail-screen";

export default function PurchaseOrderDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return <PoDetailScreen id={decodeURIComponent(id)} />;
}
