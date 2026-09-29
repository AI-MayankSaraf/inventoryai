"use client";

import * as React from "react";
import { AlertTriangle, Brain, CheckCircle2, Loader2, RefreshCw } from "lucide-react";

import { FormError } from "@/components/common/async-state";
import { SectionCard } from "@/components/common/section-card";
import { Button } from "@/components/ui/button";
import { useEmbeddingStatus, useRebuildEmbeddings } from "@/hooks/use-documents";
import { usePermission } from "@/hooks/use-session";
import { formatRelativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Product matching by meaning (rung 6 of the match ladder).
 *
 * Shows how much of the catalogue is indexed and lets someone who manages
 * AI mappings re-index it. Day to day nothing needs doing here — matching
 * tops the index up before each document — so this is for after the
 * embedding model changes, or to index a large catalogue up front.
 */
export function EmbeddingIndexCard() {
  const canView = usePermission("ai.view");
  const canManage = usePermission("ai.manage_mappings");
  const status = useEmbeddingStatus(canView);
  const rebuild = useRebuildEmbeddings(() => status.refresh());

  const data = status.data;
  const rebuilding = !!data?.rebuilding;

  // Poll while a rebuild runs in the background.
  const { refresh } = status;
  React.useEffect(() => {
    if (!rebuilding) return;
    const t = window.setInterval(refresh, 1500);
    return () => window.clearInterval(t);
  }, [rebuilding, refresh]);

  if (!canView) return null;

  const pct = data && data.totalProducts > 0 ? Math.round((data.embedded / data.totalProducts) * 100) : 0;

  return (
    <div data-testid="embedding-index-card">
      <SectionCard
        title="Product matching by meaning"
        description="Finds your product even when a supplier words it differently"
      >
        <div className="space-y-3.5 p-4">
          {!data ? (
            <p className="flex items-center gap-2 text-caption text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin" /> Checking…
            </p>
          ) : !data.configured ? (
            <div className="flex gap-2.5 rounded-lg bg-muted/50 px-3 py-2.5 text-[12.5px] text-muted-foreground">
              <Brain className="mt-0.5 size-4 shrink-0" />
              <p>
                Off — no embedding model is configured. Set <code className="font-mono">AI_PROVIDER</code> and{" "}
                <code className="font-mono">AI_EMBEDDING_MODEL</code> on the server to turn it on. Matching still
                works on codes and wording.
              </p>
            </div>
          ) : (
            <>
              <div className="flex items-start gap-3">
                <span
                  className={cn(
                    "flex size-9 shrink-0 items-center justify-center rounded-md",
                    data.pending === 0 ? "bg-success-subtle text-success-subtle-foreground" : "bg-ai-subtle text-ai-subtle-foreground",
                  )}
                >
                  {rebuilding ? <Loader2 className="size-4 animate-spin" /> : data.pending === 0 ? <CheckCircle2 className="size-4" /> : <Brain className="size-4" />}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-[13.5px] font-medium text-foreground" data-testid="embedding-index-summary">
                    {rebuilding
                      ? `Indexing… ${data.rebuildEmbedded} done`
                      : `${data.embedded} of ${data.totalProducts} products indexed`}
                  </p>
                  <p className="text-caption text-muted-foreground">
                    {data.model} · {data.provider} · {data.dimensions} dimensions
                    {data.lastGeneratedAt ? ` · updated ${formatRelativeTime(data.lastGeneratedAt)}` : ""}
                  </p>
                </div>
              </div>

              <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
                <div
                  className={cn("h-full rounded-full transition-all", pct === 100 ? "bg-success" : "bg-ai-border")}
                  style={{ width: `${pct}%` }}
                />
              </div>

              {data.pending > 0 && !rebuilding && (
                <p className="text-caption text-muted-foreground">
                  {data.pending} new or changed product{data.pending === 1 ? "" : "s"} will be indexed automatically
                  before the next document is matched, or now with Update.
                </p>
              )}
              {data.lastError && (
                <p className="flex items-start gap-1.5 text-caption text-destructive" role="alert">
                  <AlertTriangle className="mt-px size-3.5 shrink-0" />
                  {data.lastError}
                </p>
              )}
              <p className="text-caption text-muted-foreground">
                Suggestions only — a person always confirms which product a supplier line is.
              </p>

              {canManage && (
                <div className="flex flex-wrap justify-end gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={rebuilding || rebuild.isPending}
                    onClick={() => void rebuild.run(true)}
                    title="Re-index every product — use after changing the embedding model"
                  >
                    Re-index all
                  </Button>
                  <Button
                    size="sm"
                    disabled={rebuilding || rebuild.isPending || data.pending === 0}
                    onClick={() => void rebuild.run(false)}
                    data-testid="embedding-update"
                  >
                    <RefreshCw className={cn(rebuilding && "animate-spin")} />
                    {rebuilding ? "Indexing…" : "Update"}
                  </Button>
                </div>
              )}
            </>
          )}
          <FormError message={rebuild.error ?? status.error} />
        </div>
      </SectionCard>
    </div>
  );
}
