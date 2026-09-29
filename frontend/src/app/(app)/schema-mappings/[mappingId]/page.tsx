"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { PageHeader } from "@/components/common/page-header";
import { SchemaMappingDetailScreen } from "@/components/documents/schema-mapping-screen";
import { Button } from "@/components/ui/button";

export default function SchemaMappingPage({
  params,
}: {
  params: Promise<{ mappingId: string }>;
}) {
  const { mappingId } = use(params);

  return (
    <div className="space-y-5">
      <div>
        <Button variant="ghost" size="sm" asChild className="-ml-2 mb-2 text-muted-foreground">
          <Link href="/schema-mappings">
            <ArrowLeft />
            All Mappings
          </Link>
        </Button>
        <PageHeader
          title="Column Mapping"
          description="Map each of the supplier's columns to what it means in your data"
        />
      </div>

      <SchemaMappingDetailScreen mappingId={mappingId} />
    </div>
  );
}
