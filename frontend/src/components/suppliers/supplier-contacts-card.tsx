"use client";

import * as React from "react";
import { Mail, Pencil, Phone, Plus, Trash2 } from "lucide-react";

import { FormError } from "@/components/common/async-state";
import { ConfirmButton } from "@/components/common/confirm-dialog";
import { EmptyState } from "@/components/common/empty-state";
import { PermissionGate } from "@/components/common/permission-gate";
import { SectionCard } from "@/components/common/section-card";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { useDeleteContact, useSaveContact } from "@/hooks/use-suppliers";
import type { Id, SupplierContact } from "@/types";

/**
 * Contacts card on the supplier detail screen. People with `supplier.update`
 * can add, edit and remove contacts; everyone else sees the list only.
 * `onChanged` refreshes the detail query — real HTTP writes don't notify
 * screens on their own.
 */
export function SupplierContactsCard({
  supplierId,
  contacts,
  onChanged,
}: {
  supplierId: Id;
  contacts: SupplierContact[];
  onChanged: () => void;
}) {
  const remove = useDeleteContact(onChanged);

  return (
    <SectionCard
      title="Contacts"
      action={
        <PermissionGate permission="supplier.update">
          <ContactDialog
            supplierId={supplierId}
            isFirst={contacts.length === 0}
            onSaved={onChanged}
            trigger={
              <Button variant="ghost" size="sm" data-testid="add-contact">
                <Plus />
                Add
              </Button>
            }
          />
        </PermissionGate>
      }
    >
      {contacts.length === 0 ? (
        <EmptyState
          icon={Phone}
          title="No contacts yet"
          description="Add the people you deal with — sales, accounts, dispatch."
          className="py-8"
        />
      ) : (
        <ul className="divide-y divide-border">
          {contacts.map((contact) => (
            <li key={contact.id} className="group px-4 py-3" data-testid="supplier-contact">
              <div className="flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-2 text-[13.5px] font-medium text-foreground">
                    <span className="truncate">{contact.name}</span>
                    {contact.isPrimary && <StatusBadge status="active" label="Primary" />}
                  </p>
                  {contact.designation && (
                    <p className="text-caption text-muted-foreground">{contact.designation}</p>
                  )}
                </div>
                <PermissionGate permission="supplier.update">
                  <div className="flex shrink-0 items-center gap-0.5">
                    <ContactDialog
                      supplierId={supplierId}
                      contact={contact}
                      onSaved={onChanged}
                      trigger={
                        <Button variant="ghost" size="icon" className="size-7" aria-label={`Edit ${contact.name}`}>
                          <Pencil className="size-3.5" />
                        </Button>
                      }
                    />
                    <ConfirmButton
                      variant="ghost"
                      size="icon"
                      className="size-7"
                      tone="destructive"
                      aria-label={`Remove ${contact.name}`}
                      title={`Remove ${contact.name}?`}
                      description="The contact is removed from this supplier. RFQs already sent keep the email they went to."
                      confirmLabel="Remove"
                      onConfirm={() => remove.run(contact.id).then(() => undefined)}
                    >
                      <Trash2 className="size-3.5" />
                    </ConfirmButton>
                  </div>
                </PermissionGate>
              </div>
              {(contact.phone || contact.email) && (
                <div className="mt-2 space-y-1">
                  {contact.phone && (
                    <p className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
                      <Phone className="size-3.5" />
                      <span className="tabular">{contact.phone}</span>
                    </p>
                  )}
                  {contact.email && (
                    <p className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
                      <Mail className="size-3.5" />
                      <span className="truncate">{contact.email}</span>
                    </p>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {remove.error && <FormError message={remove.error} className="m-3" />}
    </SectionCard>
  );
}

function ContactDialog({
  supplierId,
  contact,
  isFirst = false,
  trigger,
  onSaved,
}: {
  supplierId: Id;
  contact?: SupplierContact;
  isFirst?: boolean;
  trigger: React.ReactNode;
  onSaved: () => void;
}) {
  const isEdit = !!contact;
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [designation, setDesignation] = React.useState("");
  const [phone, setPhone] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [isPrimary, setIsPrimary] = React.useState(false);

  const save = useSaveContact(supplierId, contact?.id, () => {
    setOpen(false);
    onSaved();
  });

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (next) {
      setName(contact?.name ?? "");
      setDesignation(contact?.designation ?? "");
      setPhone(contact?.phone ?? "");
      setEmail(contact?.email ?? "");
      setIsPrimary(contact?.isPrimary ?? isFirst);
      save.reset();
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit contact" : "Add a contact"}</DialogTitle>
          <DialogDescription>
            The primary contact is who RFQs and purchase orders are addressed to.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-3.5">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="ct-name">Name</Label>
              <Input id="ct-name" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ct-designation">Designation (optional)</Label>
              <Input
                id="ct-designation"
                value={designation}
                onChange={(e) => setDesignation(e.target.value)}
                placeholder="e.g. Sales Manager"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="ct-phone">Phone (optional)</Label>
              <Input id="ct-phone" value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ct-email">Email (optional)</Label>
              <Input id="ct-email" value={email} onChange={(e) => setEmail(e.target.value)} type="email" />
            </div>
          </div>
          <label className="flex items-center gap-2 text-[13.5px] text-foreground">
            <Checkbox
              id="ct-primary"
              checked={isPrimary}
              disabled={isFirst && !isEdit}
              onCheckedChange={(v) => setIsPrimary(v === true)}
            />
            Primary contact
            {isFirst && !isEdit && (
              <span className="text-caption text-muted-foreground">(the first contact always is)</span>
            )}
          </label>
        </DialogBody>
        <FormError message={save.error} fieldErrors={save.fieldErrors} />
        <DialogFooter>
          <Button
            onClick={() => save.run({ name, designation, phone, email, isPrimary })}
            disabled={!name.trim() || save.isPending}
          >
            {save.isPending ? "Saving..." : isEdit ? "Save Changes" : "Add Contact"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
