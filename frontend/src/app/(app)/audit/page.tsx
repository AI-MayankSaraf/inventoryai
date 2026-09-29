import type { Metadata } from "next";

import { AuditLogScreen } from "@/components/admin/audit-log-screen";

export const metadata: Metadata = {
  title: "Audit Trail",
  description: "Who did what, when, across your company.",
};

export default function AuditPage() {
  return <AuditLogScreen />;
}
