import { Suspense } from "react";
import type { Metadata } from "next";

import { AcceptInvitationForm } from "@/components/auth/accept-invitation-form";
import { LoginBrandPanel } from "@/components/auth/login-brand-panel";

export const metadata: Metadata = {
  title: "Accept Invitation",
  description: "Accept your invitation to join InventoryAI.",
};

export default function AcceptInvitationPage() {
  return (
    <main className="flex min-h-dvh bg-background">
      <LoginBrandPanel />
      <div className="flex w-full flex-1 flex-col lg:w-[46%] lg:max-w-[620px]">
        <div className="flex flex-1 items-center justify-center px-5 py-10 sm:px-10">
          {/* `useSearchParams` needs a suspense boundary in the app router. */}
          <Suspense fallback={null}>
            <AcceptInvitationForm />
          </Suspense>
        </div>
      </div>
    </main>
  );
}
