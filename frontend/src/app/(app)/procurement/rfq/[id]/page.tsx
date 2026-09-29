"use client";

import { use } from "react";

import { RfqDetailScreen } from "@/components/procurement/rfq-detail-screen";

export default function RfqDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return <RfqDetailScreen id={id} />;
}
