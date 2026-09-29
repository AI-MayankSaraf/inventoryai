"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, Loader2, MailCheck } from "lucide-react";

import { Logo } from "@/components/common/logo";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useApiMutation } from "@/hooks/use-api";
import { authApi } from "@/lib/api";

/**
 * "Forgot password?" — the first half of BR-AUTH-02's reset flow.
 *
 * The confirmation is deliberately the same whether or not that address has
 * an account: the backend answers 202 either way, and a screen that said
 * "no account with that email" would turn this into a way to find out who
 * banks here.
 */
export function ForgotPasswordForm() {
  const [email, setEmail] = React.useState("");
  const [sent, setSent] = React.useState(false);

  const request = useApiMutation((value: string) => authApi.requestPasswordReset(value), {
    onSuccess: () => setSent(true),
  });

  if (sent) {
    return (
      <div className="w-full max-w-[400px] space-y-5">
        <Logo />
        <Alert variant="success">
          <MailCheck />
          <AlertDescription>
            If {email.trim()} belongs to an account, a reset link is on its way. It works once and
            expires in an hour.
          </AlertDescription>
        </Alert>
        <p className="text-[13px] text-muted-foreground">
          Nothing arrived? Check the spam folder, or{" "}
          <button
            type="button"
            className="font-medium text-primary hover:underline"
            onClick={() => setSent(false)}
          >
            try a different address
          </button>
          .
        </p>
        <Button variant="ghost" asChild className="-ml-2">
          <Link href="/login">
            <ArrowLeft />
            Back to sign in
          </Link>
        </Button>
      </div>
    );
  }

  return (
    <form
      noValidate
      className="w-full max-w-[400px] space-y-5"
      onSubmit={(e) => {
        e.preventDefault();
        void request.run(email);
      }}
    >
      <div className="space-y-1.5">
        <Logo />
        <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-foreground">
          Reset your password
        </h1>
        <p className="text-[13.5px] text-muted-foreground">
          Enter the email you sign in with and we&apos;ll send you a link.
        </p>
      </div>

      {request.error && (
        <Alert variant="destructive">
          <AlertDescription>{request.error}</AlertDescription>
        </Alert>
      )}

      <div className="space-y-1.5">
        <Label htmlFor="fp-email">Email</Label>
        <Input
          id="fp-email"
          type="email"
          autoComplete="email"
          placeholder="you@company.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          aria-invalid={!!request.fieldErrors.email}
        />
        {request.fieldErrors.email && (
          <p className="text-caption text-destructive">{request.fieldErrors.email}</p>
        )}
      </div>

      <Button type="submit" className="w-full" disabled={request.isPending}>
        {request.isPending && <Loader2 className="animate-spin" />}
        {request.isPending ? "Sending..." : "Send reset link"}
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
