import * as React from "react";
import { CircleCheck, Pencil, Sparkles, TriangleAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/**
 * Provenance is the core AI-UX contract of this product:
 * the user must always be able to see WHERE a value came from before it
 * becomes official business data.
 *
 *  ai_extracted  — read out of a document by AI, not yet checked
 *  ai_suggested  — AI's proposal for a match/normalisation
 *  needs_review  — AI is unsure; a human must decide
 *  user_approved — a person confirmed or typed it
 *  calculated    — derived by the system from other approved values
 */
export type Provenance =
  | "ai_extracted"
  | "ai_suggested"
  | "needs_review"
  | "user_approved"
  | "calculated";

const PROVENANCE = {
  ai_extracted: { label: "AI Extracted", icon: Sparkles, variant: "ai" },
  ai_suggested: { label: "AI Suggested", icon: Sparkles, variant: "ai" },
  needs_review: { label: "Needs Review", icon: TriangleAlert, variant: "warning" },
  user_approved: { label: "User Approved", icon: CircleCheck, variant: "success" },
  calculated: { label: "Calculated", icon: Pencil, variant: "neutral" },
} as const;

export function ProvenanceTag({
  provenance,
  className,
}: {
  provenance: Provenance;
  className?: string;
}) {
  const { label, icon: Icon, variant } = PROVENANCE[provenance];
  return (
    <Badge variant={variant} className={cn("gap-1 px-1.5", className)}>
      <Icon />
      {label}
    </Badge>
  );
}

/** Confidence as a labelled bar — never a bare percentage. */
export function ConfidenceMeter({
  value,
  showBar = true,
  className,
}: {
  value: number;
  showBar?: boolean;
  className?: string;
}) {
  const band = value >= 90 ? "High" : value >= 75 ? "Medium" : "Low";
  const tone =
    value >= 90
      ? { bar: "bg-success", text: "text-success-subtle-foreground" }
      : value >= 75
        ? { bar: "bg-warning", text: "text-warning-subtle-foreground" }
        : { bar: "bg-destructive", text: "text-destructive-subtle-foreground" };

  return (
    <div className={cn("flex items-center gap-2", className)}>
      {showBar && (
        <span className="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
          <span
            className={cn("block h-full rounded-full", tone.bar)}
            style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
          />
        </span>
      )}
      <span className={cn("text-[12px] font-medium tabular", tone.text)}>
        {value}% — {band} confidence
      </span>
    </div>
  );
}

/**
 * Wraps a form field so AI-derived values are visually distinct from
 * values a person entered. The violet rail is reserved for AI.
 */
export function AiField({
  label,
  provenance,
  hint,
  children,
  className,
}: {
  label: string;
  provenance?: Provenance;
  hint?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  const isAi = provenance === "ai_extracted" || provenance === "ai_suggested";
  const needsReview = provenance === "needs_review";

  return (
    <div
      className={cn(
        "rounded-md border-l-2 py-0.5 pl-3 transition-colors",
        isAi
          ? "border-l-ai bg-ai-subtle/35"
          : needsReview
            ? "border-l-warning bg-warning-subtle/40"
            : "border-l-transparent",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-2 pr-2">
        <span className="text-[12px] font-medium text-muted-foreground">{label}</span>
        {provenance && <ProvenanceTag provenance={provenance} />}
      </div>
      <div className="mt-1 pr-2">{children}</div>
      {hint && <p className="mt-1 pr-2 text-[11.5px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

/** Inline "AI thinks you meant…" affordance used on free-text product entry. */
export function AiSuggestion({
  suggestion,
  confidence,
  onAccept,
  onDismiss,
  className,
}: {
  suggestion: string;
  confidence?: number;
  onAccept?: () => void;
  onDismiss?: () => void;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-ai-border/60 bg-ai-subtle px-2 py-1.5 text-[12.5px]",
        className,
      )}
    >
      <Sparkles className="size-3.5 shrink-0 text-ai" />
      <span className="text-ai-subtle-foreground">AI suggests</span>
      <span className="font-medium text-foreground">{suggestion}</span>
      {confidence != null && (
        <span className="text-[11.5px] text-ai-subtle-foreground tabular">{confidence}%</span>
      )}
      <span className="ml-auto flex items-center gap-1">
        <button
          type="button"
          onClick={onAccept}
          className="rounded px-1.5 py-0.5 text-[12px] font-medium text-ai-subtle-foreground transition-colors hover:bg-ai/15"
        >
          Accept
        </button>
        <button
          type="button"
          onClick={onDismiss}
          className="rounded px-1.5 py-0.5 text-[12px] font-medium text-muted-foreground transition-colors hover:bg-foreground/6"
        >
          Keep mine
        </button>
      </span>
    </div>
  );
}
