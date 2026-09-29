import type { Metadata } from "next";

import { SettingsScreen } from "@/components/admin/settings-screen";

export const metadata: Metadata = {
  title: "Settings",
  description: "Business, numbering, tax and AI settings.",
};

export default function SettingsPage() {
  return <SettingsScreen />;
}
