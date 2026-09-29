import { Suspense } from "react";
import type { Metadata } from "next";

import { LoginForm } from "@/components/auth/login-form";
import { LoginBrandPanel } from "@/components/auth/login-brand-panel";

export const metadata: Metadata = {
  title: "Sign In",
  description: "Sign in to InventoryAI — smarter procurement, better inventory.",
};

export default function LoginPage() {
  return (
    <main className="flex min-h-dvh bg-background">
      {/* Left — branding. Hidden on tablet/mobile, where the form takes the full width. */}
      <LoginBrandPanel />

      {/* Right — sign-in form */}
      <div className="flex w-full flex-1 flex-col lg:w-[46%] lg:max-w-[620px]">
        <div className="flex flex-1 items-center justify-center px-5 py-10 sm:px-10">
          {/* `useSearchParams` needs a suspense boundary in the app router. */}
          <Suspense fallback={null}>
            <LoginForm />
          </Suspense>
        </div>

        <footer className="px-5 pb-7 sm:px-10">
          <div className="mx-auto flex w-full max-w-[420px] flex-col gap-2 lg:max-w-[380px] text-caption text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
            <span>© 2026 InventoryAI</span>
            <span className="flex items-center gap-3">
              <a className="transition-colors hover:text-foreground" href="#">
                Privacy
              </a>
              <a className="transition-colors hover:text-foreground" href="#">
                Terms
              </a>
              <a className="transition-colors hover:text-foreground" href="#">
                Support
              </a>
            </span>
          </div>
        </footer>
      </div>
    </main>
  );
}
