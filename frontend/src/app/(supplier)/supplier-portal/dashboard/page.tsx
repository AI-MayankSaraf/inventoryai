import { SupplierDashboard } from "@/components/supplier-portal/supplier-dashboard";
import { SupplierPortalShell } from "@/components/supplier-portal/supplier-portal-shell";

export default function SupplierDashboardPage() {
  return (
    <SupplierPortalShell>
      <SupplierDashboard />
    </SupplierPortalShell>
  );
}
