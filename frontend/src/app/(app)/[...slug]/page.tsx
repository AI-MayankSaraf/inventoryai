import Link from "next/link";
import { ArrowLeft, Hammer } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

/**
 * Catch-all placeholder for routes whose screen has not been built yet, so every
 * sidebar link is clickable during screen-by-screen review. Real pages added
 * under (app) take precedence over this route automatically.
 */
const ROADMAP: Record<string, string> = {
  "products": "Screen 3 — Product / SKU Management",
  "suppliers": "Screen 4 — Supplier Management",
  "godowns": "Godown Management",
  "procurement/rfq": "Screen 5 — RFQ Creation",
  "ai-documents": "Screen 6 — AI Document Upload / Processing",
  "procurement/quotations": "Screen 7 — AI Extraction Review",
  "procurement/comparison": "Screen 8 — Quotation Comparison",
  "procurement/purchase-orders": "Screen 9 — Purchase Order",
  "procurement/proforma": "Screen 10 — Proforma Invoice",
  "goods-receipt": "Screen 11 — Goods Receipt / GRN",
  "inventory/current-stock": "Screen 12 — Current Inventory",
  "inventory/by-godown": "Screen 12 — Stock by Godown",
  "inventory/transactions": "Screen 13 — Inventory Transactions",
  "inventory/low-stock": "Screen 14 — Low Stock",
  "alerts": "Screen 16 — Alerts",
  "reports": "Screen 17 — Reports",
  "users": "User Management",
  "settings": "Settings",
};

export default async function ComingSoonPage({
  params,
}: {
  params: Promise<{ slug: string[] }>;
}) {
  const { slug } = await params;
  const path = slug.join("/");
  const title = ROADMAP[path] ?? "This screen";

  return (
    <Card className="py-6">
      <EmptyState
        icon={Hammer}
        title={title}
        description="Not built yet — screens are being designed and approved one at a time."
        action={
          <Button variant="outline" asChild>
            <Link href="/dashboard">
              <ArrowLeft />
              Back to Dashboard
            </Link>
          </Button>
        }
      />
    </Card>
  );
}
