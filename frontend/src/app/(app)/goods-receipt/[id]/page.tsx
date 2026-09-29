"use client";

import { use } from "react";

import { GrnDetailScreen } from "@/components/procurement/grn-detail-screen";

export default function GrnDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return <GrnDetailScreen id={id} />;
}
