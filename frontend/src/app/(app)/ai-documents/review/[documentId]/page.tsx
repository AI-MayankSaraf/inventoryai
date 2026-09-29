"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { PageHeader } from "@/components/common/page-header";
import { ExtractionReview } from "@/components/documents/extraction-review";
import { Button } from "@/components/ui/button";

export default function ExtractionReviewPage({
  params,
}: {
  params: Promise<{ documentId: string }>;
}) {
  const { documentId } = use(params);

  return (
    <div className="space-y-5">
      <div>
        <Button
          variant="ghost"
          size="sm"
          asChild
          className="-ml-2 mb-2 text-muted-foreground"
        >
          <Link href="/ai-documents">
            <ArrowLeft />
            All Documents
          </Link>
        </Button>
        <PageHeader
          title="Review Extraction"
          description="Check what AI read before it becomes business data"
        />
      </div>

      <ExtractionReview documentId={documentId} />
    </div>
  );
}
