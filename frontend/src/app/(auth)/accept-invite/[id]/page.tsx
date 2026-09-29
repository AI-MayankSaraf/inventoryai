import type { Metadata } from "next";

import { AcceptInviteForm } from "@/components/auth/accept-invite-form";
import { LoginBrandPanel } from "@/components/auth/login-brand-panel";

export const metadata: Metadata = {
  title: "Accept Invitation",
  description: "Accept your invitation to join InventoryAI.",
};

export default async function AcceptInvitePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  return (
    <main className="flex min-h-dvh bg-background">
      <LoginBrandPanel />
      <div className="flex w-full flex-1 flex-col items-center justify-center lg:w-[46%] lg:max-w-[620px] px-5 py-10 sm:px-10">
        <AcceptInviteForm inviteId={id} />
      </div>
    </main>
  );
}
