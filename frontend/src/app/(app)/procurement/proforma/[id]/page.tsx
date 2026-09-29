"use client";

import { use } from "react";

import { ProformaDetailScreen } from "@/components/procurement/proforma-detail-screen";

export default function ProformaDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return <ProformaDetailScreen id={decodeURIComponent(id)} />;
}
