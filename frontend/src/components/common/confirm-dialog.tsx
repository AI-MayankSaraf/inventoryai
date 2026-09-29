"use client";

import * as React from "react";
import { Loader2, TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

type Tone = "default" | "destructive" | "success" | "warning";

const toneIconClass: Record<Tone, string> = {
  default: "bg-primary-subtle text-primary-subtle-foreground",
  destructive: "bg-destructive-subtle text-destructive-subtle-foreground",
  success: "bg-success-subtle text-success-subtle-foreground",
  warning: "bg-warning-subtle text-warning-subtle-foreground",
};

const toneButtonVariant: Record<Tone, React.ComponentProps<typeof Button>["variant"]> = {
  default: "default",
  destructive: "destructive",
  success: "success",
  warning: "default",
};

/**
 * Generic "are you sure?" dialog. Wrap any action button with this instead of
 * firing the action directly — nothing happens until the user confirms in the
 * dialog, and closing/cancelling performs no action at all.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  tone = "default",
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: Tone;
  onConfirm: () => void | Promise<void>;
}) {
  const [busy, setBusy] = React.useState(false);

  async function handleConfirm() {
    try {
      setBusy(true);
      await onConfirm();
      onOpenChange(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent>
        <DialogHeader>
          <div className="flex items-start gap-3">
            <span
              className={cn(
                "flex size-9 shrink-0 items-center justify-center rounded-full",
                toneIconClass[tone],
              )}
            >
              <TriangleAlert className="size-[18px]" />
            </span>
            <div className="space-y-1 pt-0.5">
              <DialogTitle>{title}</DialogTitle>
              {description && <DialogDescription>{description}</DialogDescription>}
            </div>
          </div>
        </DialogHeader>
        <DialogFooter>
          <Button type="button" variant="outline" disabled={busy} onClick={() => onOpenChange(false)}>
            {cancelLabel}
          </Button>
          <Button type="button" variant={toneButtonVariant[tone]} disabled={busy} onClick={handleConfirm}>
            {busy && <Loader2 className="animate-spin" />}
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Drop-in replacement for a plain action `<Button>` that always confirms
 * before running `onConfirm`. Renders the trigger button itself, so callers
 * don't need to manage dialog open state.
 *
 * <ConfirmButton title="Reject this RFQ?" tone="destructive" onConfirm={reject}>
 *   <X /> Reject
 * </ConfirmButton>
 */
export function ConfirmButton({
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  tone = "default",
  onConfirm,
  children,
  variant = "outline",
  size,
  className,
  disabled,
  "aria-label": ariaLabel,
}: {
  title: string;
  description?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: Tone;
  onConfirm: () => void | Promise<void>;
  children: React.ReactNode;
  variant?: React.ComponentProps<typeof Button>["variant"];
  size?: React.ComponentProps<typeof Button>["size"];
  className?: string;
  disabled?: boolean;
  /** Needed whenever the trigger is icon-only, so it still has an accessible name. */
  "aria-label"?: string;
}) {
  const [open, setOpen] = React.useState(false);

  return (
    <>
      <Button
        type="button"
        variant={variant}
        size={size}
        className={className}
        disabled={disabled}
        aria-label={ariaLabel}
        onClick={() => setOpen(true)}
      >
        {children}
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={title}
        description={description}
        confirmLabel={confirmLabel}
        cancelLabel={cancelLabel}
        tone={tone}
        onConfirm={onConfirm}
      />
    </>
  );
}
