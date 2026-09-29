"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { KeyRound } from "lucide-react";

import { FormError } from "@/components/common/async-state";
import { SectionCard } from "@/components/common/section-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useChangePassword } from "@/hooks/use-admin";

/**
 * Change your own password.
 *
 * The server ends every session on success — including this one — so the
 * only honest thing to do afterwards is send the person back to sign in.
 */
export function ChangePasswordCard() {
  const router = useRouter();
  const [current, setCurrent] = React.useState("");
  const [next, setNext] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [mismatch, setMismatch] = React.useState<string | null>(null);

  const change = useChangePassword(() => router.push("/login?reset=1"));

  return (
    <div data-testid="change-password">
    <SectionCard
      title="Your Password"
      description="Changing it signs you out everywhere, including here"
    >
      <div className="space-y-3.5 p-4">
        <div className="space-y-1.5">
          <Label htmlFor="cp-current">Current password</Label>
          <Input
            id="cp-current"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="cp-new">New password</Label>
            <Input
              id="cp-new"
              type="password"
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              aria-invalid={!!change.fieldErrors.newPassword}
            />
            {change.fieldErrors.newPassword && (
              <p className="text-caption text-destructive">{change.fieldErrors.newPassword}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cp-confirm">Confirm</Label>
            <Input
              id="cp-confirm"
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              aria-invalid={!!mismatch}
            />
            {mismatch && <p className="text-caption text-destructive">{mismatch}</p>}
          </div>
        </div>
        <p className="text-caption text-muted-foreground">
          At least 8 characters, with a letter and a number.
        </p>

        <FormError message={change.error} fieldErrors={change.fieldErrors} />

        <div className="flex justify-end">
          <Button
            disabled={!current || !next || change.isPending}
            onClick={() => {
              if (next !== confirm) {
                setMismatch("The two passwords don't match.");
                return;
              }
              setMismatch(null);
              void change.run({ currentPassword: current, newPassword: next });
            }}
          >
            <KeyRound />
            {change.isPending ? "Saving..." : "Change password"}
          </Button>
        </div>
      </div>
    </SectionCard>
    </div>
  );
}
