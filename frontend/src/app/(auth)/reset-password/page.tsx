import { Suspense } from "react";
import type { Metadata } from "next";

import { LoginBrandPanel } from "@/components/auth/login-brand-panel";
import { ResetPasswordForm } from "@/components/auth/reset-password-form";

export const metadata: Metadata = {
  title: "Choose a new password",
  description: "Set a new password for your InventoryAI account.",
};

export default function ResetPasswordPage() {
  return (
    <main className="flex min-h-dvh bg-background">
      <LoginBrandPanel />
      <div className="flex w-full flex-1 flex-col lg:w-[46%] lg:max-w-[620px]">
        <div className="flex flex-1 items-center justify-center px-5 py-10 sm:px-10">
          {/* `useSearchParams` needs a suspense boundary in the app router. */}
          <Suspense fallback={null}>
            <ResetPasswordForm />
          </Suspense>
        </div>
      </div>
    </main>
  );
}
