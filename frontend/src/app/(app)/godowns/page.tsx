import type { Metadata } from "next";

import { GodownsScreen } from "@/components/godowns/godowns-screen";

export const metadata: Metadata = {
  title: "Godowns",
  description: "Your storage locations.",
};

export default function GodownsPage() {
  return <GodownsScreen />;
}
