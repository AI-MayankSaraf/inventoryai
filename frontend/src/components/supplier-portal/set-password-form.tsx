"use client";

import * as React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { CheckCircle2, Eye, EyeOff, Loader2 } from "lucide-react";

import { Logo } from "@/components/common/logo";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useApiMutation } from "@/hooks/use-api";
import { setPassword } from "@/lib/api/supplier-portal.api";

/**
 * Where the Supplier Portal invitation email lands. The same link, sent
 * again by the company, is also how a supplier who forgot their password
 * gets back in — there is no self-service reset, because the company is
 * the one vouching for who may act as its supplier.
 */
export function SupplierSetPasswordForm() {
  const token = useSearchParams().get("token") ?? "";
  const [password, setPasswordValue] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [show, setShow] = React.useState(false);
  const [mismatch, setMismatch] = React.useState<string | null>(null);
  const [saved, setSaved] = React.useState(false);
  const save = useApiMutation((value: string) => setPassword(token, value), { onSuccess: () => setSaved(true) });

  if (!token) {
    return (
      <div className="w-full max-w-[400px] space-y-5">
        <Logo />
        <Alert variant="destructive">
          <AlertDescription>
            This link is missing its token. Ask the company you supply to send you a new portal link.
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  if (saved) {
    return (
      <div className="w-full max-w-[400px] space-y-5" data-testid="portal-password-set">
        <Logo />
        <div className="flex gap-3 rounded-lg bg-success-subtle px-4 py-3 text-success-subtle-foreground">
          <CheckCircle2 className="mt-0.5 size-5 shrink-0" />
          <div>
            <p className="text-[14px] font-semibold">Your password is set</p>
            <p className="text-[13px]">Sign in with your email and the password you just chose.</p>
          </div>
        </div>
        <Button asChild className="w-full">
          <Link href="/supplier-portal/login">Go to Supplier Portal sign-in</Link>
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
        void save.run(password);
      }}
    >
      <div className="space-y-1.5">
        <Logo />
        <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-foreground">Set your portal password</h1>
        <p className="text-[13.5px] text-muted-foreground">
          At least 8 characters, with a letter and a number. You&apos;ll use it with your email to sign in to the
          Supplier Portal.
        </p>
      </div>

      {save.error && (
        <Alert variant="destructive">
          <AlertDescription>{save.error}</AlertDescription>
        </Alert>
      )}

      <div className="space-y-1.5">
        <Label htmlFor="sp-password">Password</Label>
        <div className="relative">
          <Input
            id="sp-password"
            type={show ? "text" : "password"}
            autoComplete="new-password"
            className="pr-10"
            value={password}
            onChange={(e) => setPasswordValue(e.target.value)}
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
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="sp-confirm">Confirm password</Label>
        <Input
          id="sp-confirm"
          type={show ? "text" : "password"}
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          aria-invalid={!!mismatch}
        />
        {mismatch && <p className="text-caption text-destructive">{mismatch}</p>}
      </div>

      <Button type="submit" className="w-full" disabled={save.isPending || !password}>
        {save.isPending && <Loader2 className="animate-spin" />}
        {save.isPending ? "Saving..." : "Set password"}
      </Button>
    </form>
  );
}
