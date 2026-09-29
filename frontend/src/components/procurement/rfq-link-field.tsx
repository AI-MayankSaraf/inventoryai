"use client";

import { Check } from "lucide-react";

import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useRfqs } from "@/hooks/use-procurement";
import type { Id } from "@/types";

/**
 * Links a document back to the RFQ it originated from. Resolves to the RFQ's
 * id — the number shown here is display only, never what the link is stored
 * as (C12).
 */
export function RfqLinkField({
  id = "linked-rfq",
  label = "Linked RFQ",
  value,
  onChange,
  helpText = "Optional — link the RFQ this responds to",
}: {
  id?: string;
  label?: string;
  value: Id | null;
  onChange: (value: Id | null) => void;
  helpText?: string;
}) {
  const rfqsState = useRfqs({ sort: "-rfqDate", limit: 200 });
  const rfqs = rfqsState.data?.items ?? [];
  const selected = rfqs.find((r) => r.id === value);

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Select
        value={value ?? "none"}
        onValueChange={(next) => onChange(next === "none" ? null : next)}
      >
        <SelectTrigger id={id}>
          <SelectValue placeholder="No RFQ linked" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="none">No RFQ linked</SelectItem>
          {rfqs.map((r) => (
            <SelectItem key={r.id} value={r.id}>
              {r.rfqNumber} · {r.subject}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {selected ? (
        <p className="flex items-center gap-1 text-[11.5px] text-success-subtle-foreground">
          <Check className="size-3" />
          {selected.subject}
        </p>
      ) : (
        helpText && <p className="text-[11.5px] text-muted-foreground">{helpText}</p>
      )}
    </div>
  );
}
