"use client";

import { use } from "react";

import { QuotationComparison } from "@/components/procurement/quotation-comparison";

export default function ComparisonDetailPage({
  params,
}: {
  params: Promise<{ rfqId: string }>;
}) {
  const { rfqId } = use(params);
  return <QuotationComparison rfqId={rfqId} />;
}
