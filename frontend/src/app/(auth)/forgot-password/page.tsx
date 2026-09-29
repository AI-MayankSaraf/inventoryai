import type { Metadata } from "next";

import { ForgotPasswordForm } from "@/components/auth/forgot-password-form";
import { LoginBrandPanel } from "@/components/auth/login-brand-panel";

export const metadata: Metadata = {
  title: "Reset your password",
  description: "Request a password reset link for your InventoryAI account.",
};

export default function ForgotPasswordPage() {
  return (
    <main className="flex min-h-dvh bg-background">
      <LoginBrandPanel />
      <div className="flex w-full flex-1 flex-col lg:w-[46%] lg:max-w-[620px]">
        <div className="flex flex-1 items-center justify-center px-5 py-10 sm:px-10">
          <ForgotPasswordForm />
        </div>
      </div>
    </main>
  );
}
