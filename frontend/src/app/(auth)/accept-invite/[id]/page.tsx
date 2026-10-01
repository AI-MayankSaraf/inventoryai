import { redirect } from "next/navigation";

/**
 * Old invitation URL shape. Invitations are accepted at
 * /accept-invitation?token=…, which is what the invitation email links to;
 * this keeps any older link working instead of showing a dead end.
 */
export default async function AcceptInviteRedirect({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  redirect(`/accept-invitation?token=${encodeURIComponent(id)}`);
}
