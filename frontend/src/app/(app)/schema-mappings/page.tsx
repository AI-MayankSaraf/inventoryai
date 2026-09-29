import type { Metadata } from "next";

import { SchemaMappingsScreen } from "@/components/documents/schema-mapping-screen";

export const metadata: Metadata = {
  title: "Schema Mappings",
  description: "How each supplier's file columns map to your business fields.",
};

export default function SchemaMappingsPage() {
  return <SchemaMappingsScreen />;
}
