"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertCircle, Eye, EyeOff, Loader2 } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Logo } from "@/components/common/logo";
import { useSupplierSession } from "@/hooks/use-supplier-session";
import { EMAIL_REGEX } from "@/lib/format";

type FieldErrors = { email?: string; password?: string };

/**
 * Single sign-in for a supplier contact, regardless of how many companies on
 * the platform they supply to — the "single-login" ask from supplier
 * feedback. Which company to work in is a separate step (the company
 * switcher), not a separate account.
 */
export function SupplierLoginForm() {
  const router = useRouter();
  const { signIn } = useSupplierSession();

  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [showPassword, setShowPassword] = React.useState(false);
  const [errors, setErrors] = React.useState<FieldErrors>({});
  const [formError, setFormError] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);

  function validate(): FieldErrors {
    const next: FieldErrors = {};
    if (!email.trim()) next.email = "Email is required.";
    else if (!EMAIL_REGEX.test(email.trim())) next.email = "Enter a valid email address.";
    if (!password) next.password = "Password is required.";
    return next;
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);

    const nextErrors = validate();
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    setSubmitting(true);
    try {
      const principal = await signIn(email.trim(), password);
      router.push(
        principal.companies.length > 1 ? "/supplier-portal/select-company" : "/supplier-portal/dashboard",
      );
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Sign-in failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="w-full max-w-[420px] lg:max-w-[380px] max-lg:rounded-xl max-lg:border max-lg:border-border max-lg:bg-card max-lg:p-6 max-lg:shadow-card max-sm:p-5 sm:max-lg:p-8">
      <Logo className="mb-7 lg:hidden" />

      <header className="mb-7">
        <h2 className="text-[26px] leading-tight font-semibold tracking-[-0.025em] text-foreground">
          Supplier Portal
        </h2>
        <p className="mt-1.5 text-body text-muted-foreground">
          One sign-in, every company you supply on InventoryAI.
        </p>
      </header>

      {formError && (
        <Alert variant="destructive" className="mb-5">
          <AlertCircle />
          <AlertDescription>{formError}</AlertDescription>
        </Alert>
      )}

      <form onSubmit={handleSubmit} noValidate className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="supplier-email">Email</Label>
          <Input
            id="supplier-email"
            name="email"
            type="text"
            autoComplete="username"
            placeholder="you@yourcompany.com"
            value={email}
            aria-invalid={!!errors.email}
            onChange={(e) => {
              setEmail(e.target.value);
              if (errors.email) setErrors((p) => ({ ...p, email: undefined }));
            }}
            disabled={submitting}
          />
          {errors.email && <p className="text-caption text-destructive">{errors.email}</p>}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="supplier-password">Password</Label>
          <div className="relative">
            <Input
              id="supplier-password"
              name="password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              placeholder="••••••••"
              className="pr-10"
              value={password}
              aria-invalid={!!errors.password}
              onChange={(e) => {
                setPassword(e.target.value);
                if (errors.password) setErrors((p) => ({ ...p, password: undefined }));
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
              {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
            </button>
          </div>
          {errors.password && <p className="text-caption text-destructive">{errors.password}</p>}
        </div>

        <Button type="submit" size="lg" className="mt-1 w-full" disabled={submitting}>
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
        Managing this company from the inside?{" "}
        <Link href="/login" className="font-medium text-primary transition-colors hover:text-primary-hover">
          Go to the staff sign-in
        </Link>
      </p>

      <p className="mt-4 text-center text-[12.5px] text-muted-foreground">
        No password yet, or forgot it? Ask the company you supply to send you a portal link.
      </p>
    </div>
  );
}
