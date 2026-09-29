import type { Metadata } from "next";

import { AlertsScreen } from "@/components/alerts/alerts-screen";

export const metadata: Metadata = {
  title: "Alerts",
  description: "Everything that needs your attention.",
};

export default function AlertsPage() {
  return <AlertsScreen />;
}
