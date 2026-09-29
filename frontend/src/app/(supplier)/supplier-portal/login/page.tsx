import type { Metadata } from "next";

import { LoginBrandPanel } from "@/components/auth/login-brand-panel";
import { SupplierLoginForm } from "@/components/supplier-portal/supplier-login-form";

export const metadata: Metadata = {
  title: "Supplier Sign In",
  description: "Sign in to the InventoryAI Supplier Portal.",
};

export default function SupplierLoginPage() {
  return (
    <main className="flex min-h-dvh bg-background">
      <LoginBrandPanel />
      <div className="flex w-full flex-1 flex-col lg:w-[46%] lg:max-w-[620px]">
        <div className="flex flex-1 items-center justify-center px-5 py-10 sm:px-10">
          <SupplierLoginForm />
        </div>
      </div>
    </main>
  );
}
