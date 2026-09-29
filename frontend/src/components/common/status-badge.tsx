import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { statusLabel, statusTone, type StatusTone } from "@/lib/domain/state-machines";
import { cn } from "@/lib/utils";

/**
 * One badge for every status in the app.
 *
 * Labels and colours come from `lib/domain/state-machines.ts`, which is also
 * what decides which transitions are legal — so a status can never be shown
 * with a label the workflow does not recognise. Screens pass the raw status
 * string from the API; they no longer pick a variant themselves.
 */

type Variant = React.ComponentProps<typeof Badge>["variant"];

const TONE_VARIANT: Record<StatusTone, Variant> = {
  neutral: "neutral",
  info: "info",
  success: "success",
  warning: "warning",
  danger: "destructive",
};

export function StatusBadge({
  status,
  label,
  className,
  ...props
}: {
  status: string;
  label?: string;
} & Omit<React.ComponentProps<typeof Badge>, "variant">) {
  return (
    <Badge variant={TONE_VARIANT[statusTone(status)]} className={cn(className)} {...props}>
      {label ?? statusLabel(status)}
    </Badge>
  );
}

/* --------------------------------------------------------- AI provenance */

const PROVENANCE_META: Record<string, { label: string; variant: Variant }> = {
  ai_extracted: { label: "AI extracted", variant: "ai" },
  ai_suggested: { label: "AI suggested", variant: "ai" },
  needs_review: { label: "Needs review", variant: "warning" },
  user_approved: { label: "You approved", variant: "success" },
  calculated: { label: "Calculated", variant: "neutral" },
};

/**
 * Where a value came from. `calculated` means the app's own money engine
 * produced it — never the number printed on the supplier's document.
 */
export function ProvenanceBadge({
  provenance,
  confidence,
  className,
}: {
  provenance: string;
  confidence?: number | null;
  className?: string;
}) {
  const meta = PROVENANCE_META[provenance] ?? { label: provenance, variant: "neutral" as Variant };
  return (
    <Badge variant={meta.variant} className={cn(className)}>
      {meta.label}
      {typeof confidence === "number" ? ` · ${Math.round(confidence)}%` : ""}
    </Badge>
  );
}

export function SeverityBadge({ severity, className }: { severity: string; className?: string }) {
  const variant: Variant =
    severity === "critical" ? "destructive" : severity === "high" ? "warning" : severity === "medium" ? "info" : "neutral";
  return (
    <Badge variant={variant} className={cn(className)}>
      {severity.replace(/^\w/, (c) => c.toUpperCase())}
    </Badge>
  );
}
