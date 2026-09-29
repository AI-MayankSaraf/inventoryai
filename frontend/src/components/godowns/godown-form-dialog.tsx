"use client";

import * as React from "react";
import { Pencil, Plus } from "lucide-react";

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
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { INDIAN_STATES } from "@/lib/gst-states";
import { useCreateGodown, useUpdateGodown, useUsers } from "@/hooks/use-admin";
import { useUoms } from "@/hooks/use-catalog";
import type { Godown } from "@/types";

/**
 * GST state codes. The state a godown sits in decides whether a document
 * delivered there charges CGST + SGST (same state as the supplier/company) or
 * IGST (different state) — never a checkbox on the document itself.
 */

export function GodownFormDialog({
  godown,
  trigger,
  onSaved,
}: {
  godown?: Godown;
  trigger?: React.ReactNode;
  /** The parent list/screen has no other way to learn a create or edit
   * happened — without this its own query stays stale until the user
   * navigates away and back. */
  onSaved?: () => void;
}) {
  const isEdit = !!godown;
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState(godown?.name ?? "");
  const [code, setCode] = React.useState(godown?.code ?? "");
  const [city, setCity] = React.useState(godown?.city ?? "");
  const [stateCode, setStateCode] = React.useState(godown?.stateCode ?? "");
  const [address, setAddress] = React.useState(godown?.address ?? "");
  const [inchargeUserId, setInchargeUserId] = React.useState(godown?.inchargeUserId ?? "");
  const [capacity, setCapacity] = React.useState(godown?.capacityValue ? String(godown.capacityValue) : "");
  const [capacityUomId, setCapacityUomId] = React.useState(godown?.capacityUomId ?? "");
  const uoms = useUoms().data ?? [];

  const usersState = useUsers({ limit: 1000 });
  const users = usersState.data?.items ?? [];

  const create = useCreateGodown(() => {
    setOpen(false);
    reset();
    onSaved?.();
  });
  const update = useUpdateGodown(() => {
    setOpen(false);
    reset();
    onSaved?.();
  });
  const mutation = isEdit ? update : create;

  function reset() {
    setName(godown?.name ?? "");
    setCode(godown?.code ?? "");
    setCity(godown?.city ?? "");
    setStateCode(godown?.stateCode ?? "");
    setAddress(godown?.address ?? "");
    setInchargeUserId(godown?.inchargeUserId ?? "");
    setCapacity(godown?.capacityValue ? String(godown.capacityValue) : "");
    setCapacityUomId(godown?.capacityUomId ?? "");
    create.reset();
    update.reset();
  }

  function handleOpenChange(next: boolean) {
    setOpen(next);
    reset();
  }

  async function save() {
    const input = {
      name: name.trim(),
      code: code.trim(),
      city: city.trim(),
      stateCode,
      address: address.trim(),
      gstin: godown?.gstin ?? null,
      inchargeUserId: inchargeUserId || null,
      capacityValue: capacity.trim() ? Number(capacity) : undefined,
      capacityUomId: capacity.trim() ? capacityUomId || null : null,
      isDefault: godown?.isDefault ?? false,
    };
    if (isEdit) await update.run({ godownId: godown!.id, data: input });
    else await create.run(input);
  }

  const capacityInvalid =
    !!capacity.trim() && (!(Number(capacity) > 0) || !capacityUomId);
  const canSubmit = !!name.trim() && !!city.trim() && !!stateCode && !capacityInvalid && !mutation.isPending;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button>
            {isEdit ? <Pencil /> : <Plus />}
            {isEdit ? "Edit Godown" : "Add Godown"}
          </Button>
        )}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit godown" : "Add a godown"}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Update this storage location's details."
              : "A godown is a storage location that stock can be received into and issued from."}
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-3.5">
          <div className="space-y-1.5">
            <Label htmlFor="gd-name">Godown Name</Label>
            <Input
              id="gd-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Main Godown"
              autoFocus
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="gd-city">City</Label>
              <Input
                id="gd-city"
                value={city}
                onChange={(e) => setCity(e.target.value)}
                placeholder="e.g. Indore"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="gd-state">State</Label>
              <Select value={stateCode} onValueChange={setStateCode}>
                <SelectTrigger id="gd-state">
                  <SelectValue placeholder="Select state..." />
                </SelectTrigger>
                <SelectContent>
                  {INDIAN_STATES.map((s) => (
                    <SelectItem key={s.code} value={s.code}>
                      {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <p className="text-caption text-muted-foreground">
            The state decides whether documents delivered here charge CGST + SGST or IGST.
          </p>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="gd-code">Godown Code (optional)</Label>
              <Input id="gd-code" value={code} onChange={(e) => setCode(e.target.value)} placeholder="e.g. MAIN" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="gd-incharge">In-charge (optional)</Label>
              <Select
                value={inchargeUserId || "none"}
                onValueChange={(v) => setInchargeUserId(v === "none" ? "" : v)}
              >
                <SelectTrigger id="gd-incharge">
                  <SelectValue placeholder="Unassigned" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Unassigned</SelectItem>
                  {users.map((u) => (
                    <SelectItem key={u.id} value={u.id}>
                      {u.fullName}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="gd-capacity">Capacity (optional)</Label>
            <div className="grid grid-cols-[1fr_140px] gap-2">
              <Input
                id="gd-capacity"
                type="number"
                min={0}
                inputMode="decimal"
                value={capacity}
                onChange={(e) => setCapacity(e.target.value)}
                placeholder="e.g. 5000"
                aria-invalid={capacityInvalid}
              />
              <Select value={capacityUomId || "none"} onValueChange={(v) => setCapacityUomId(v === "none" ? "" : v)}>
                <SelectTrigger id="gd-capacity-unit" aria-label="Capacity unit">
                  <SelectValue placeholder="Unit" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Unit…</SelectItem>
                  {uoms.map((u) => (
                    <SelectItem key={u.id} value={u.id}>
                      {u.name} ({u.code})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {capacityInvalid && (
              <p className="text-caption text-destructive">Enter a capacity above zero and choose its unit.</p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="gd-address">Address (optional)</Label>
            <Input
              id="gd-address"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="Street, area"
            />
          </div>

          <p className="text-caption text-muted-foreground">
            SKUs stored and stock value are calculated from inventory transactions — a new godown
            starts empty.
          </p>
        </DialogBody>

        <FormError message={mutation.error} fieldErrors={mutation.fieldErrors} />

        <DialogFooter>
          <Button onClick={save} disabled={!canSubmit}>
            {mutation.isPending ? "Saving..." : isEdit ? "Save Changes" : "Add Godown"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
