"use client";

import * as React from "react";
import { Loader2, Trash2 } from "lucide-react";

import { FormError } from "@/components/common/async-state";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useSetQuotationStatus } from "@/hooks/use-procurement";
import type { Id } from "@/types";

/**
 * There is no "delete" for a supplier quotation once it exists — the only
 * document-safe way to take it out of consideration is to reject it, and the
 * API requires a reason so the supplier can be told why (BR-QT-04). This is
 * the button previously labelled "Delete"; it now runs that transition.
 */
export function DeleteQuotationButton({
  quotationId,
  quotationNumber,
  supplierName,
  variant = "outline",
  onDone,
}: {
  quotationId: Id;
  quotationNumber: string;
  supplierName?: string;
  variant?: React.ComponentProps<typeof Button>["variant"];
  onDone?: () => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [reason, setReason] = React.useState("");
  const reject = useSetQuotationStatus(() => {
    setOpen(false);
    setReason("");
    onDone?.();
  });

  return (
    <>
      <Button
        type="button"
        variant={variant}
        className="text-destructive hover:text-destructive"
        onClick={() => setOpen(true)}
      >
        <Trash2 />
        Reject
      </Button>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!reject.isPending) setOpen(next);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject this quotation?</DialogTitle>
            <DialogDescription>
              {quotationNumber}
              {supplierName ? ` from ${supplierName}` : ""} will be marked rejected and removed
              from consideration. Give a reason so the supplier can be told why. This can&apos;t be
              undone.
            </DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-2">
            <Label htmlFor="reject-reason">Reason</Label>
            <Textarea
              id="reject-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              placeholder="e.g. Price too high, item discontinued..."
            />
            <FormError message={reject.error} fieldErrors={reject.fieldErrors} />
          </DialogBody>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={reject.isPending}
              onClick={() => setOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={reject.isPending || !reason.trim()}
              onClick={() => reject.run({ quotationId, status: "rejected", reason })}
            >
              {reject.isPending && <Loader2 className="animate-spin" />}
              Reject
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
