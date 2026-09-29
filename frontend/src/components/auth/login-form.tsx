"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertCircle, Eye, EyeOff, Loader2 } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Logo } from "@/components/common/logo";
import { useApiMutation } from "@/hooks/use-api";
import { authApi } from "@/lib/api";
import { EMAIL_REGEX } from "@/lib/format";

type FieldErrors = { email?: string; password?: string };

export function LoginForm() {
  const router = useRouter();
  // Set by the reset screen once a new password is saved.
  const searchParams = useSearchParams();
  const justReset = searchParams.get("reset") === "1";
  const justInvited = searchParams.get("invited") === "1";

  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [remember, setRemember] = React.useState(true);
  const [showPassword, setShowPassword] = React.useState(false);
  const [errors, setErrors] = React.useState<FieldErrors>({});

  // The demo accounts come from the seeded user table, so the buttons below
  // can never drift from the credentials that actually work.
  const accounts = React.useMemo(() => authApi.demoAccounts(), []);

  const login = useApiMutation(
    (input: { identifier: string; password: string }) =>
      authApi.signIn(input.identifier, input.password),
    {
      onSuccess: (user) => {
        router.push(user.isPlatformAdmin ? "/system-admin" : "/dashboard");
      },
    },
  );
  const submitting = login.isPending;
  const formError = login.error;

  function validate(): FieldErrors {
    const next: FieldErrors = {};
    const trimmed = email.trim();
    const isKnownUsername = accounts.some(
      (a) => a.username.toLowerCase() === trimmed.toLowerCase(),
    );
    if (!trimmed) next.email = "Email or username is required.";
    else if (!isKnownUsername && !EMAIL_REGEX.test(trimmed))
      next.email = "Enter a valid email address or username.";

    if (!password) next.password = "Password is required.";
    else if (password.length < 6)
      next.password = "Password must be at least 6 characters.";

    return next;
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    login.reset();

    const nextErrors = validate();
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    await login.run({ identifier: email.trim(), password });
  }

  function quickFill(account: (typeof accounts)[number]) {
    setEmail(account.username);
    setPassword(account.password);
    setErrors({});
    login.reset();
  }

  return (
    <div className="w-full max-w-[420px] lg:max-w-[380px] max-lg:rounded-xl max-lg:border max-lg:border-border max-lg:bg-card max-lg:p-6 max-lg:shadow-card max-sm:p-5 sm:max-lg:p-8">
      {/* Logo repeats here for tablet/mobile, where the brand panel is hidden */}
      <Logo className="mb-7 lg:hidden" />

      <header className="mb-7">
        <h2 className="text-[26px] leading-tight font-semibold tracking-[-0.025em] text-foreground">
          Welcome Back
        </h2>
        <p className="mt-1.5 text-body text-muted-foreground">
          Sign in to your account
        </p>
      </header>

      {justReset && !formError && (
        <Alert variant="success">
          <AlertDescription>Your password has been changed. Sign in with it.</AlertDescription>
        </Alert>
      )}

      {justInvited && !formError && (
        <Alert variant="success">
          <AlertDescription>Your account is active. Sign in with the password you just set.</AlertDescription>
        </Alert>
      )}

      {formError && (
        <Alert variant="destructive" className="mb-5">
          <AlertCircle />
          <AlertDescription>{formError}</AlertDescription>
        </Alert>
      )}

      <form onSubmit={handleSubmit} noValidate className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="email">Email or Username</Label>
          <Input
            id="email"
            name="email"
            type="text"
            autoComplete="username"
            placeholder="you@company.com or superadmin"
            value={email}
            aria-invalid={!!errors.email}
            aria-describedby={errors.email ? "email-error" : undefined}
            onChange={(e) => {
              setEmail(e.target.value);
              if (errors.email) setErrors((p) => ({ ...p, email: undefined }));
            }}
            disabled={submitting}
          />
          {errors.email && (
            <p id="email-error" className="text-caption text-destructive">
              {errors.email}
            </p>
          )}
        </div>

        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <Label htmlFor="password">Password</Label>
            <Link
              href="/forgot-password"
              className="text-[12.5px] font-medium text-primary transition-colors hover:text-primary-hover"
            >
              Forgot password?
            </Link>
          </div>
          <div className="relative">
            <Input
              id="password"
              name="password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              placeholder="••••••••"
              className="pr-10"
              value={password}
              aria-invalid={!!errors.password}
              aria-describedby={errors.password ? "password-error" : undefined}
              onChange={(e) => {
                setPassword(e.target.value);
                if (errors.password)
                  setErrors((p) => ({ ...p, password: undefined }));
              }}
              disabled={submitting}
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              aria-label={showPassword ? "Hide password" : "Show password"}
              className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-md text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/25 focus-visible:outline-none"
              tabIndex={-1}
            >
              {showPassword ? (
                <EyeOff className="size-4" />
              ) : (
                <Eye className="size-4" />
              )}
            </button>
          </div>
          {errors.password && (
            <p id="password-error" className="text-caption text-destructive">
              {errors.password}
            </p>
          )}
        </div>

        <div className="flex items-center gap-2 pt-0.5">
          <Checkbox
            id="remember"
            checked={remember}
            onCheckedChange={(v) => setRemember(v === true)}
            disabled={submitting}
          />
          <Label htmlFor="remember" className="font-normal text-muted-foreground">
            Keep me signed in
          </Label>
        </div>

        <Button
          type="submit"
          size="lg"
          className="mt-1 w-full"
          disabled={submitting}
        >
          {submitting ? (
            <>
              <Loader2 className="animate-spin" />
              Signing in…
            </>
          ) : (
            "Sign In"
          )}
        </Button>
      </form>

      <p className="mt-6 text-center text-[13px] text-muted-foreground">
        Don&apos;t have an account?{" "}
        <a
          href="#"
          className="font-medium text-primary transition-colors hover:text-primary-hover"
        >
          Contact your administrator
        </a>
      </p>

      <p className="mt-2 text-center text-[13px] text-muted-foreground">
        Signing in as a supplier?{" "}
        <Link
          href="/supplier-portal/login"
          className="font-medium text-primary transition-colors hover:text-primary-hover"
        >
          Go to the Supplier Portal
        </Link>
      </p>

      <div className="mt-7 space-y-2 rounded-lg border border-dashed border-border bg-muted/40 p-3.5">
        <p className="text-[11.5px] font-medium text-muted-foreground">
          Prototype demo logins — click to fill
        </p>
        {accounts.map((account) => (
          <button
            key={account.username}
            type="button"
            onClick={() => quickFill(account)}
            disabled={submitting}
            className="flex w-full items-center justify-between rounded-md border border-border bg-card px-2.5 py-1.5 text-left transition-colors hover:border-ring hover:bg-muted disabled:opacity-50"
          >
            <span>
              <span className="block text-[12px] font-medium text-foreground">
                {account.label} · {account.roleName}
              </span>
              <span className="block font-mono text-[10.5px] text-muted-foreground">
                {account.username}
              </span>
            </span>
            <span className="font-mono text-[10.5px] text-muted-foreground">{account.password}</span>
          </button>
        ))}
        <p className="text-[10.5px] text-muted-foreground/70">
          These are the only accounts that sign in. Sign-in selects which seeded user the prototype
          acts as — it is not an authentication system.
        </p>
      </div>
    </div>
  );
}
