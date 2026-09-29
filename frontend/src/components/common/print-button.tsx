"use client";

import type * as React from "react";
import { Printer } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Prints the current document (RFQ, PO, Proforma, GRN...). The app chrome
 * (sidebar/header) is hidden for print via `print:hidden` in AppShell, so
 * this always prints just the record itself.
 */
export function PrintButton({
  label = "Print",
  className,
  variant = "outline",
}: {
  label?: string;
  className?: string;
  variant?: React.ComponentProps<typeof Button>["variant"];
}) {
  return (
    <Button
      type="button"
      variant={variant}
      className={cn("print:hidden", className)}
      onClick={() => window.print()}
    >
      <Printer />
      {label}
    </Button>
  );
}
