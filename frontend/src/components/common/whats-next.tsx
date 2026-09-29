import Link from "next/link";
import { ArrowRight, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export interface NextStep {
  label: string;
  description: string;
  href: string;
  icon: LucideIcon;
  primary?: boolean;
}

/**
 * "What happens next?" panel shown after every major workflow action, so the
 * user is never left wondering what the system expects of them.
 */
export function WhatsNext({
  title = "What happens next?",
  steps,
  className,
}: {
  title?: string;
  steps: NextStep[];
  className?: string;
}) {
  return (
    <div className={cn("rounded-xl border border-border bg-card p-4", className)}>
      <p className="text-section text-foreground">{title}</p>
      <ul className="mt-3 grid gap-2 sm:grid-cols-3">
        {steps.map((step) => {
          const Icon = step.icon;
          return (
            <li key={step.label}>
              <Link
                href={step.href}
                className={cn(
                  "flex h-full items-start gap-3 rounded-lg border p-3 transition-colors",
                  step.primary
                    ? "border-primary/35 bg-primary-subtle/55 hover:bg-primary-subtle"
                    : "border-border hover:bg-muted/60",
                )}
              >
                <span
                  className={cn(
                    "flex size-8 shrink-0 items-center justify-center rounded-lg",
                    step.primary
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-muted-foreground",
                  )}
                >
                  <Icon className="size-4" strokeWidth={2} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1 text-[13.5px] font-medium text-foreground">
                    {step.label}
                    <ArrowRight className="size-3.5 text-muted-foreground" />
                  </span>
                  <span className="mt-0.5 block text-caption text-muted-foreground">
                    {step.description}
                  </span>
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
