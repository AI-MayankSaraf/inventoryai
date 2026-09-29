import type { Metadata } from "next";

import { RolesScreen } from "@/components/admin/roles-screen";

export const metadata: Metadata = {
  title: "Roles & Permissions",
  description: "What each role is allowed to see and do.",
};

export default function RolesPage() {
  return <RolesScreen />;
}
