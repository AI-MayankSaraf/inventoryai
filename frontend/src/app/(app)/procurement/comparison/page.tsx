import type { Metadata } from "next";

import { ComparisonScreen } from "@/components/procurement/comparison-screen";

export const metadata: Metadata = {
  title: "Quotation Comparison",
  description: "Compare supplier quotations side by side.",
};

export default function ComparisonChooserPage() {
  return <ComparisonScreen />;
}
