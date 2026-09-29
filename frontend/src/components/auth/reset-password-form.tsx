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
 * The second half of the reset flow, reached from the emailed link.
 *
 * Setting a new password ends every other session server-side, so this
 * finishes by sending the person to sign in again rather than pretending
 * the old token still works.
 */
export function ResetPasswordForm() {
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";

  const [password, setPassword] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [show, setShow] = React.useState(false);
  const [mismatch, setMismatch] = React.useState<string | null>(null);

  const reset = useApiMutation((value: string) => authApi.resetPassword(token, value), {
    onSuccess: () => router.push("/login?reset=1"),
  });

  if (!token) {
    return (
      <div className="w-full max-w-[400px] space-y-5">
        <Logo />
        <Alert variant="destructive">
          <AlertDescription>
            This link is missing its token. Request a new one from the sign-in screen.
          </AlertDescription>
        </Alert>
        <Button variant="outline" asChild>
          <Link href="/forgot-password">Request a new link</Link>
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
        void reset.run(password);
      }}
    >
      <div className="space-y-1.5">
        <Logo />
        <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-foreground">
          Choose a new password
        </h1>
        <p className="text-[13.5px] text-muted-foreground">
          At least 8 characters, with a letter and a number. Everyone signed in as you will be
          signed out.
        </p>
      </div>

      {reset.error && (
        <Alert variant="destructive">
          <AlertDescription>
            {reset.error}
            {reset.error.toLowerCase().includes("no longer valid") && (
              <>
                {" "}
                <Link href="/forgot-password" className="font-medium underline">
                  Request a new link
                </Link>
              </>
            )}
          </AlertDescription>
        </Alert>
      )}

      <div className="space-y-1.5">
        <Label htmlFor="rp-password">New password</Label>
        <div className="relative">
          <Input
            id="rp-password"
            type={show ? "text" : "password"}
            autoComplete="new-password"
            className="pr-10"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={!!reset.fieldErrors.newPassword}
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
        {reset.fieldErrors.newPassword && (
          <p className="text-caption text-destructive">{reset.fieldErrors.newPassword}</p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="rp-confirm">Confirm new password</Label>
        <Input
          id="rp-confirm"
          type={show ? "text" : "password"}
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          aria-invalid={!!mismatch}
        />
        {mismatch && <p className="text-caption text-destructive">{mismatch}</p>}
      </div>

      <Button type="submit" className="w-full" disabled={reset.isPending || !password}>
        {reset.isPending && <Loader2 className="animate-spin" />}
        {reset.isPending ? "Saving..." : "Set new password"}
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
