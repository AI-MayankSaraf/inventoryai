"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, Eye, EyeOff, Loader2 } from "lucide-react";

import { Logo } from "@/components/common/logo";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useApiMutation } from "@/hooks/use-api";
import { authApi } from "@/lib/api";

/**
 * Reached from the emailed invitation link (`/accept-invitation?token=…`).
 * The invitee picks a password, the backend creates the account, and we send
 * them to sign in.
 */
export function AcceptInvitationForm() {
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";

  const [fullName, setFullName] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [show, setShow] = React.useState(false);
  const [mismatch, setMismatch] = React.useState<string | null>(null);

  const accept = useApiMutation(
    (input: { password: string; fullName: string }) =>
      authApi.acceptInvitation(token, input.password, input.fullName),
    { onSuccess: () => router.push("/login?invited=1") },
  );

  if (!token) {
    return (
      <div className="w-full max-w-[400px] space-y-5">
        <Logo />
        <Alert variant="destructive">
          <AlertDescription>
            This link is missing its token. Ask your administrator to resend the invitation.
          </AlertDescription>
        </Alert>
        <Button variant="outline" asChild>
          <Link href="/login">Go to sign in</Link>
        </Button>
      </div>
    );
  }

  return (
    <form
      className="w-full max-w-[400px] space-y-5"
      onSubmit={(e) => {
        e.preventDefault();
        if (password !== confirm) {
          setMismatch("The two passwords don't match.");
          return;
        }
        setMismatch(null);
        void accept.run({ password, fullName });
      }}
    >
      <div className="space-y-1.5">
        <Logo />
        <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-foreground">
          Accept your invitation
        </h1>
        <p className="text-[13.5px] text-muted-foreground">
          Set a password to activate your account. At least 8 characters, with a letter and a number.
        </p>
      </div>

      {accept.error && (
        <Alert variant="destructive">
          <AlertDescription>{accept.error}</AlertDescription>
        </Alert>
      )}

      <div className="space-y-1.5">
        <Label htmlFor="ai-name">Full name (optional)</Label>
        <Input
          id="ai-name"
          autoComplete="name"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="ai-password">Password</Label>
        <div className="relative">
          <Input
            id="ai-password"
            type={show ? "text" : "password"}
            autoComplete="new-password"
            className="pr-10"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={!!accept.fieldErrors.password}
          />
          <button
            type="button"
            aria-label={show ? "Hide password" : "Show password"}
            className="absolute top-1/2 right-3 -translate-y-1/2 text-muted-foreground"
            onClick={() => setShow((v) => !v)}
          >
            {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          </button>
        </div>
        {accept.fieldErrors.password && (
          <p className="text-caption text-destructive">{accept.fieldErrors.password}</p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="ai-confirm">Confirm password</Label>
        <Input
          id="ai-confirm"
          type={show ? "text" : "password"}
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          aria-invalid={!!mismatch}
        />
        {mismatch && <p className="text-caption text-destructive">{mismatch}</p>}
      </div>

      <Button type="submit" className="w-full" disabled={accept.isPending || !password}>
        {accept.isPending && <Loader2 className="animate-spin" />}
        {accept.isPending ? "Activating..." : "Activate account"}
      </Button>

      <Button variant="ghost" asChild className="-ml-2">
        <Link href="/login">
          <ArrowLeft />
          Back to sign in
        </Link>
      </Button>
    </form>
  );
}
