"use client";

import * as React from "react";
import { CheckCircle2, Mail, Send, TriangleAlert } from "lucide-react";

import { FormError } from "@/components/common/async-state";
import { PermissionButton } from "@/components/common/permission-gate";
import { SectionCard } from "@/components/common/section-card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useEmailSettings, useSaveEmailSettings, useSendTestEmail } from "@/hooks/use-admin";
import { usePermission } from "@/hooks/use-session";
import { formatDateTime } from "@/lib/format";

/**
 * Where invitations and password-reset links are sent from.
 *
 * The password is write-only: the API says whether one is stored, never
 * what it is. Leaving the field blank keeps it; clearing it explicitly
 * removes it.
 */
export function EmailSettingsCard() {
  const state = useEmailSettings();
  const canManage = usePermission("company.manage");
  const [form, setForm] = React.useState<{
    provider: "console" | "smtp";
    fromAddress: string;
    fromName: string;
    smtpHost: string;
    smtpPort: string;
    smtpUsername: string;
    smtpPassword: string;
    smtpUseTls: boolean;
  } | null>(null);
  const [testTo, setTestTo] = React.useState("");
  const seeded = React.useRef(false);

  React.useEffect(() => {
    if (seeded.current || !state.data) return;
    const s = state.data;
    setForm({
      provider: s.provider,
      fromAddress: s.fromAddress,
      fromName: s.fromName,
      smtpHost: s.smtpHost,
      smtpPort: String(s.smtpPort),
      smtpUsername: s.smtpUsername,
      smtpPassword: "",
      smtpUseTls: s.smtpUseTls,
    });
    seeded.current = true;
  }, [state.data]);

  const save = useSaveEmailSettings(() => {
    seeded.current = false;
    state.refresh();
  });
  const test = useSendTestEmail(() => state.refresh());

  if (!form) return null;
  const stored = state.data;
  const isSmtp = form.provider === "smtp";

  return (
    <div data-testid="email-settings">
    <SectionCard
      title="Outgoing Email"
      description="Used for invitations and password-reset links"
    >
      <div className="space-y-3.5 p-4">
        <div className="space-y-1.5">
          <Label htmlFor="em-provider">How email is sent</Label>
          <Select
            value={form.provider}
            onValueChange={(v) => setForm({ ...form, provider: v as "console" | "smtp" })}
            disabled={!canManage}
          >
            <SelectTrigger id="em-provider">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="console">Not configured — messages are only logged</SelectItem>
              <SelectItem value="smtp">Your own SMTP server</SelectItem>
            </SelectContent>
          </Select>
          {!isSmtp && (
            <p className="text-caption text-muted-foreground">
              Invitations and reset links are recorded but never delivered until a mail server is set
              up here.
            </p>
          )}
        </div>

        {isSmtp && (
          <>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="em-from">From address</Label>
                <Input
                  id="em-from"
                  value={form.fromAddress}
                  placeholder="no-reply@yourcompany.in"
                  onChange={(e) => setForm({ ...form, fromAddress: e.target.value })}
                  disabled={!canManage}
                  aria-invalid={!!save.fieldErrors.fromAddress}
                />
                {save.fieldErrors.fromAddress && (
                  <p className="text-caption text-destructive">{save.fieldErrors.fromAddress}</p>
                )}
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="em-from-name">From name</Label>
                <Input
                  id="em-from-name"
                  value={form.fromName}
                  placeholder="Your company"
                  onChange={(e) => setForm({ ...form, fromName: e.target.value })}
                  disabled={!canManage}
                />
              </div>
            </div>

            <div className="grid grid-cols-[1fr_110px] gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="em-host">SMTP host</Label>
                <Input
                  id="em-host"
                  value={form.smtpHost}
                  placeholder="smtp.yourprovider.com"
                  onChange={(e) => setForm({ ...form, smtpHost: e.target.value })}
                  disabled={!canManage}
                  aria-invalid={!!save.fieldErrors.smtpHost}
                />
                {save.fieldErrors.smtpHost && (
                  <p className="text-caption text-destructive">{save.fieldErrors.smtpHost}</p>
                )}
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="em-port">Port</Label>
                <Input
                  id="em-port"
                  type="number"
                  value={form.smtpPort}
                  onChange={(e) => setForm({ ...form, smtpPort: e.target.value })}
                  disabled={!canManage}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="em-user">Username</Label>
                <Input
                  id="em-user"
                  value={form.smtpUsername}
                  onChange={(e) => setForm({ ...form, smtpUsername: e.target.value })}
                  disabled={!canManage}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="em-password">Password</Label>
                <Input
                  id="em-password"
                  type="password"
                  autoComplete="new-password"
                  value={form.smtpPassword}
                  placeholder={stored?.hasPassword ? "•••••••• (unchanged)" : "Not set"}
                  onChange={(e) => setForm({ ...form, smtpPassword: e.target.value })}
                  disabled={!canManage}
                />
                <p className="text-caption text-muted-foreground">
                  {stored?.hasPassword
                    ? "Leave blank to keep the stored password."
                    : "Stored encrypted; never shown again."}
                </p>
              </div>
            </div>

            <div className="flex items-center justify-between rounded-lg bg-muted/50 px-3.5 py-2.5">
              <div>
                <p className="text-[13.5px] font-medium text-foreground">Use TLS (STARTTLS)</p>
                <p className="text-caption text-muted-foreground">Almost always on for port 587.</p>
              </div>
              <Switch
                checked={form.smtpUseTls}
                onCheckedChange={(v) => setForm({ ...form, smtpUseTls: v })}
                disabled={!canManage}
              />
            </div>
          </>
        )}

        {stored?.lastTestAt && (
          <Alert variant={stored.lastTestOk ? "success" : "destructive"}>
            {stored.lastTestOk ? <CheckCircle2 /> : <TriangleAlert />}
            <AlertDescription>
              Last test {formatDateTime(stored.lastTestAt)}:{" "}
              {stored.lastTestOk ? "delivered" : stored.lastTestError || "failed"}
            </AlertDescription>
          </Alert>
        )}

        <FormError message={save.error} fieldErrors={save.fieldErrors} />
        {test.data && (
          <Alert variant={test.data.sent ? "success" : "destructive"}>
            {test.data.sent ? <CheckCircle2 /> : <TriangleAlert />}
            <AlertDescription>
              {test.data.sent
                ? `Test message sent to ${test.data.toAddress}.`
                : `Could not send: ${test.data.error}`}
            </AlertDescription>
          </Alert>
        )}

        <div className="flex flex-col gap-2 border-t border-border pt-3 sm:flex-row sm:items-end">
          <div className="w-full space-y-1.5 sm:max-w-[260px]">
            <Label htmlFor="em-test-to">Send a test to</Label>
            <Input
              id="em-test-to"
              value={testTo}
              placeholder="your own address"
              onChange={(e) => setTestTo(e.target.value)}
              disabled={!canManage}
            />
          </div>
          <div className="flex gap-2 sm:ml-auto">
            <PermissionButton
              permission="company.manage"
              variant="outline"
              disabled={test.isPending}
              onClick={() => test.run(testTo || undefined)}
            >
              <Send />
              {test.isPending ? "Sending..." : "Send test"}
            </PermissionButton>
            <PermissionButton
              permission="company.manage"
              disabled={save.isPending}
              onClick={() =>
                save.run({
                  provider: form.provider,
                  fromAddress: form.fromAddress,
                  fromName: form.fromName,
                  smtpHost: form.smtpHost,
                  smtpPort: Number(form.smtpPort || 587),
                  smtpUsername: form.smtpUsername,
                  smtpUseTls: form.smtpUseTls,
                  // Undefined keeps whatever is stored; the field is only
                  // sent when the person actually typed something.
                  smtpPassword: form.smtpPassword === "" ? undefined : form.smtpPassword,
                })
              }
            >
              <Mail />
              {save.isPending ? "Saving..." : "Save email settings"}
            </PermissionButton>
          </div>
        </div>
      </div>
    </SectionCard>
    </div>
  );
}
