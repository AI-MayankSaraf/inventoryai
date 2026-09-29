import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const alertVariants = cva(
  "relative grid w-full items-start gap-x-3 rounded-lg border px-3.5 py-3 text-[13px] has-[>svg]:grid-cols-[1rem_1fr] grid-cols-[0_1fr] [&>svg]:size-4 [&>svg]:translate-y-0.5",
  {
    variants: {
      variant: {
        default: "bg-card text-foreground border-border",
        info: "bg-info-subtle text-info-subtle-foreground border-transparent [&>svg]:text-info",
        success:
          "bg-success-subtle text-success-subtle-foreground border-transparent [&>svg]:text-success",
        warning:
          "bg-warning-subtle text-warning-subtle-foreground border-transparent [&>svg]:text-warning-subtle-foreground",
        destructive:
          "bg-destructive-subtle text-destructive-subtle-foreground border-transparent [&>svg]:text-destructive",
        ai: "bg-ai-subtle text-ai-subtle-foreground border-ai-border/60 [&>svg]:text-ai",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

function Alert({
  className,
  variant,
  ...props
}: React.ComponentProps<"div"> & VariantProps<typeof alertVariants>) {
  return (
    <div
      data-slot="alert"
      role="alert"
      className={cn(alertVariants({ variant }), className)}
      {...props}
    />
  );
}

function AlertTitle({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-title"
      className={cn("col-start-2 min-h-4 font-medium tracking-tight", className)}
      {...props}
    />
  );
}

function AlertDescription({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-description"
      className={cn("col-start-2 grid justify-items-start gap-1 text-[13px] opacity-90", className)}
      {...props}
    />
  );
}

export { Alert, AlertTitle, AlertDescription };
