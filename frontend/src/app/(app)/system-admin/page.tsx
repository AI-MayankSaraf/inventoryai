"use client";

import Link from "next/link";
import { ShieldAlert } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { Button } from "@/components/ui/button";
import { SystemAdminScreen } from "@/components/admin/system-admin-screen";
import { usePermission } from "@/hooks/use-session";

export default function SystemAdminPage() {
  const canView = usePermission("platform.companies.view");

  if (!canView) {
    return (
      <EmptyState
        icon={ShieldAlert}
        title="Access restricted"
        description="This area is only available to a platform administrator. Sign in with a platform admin demo account from the login page to see it."
        action={
          <Button asChild>
            <Link href="/dashboard">Back to Dashboard</Link>
          </Button>
        }
        className="mt-16"
      />
    );
  }

  return <SystemAdminScreen />;
}
