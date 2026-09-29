"use client";

import { use } from "react";

import { SupplierInvoiceDetailScreen } from "@/components/payables/supplier-invoice-detail-screen";

export default function SupplierInvoiceDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return <SupplierInvoiceDetailScreen id={id} />;
}
