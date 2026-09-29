"use client";

import * as React from "react";
import { KeyRound, Mail, Plus, RotateCw, UserX } from "lucide-react";

import { FormError } from "@/components/common/async-state";
import { ConfirmButton } from "@/components/common/confirm-dialog";
import { PermissionGate } from "@/components/common/permission-gate";
import { SectionCard } from "@/components/common/section-card";
import { Badge } from "@/components/ui/badge";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import {
  grantPortalAccess,
  listPortalAccess,
  resendPortalLink,
  revokePortalAccess,
} from "@/lib/api/supplier-portal.api";
import { formatRelativeTime } from "@/lib/format";
import type { Id, SupplierContact } from "@/types";
import type { SupplierPortalAccess } from "@/types/supplier-portal";

/**
 * Who at this supplier can sign in to the Supplier Portal, where they see
 * the RFQs you send them, their quotations and your POs to them.
 *
 * Giving access emails a one-time link to set a password. The same person
 * keeps one login across every company that gives them access. "Re-send
 * link" is also how they get back in after forgetting their password.
 */
export function SupplierPortalAccessCard({ supplierId, contacts }: { supplierId: Id; contacts: SupplierContact[] }) {
  const list = useApiQuery(["portal-access", supplierId], () => listPortalAccess(supplierId));
  const [open, setOpen] = React.useState(false);
  const [notice, setNotice] = React.useState<string | null>(null);

  const revoke = useApiMutation((accessId: Id) => revokePortalAccess(supplierId, accessId), {
    onSuccess: () => {
      setNotice("Access revoked. They can no longer see anything from your company.");
      list.refresh();
    },
  });
  const resend = useApiMutation((row: SupplierPortalAccess) => resendPortalLink(supplierId, row.id), {
    onSuccess: () => setNotice("A new link is on its way to them."),
  });

  const rows = (list.data ?? []).slice().sort((a, b) => (a.status === b.status ? 0 : a.status === "active" ? -1 : 1));

  return (
    <div data-testid="portal-access-card">
      <SectionCard
        title="Supplier Portal access"
        description="People here can sign in to see your RFQs, their quotes and your POs to them"
        action={
          <PermissionGate permission="supplier.update">
            <Button size="sm" variant="outline" onClick={() => setOpen(true)} data-testid="portal-grant">
              <Plus />
              Give access
            </Button>
          </PermissionGate>
        }
      >
        <div className="space-y-3 p-4">
          {notice && (
            <p className="rounded-md bg-success-subtle px-3 py-2 text-[12.5px] text-success-subtle-foreground" role="status">
              {notice}
            </p>
          )}
          <FormError message={list.error ?? revoke.error ?? resend.error} />
          {list.isLoading && !list.data ? (
            <p className="text-caption text-muted-foreground">Loading…</p>
          ) : rows.length === 0 ? (
            <p className="text-caption text-muted-foreground">
              Nobody from this supplier can sign in yet. Give access to a contact and they&apos;ll get an email to set a
              password.
            </p>
          ) : (
            <ul className="divide-y divide-border rounded-md border border-border">
              {rows.map((row) => (
                <li key={row.id} className="space-y-2 px-3 py-2.5" data-testid="portal-access-row">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-[13.5px] font-medium text-foreground">{row.fullName}</p>
                      <p className="flex items-center gap-1 truncate text-caption text-muted-foreground">
                        <Mail className="size-3" />
                        {row.email}
                      </p>
                    </div>
                    <AccessBadge row={row} />
                  </div>
                  {row.status === "active" && (
                    <PermissionGate permission="supplier.update">
                      <div className="flex flex-wrap gap-1.5">
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={resend.isPending}
                          onClick={() => {
                            setNotice(null);
                            void resend.run(row);
                          }}
                        >
                          <RotateCw />
                          {row.accountStatus === "invited" ? "Re-send invitation" : "Send password link"}
                        </Button>
                        <ConfirmButton
                          title={`Revoke ${row.fullName}'s access?`}
                          description="They will immediately stop seeing your company in the Supplier Portal. Their login keeps working for other companies that gave them access."
                          confirmLabel="Revoke access"
                          tone="destructive"
                          variant="ghost"
                          size="sm"
                          onConfirm={() => {
                            setNotice(null);
                            void revoke.run(row.id);
                          }}
                        >
                          <UserX />
                          Revoke
                        </ConfirmButton>
                      </div>
                    </PermissionGate>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </SectionCard>

      <GrantDialog
        open={open}
        onOpenChange={setOpen}
        supplierId={supplierId}
        contacts={contacts}
        onGranted={(row) => {
          setNotice(
            row.accountStatus === "invited"
              ? `Invitation sent to ${row.email}. They'll set a password from the email.`
              : `${row.fullName} already has a portal login and can now see your company too.`,
          );
          list.refresh();
        }}
      />
    </div>
  );
}

function AccessBadge({ row }: { row: SupplierPortalAccess }) {
  if (row.status === "revoked") return <Badge variant="neutral">Revoked</Badge>;
  if (row.accountStatus === "invited") return <Badge variant="warning">Waiting for password</Badge>;
  if (row.accountStatus === "disabled") return <Badge variant="destructive">Disabled</Badge>;
  return (
    <Badge variant="success" title={row.lastLoginAt ? undefined : "Hasn't signed in yet"}>
      <KeyRound />
      {row.lastLoginAt ? `Active · ${formatRelativeTime(row.lastLoginAt)}` : "Active"}
    </Badge>
  );
}

function GrantDialog({
  open,
  onOpenChange,
  supplierId,
  contacts,
  onGranted,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  supplierId: Id;
  contacts: SupplierContact[];
  onGranted: (row: SupplierPortalAccess) => void;
}) {
  const [email, setEmail] = React.useState("");
  const [name, setName] = React.useState("");
  const grant = useApiMutation(
    (input: { email: string; fullName: string }) => grantPortalAccess(supplierId, input),
    {
      onSuccess: (row) => {
        onGranted(row);
        onOpenChange(false);
      },
    },
  );
  const withEmail = contacts.filter((c) => c.email);

  React.useEffect(() => {
    if (!open) {
      setEmail("");
      setName("");
      grant.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Give Supplier Portal access</DialogTitle>
          <DialogDescription>
            They get an email with a link to set a password. They&apos;ll see only what concerns this supplier: RFQs
            you send them, their quotations and POs you&apos;ve sent.
          </DialogDescription>
        </DialogHeader>
        <form
          id="portal-grant-form"
          onSubmit={(e) => {
            e.preventDefault();
            void grant.run({ email, fullName: name });
          }}
        >
          <DialogBody className="space-y-3.5">
            {withEmail.length > 0 && (
              <div className="space-y-1.5">
                <p className="text-caption text-muted-foreground">Pick a contact</p>
                <div className="flex flex-wrap gap-1.5">
                  {withEmail.map((c) => (
                    <Button
                      key={c.id}
                      type="button"
                      size="sm"
                      variant={email === c.email ? "default" : "outline"}
                      onClick={() => {
                        setEmail(c.email ?? "");
                        setName(c.name);
                      }}
                    >
                      {c.name}
                    </Button>
                  ))}
                </div>
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="portal-name">Name</Label>
              <Input id="portal-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Ravi Kumar" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="portal-email">Email</Label>
              <Input
                id="portal-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@supplier.com"
                required
              />
            </div>
            <FormError message={grant.error} />
          </DialogBody>
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={grant.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="portal-grant-form" disabled={grant.isPending || !email.trim()}>
            {grant.isPending ? "Sending…" : "Send invitation"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
