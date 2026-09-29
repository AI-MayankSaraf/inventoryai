import type { Metadata } from "next";

import { UsersScreen } from "@/components/admin/users-screen";

export const metadata: Metadata = {
  title: "Users",
  description: "People who can use InventoryAI in your business.",
};

export default function UsersPage() {
  return <UsersScreen />;
}
