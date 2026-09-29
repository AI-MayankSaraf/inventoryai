import * as React from "react";
import type { LucideIcon } from "lucide-react";

import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type Tone = "default" | "success" | "warning" | "destructive" | "info";

const TONE: Record<Tone, { icon: string; value: string }> = {
  default: { icon: "bg-primary-subtle text-primary-subtle-foreground", value: "text-foreground" },
  success: { icon: "bg-success-subtle text-success-subtle-foreground", value: "text-foreground" },
  warning: { icon: "bg-warning-subtle text-warning-subtle-foreground", value: "text-warning-subtle-foreground" },
  destructive: { icon: "bg-destructive-subtle text-destructive-subtle-foreground", value: "text-destructive-subtle-foreground" },
  info: { icon: "bg-info-subtle text-info-subtle-foreground", value: "text-foreground" },
};

export function KpiCard({
  label,
  value,
  hint,
  icon: Icon,
  tone = "default",
  href,
  className,
}: {
  label: string;
  value: string;
  hint?: React.ReactNode;
  icon: LucideIcon;
  tone?: Tone;
  href?: string;
  className?: string;
}) {
  const tones = TONE[tone];

  const body = (
    <>
      <div className="flex items-start justify-between gap-3">
        <p className="text-label text-muted-foreground">{label}</p>
        <span
          className={cn(
            "flex size-8 shrink-0 items-center justify-center rounded-lg",
            tones.icon,
          )}
        >
          <Icon className="size-4" strokeWidth={2} />
        </span>
      </div>
      <p className={cn("mt-2.5 text-[26px] leading-none font-semibold tracking-[-0.02em] tabular", tones.value)}>
        {value}
      </p>
      {hint && <p className="mt-2 text-caption text-muted-foreground">{hint}</p>}
    </>
  );

  return (
    <Card
      className={cn(
        "p-4 transition-shadow",
        href && "hover:shadow-elevated",
        className,
      )}
    >
      {href ? (
        <a href={href} className="outline-none focus-visible:ring-[3px] focus-visible:ring-ring/25">
          {body}
        </a>
      ) : (
        body
      )}
    </Card>
  );
}
