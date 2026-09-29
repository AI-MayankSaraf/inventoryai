import type { Metadata } from "next";

import { PageHeader } from "@/components/common/page-header";
import { InventoryAssistant } from "@/components/ai/inventory-assistant";

export const metadata: Metadata = {
  title: "AI Assistant",
  description: "Ask questions about your inventory in plain English.",
};

export default function AssistantPage() {
  return (
    <div className="space-y-5">
      <PageHeader
        title="AI Inventory Assistant"
        description="Ask about stock, godowns, suppliers or receipts — in plain English"
      />
      <InventoryAssistant />
    </div>
  );
}
