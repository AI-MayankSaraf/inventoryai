import { Suspense } from "react";
import type { Metadata } from "next";

import { LoginBrandPanel } from "@/components/auth/login-brand-panel";
import { SupplierSetPasswordForm } from "@/components/supplier-portal/set-password-form";

export const metadata: Metadata = {
  title: "Set your portal password",
  description: "Set the password for your InventoryAI Supplier Portal account.",
};

export default function SupplierSetPasswordPage() {
  return (
    <main className="flex min-h-dvh bg-background">
      <LoginBrandPanel />
      <div className="flex w-full flex-1 flex-col lg:w-[46%] lg:max-w-[620px]">
        <div className="flex flex-1 items-center justify-center px-5 py-10 sm:px-10">
          {/* `useSearchParams` needs a suspense boundary in the app router. */}
          <Suspense fallback={null}>
            <SupplierSetPasswordForm />
          </Suspense>
        </div>
      </div>
    </main>
  );
}
