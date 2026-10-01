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
    if (!trimmed) next.email = "Email is required.";
    else if (!EMAIL_REGEX.test(trimmed)) next.email = "Enter a valid email address.";

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
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            name="email"
            type="text"
            autoComplete="username"
            placeholder="you@company.com"
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
    </div>
  );
}
