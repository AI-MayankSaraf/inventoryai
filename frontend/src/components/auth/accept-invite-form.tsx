import Link from "next/link";
import { MailQuestion } from "lucide-react";

import { Logo } from "@/components/common/logo";
import { Button } from "@/components/ui/button";

/**
 * Accepting an invitation — verifying the link, setting a password and
 * activating the account — is a server-side flow. The new API surface has no
 * public accept-invitation endpoint for a prototype frontend to call, so this
 * page does not pretend to look one up or submit a password; it says so and
 * sends the person to sign in instead.
 */
export function AcceptInviteForm({ inviteId }: { inviteId: string }) {
  return (
    <div className="w-full max-w-[420px] text-center lg:max-w-[380px] max-lg:rounded-xl max-lg:border max-lg:border-border max-lg:bg-card max-lg:p-6 max-lg:shadow-card max-sm:p-5 sm:max-lg:p-8">
      <Logo className="mx-auto mb-6 justify-center lg:hidden" />

      <span className="mx-auto mb-4 flex size-12 items-center justify-center rounded-full bg-info-subtle">
        <MailQuestion className="size-6 text-info-subtle-foreground" />
      </span>
      <h2 className="text-[22px] font-semibold text-foreground">Invitations are accepted on the server</h2>
      <p className="mt-1.5 text-body text-muted-foreground">
        Verifying an invite link, setting a password and activating the account happens server-side and
        isn&apos;t part of this prototype — there is nothing this page can look up or submit for invitation{" "}
        <span className="font-mono text-foreground">{inviteId}</span>.
      </p>
      <Button asChild className="mt-5">
        <Link href="/login">Go to Sign In</Link>
      </Button>
    </div>
  );
}
