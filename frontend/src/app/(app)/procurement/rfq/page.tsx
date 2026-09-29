import type { Metadata } from "next";

import { RfqListScreen } from "@/components/procurement/rfq-list-screen";

export const metadata: Metadata = {
  title: "RFQ",
  description: "Requests for quotation sent to your suppliers.",
};

export default function RfqListPage() {
  return <RfqListScreen />;
}
