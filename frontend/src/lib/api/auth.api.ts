/**
 * Session and identity.
 *
 * Sign-in now talks to the real backend: `POST /auth/login` for tokens
 * (stored via `client.ts`'s `storeTokens`), then `GET /auth/me` for the
 * profile fields a JWT doesn't carry (full name, company name, the role's
 * display name). `SessionUser` is cached in `localStorage` under
 * `SESSION_CACHE_KEY` purely so `currentSession()` can stay synchronous —
 * every route guard and the mock audit-log stamper (`./audit.ts`) rely on
 * that — while the actual source of truth is always the token plus the
 * next `getSession()` refetch.
 *
 * Password reset, password change and impersonation are real too
 * (`/auth/forgot-password`, `/auth/reset-password`, `/auth/change-password`,
 * `/platform/impersonate`). Impersonation swaps the stored token for the
 * 30-minute one the platform endpoint returns, keeping the admin's own pair
 * aside so "Return to Super Admin" is a local restore rather than a second
 * sign-in (BR-AUTH-07).
 */

import type { CompanyMembership, Id, ImpersonationSession, PermissionCode, SessionUser } from "@/types";
import { getStoredTokens, httpGet, httpPatch, httpPost, storeTokens, validationFailed } from "./client";

const SESSION_KEY = "inventoryai.session.v2";
const SESSION_CACHE_KEY = "inventoryai.session_user.v1";

interface StoredSession {
  userId: Id;
  impersonation?: ImpersonationSession | null;
}

const isBrowser = typeof window !== "undefined";

function readSession(): StoredSession | null {
  if (!isBrowser) return null;
  try {
    const raw = window.localStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as StoredSession) : null;
  } catch {
    return null;
  }
}

function writeSession(session: StoredSession | null): void {
  if (!isBrowser) return;
  try {
    if (session) window.localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    else window.localStorage.removeItem(SESSION_KEY);
  } catch {
    /* storage unavailable — the session simply does not survive a reload */
  }
}

/** `GET /auth/me`'s shape — see `app/modules/auth/schemas.py::MeOut`. */
interface MeResponse {
  id: string;
  company_id: string | null;
  company_name: string | null;
  email: string;
  full_name: string;
  phone: string | null;
  role_id: string;
  role_code: string;
  role_name: string;
  status: SessionUser["status"];
  is_platform_admin: boolean;
  godown_scope: { all: boolean; godown_ids: string[] };
  last_login_at: string | null;
  home_company_id?: string | null;
}

function toSessionUserFromMe(me: MeResponse): SessionUser {
  return {
    id: me.id,
    companyId: me.company_id,
    email: me.email,
    fullName: me.full_name,
    phone: me.phone ?? undefined,
    roleId: me.role_id,
    roleCode: me.role_code as SessionUser["roleCode"],
    status: me.status,
    isPlatformAdmin: me.is_platform_admin,
    godownScope: { all: me.godown_scope.all, godownIds: me.godown_scope.godown_ids },
    lastActiveAt: me.last_login_at ?? undefined,
    deletedAt: null,
    companyName: me.company_name ?? "InventoryAI Platform",
    roleName: me.role_name || me.role_code,
    permissions: [] as PermissionCode[], // filled in below, once fetched from the token-bearing login response
    homeCompanyId: me.home_company_id ?? me.company_id,
  };
}

function readSessionCache(): SessionUser | null {
  if (!isBrowser) return null;
  try {
    const raw = window.localStorage.getItem(SESSION_CACHE_KEY);
    return raw ? (JSON.parse(raw) as SessionUser) : null;
  } catch {
    return null;
  }
}

function writeSessionCache(user: SessionUser | null): void {
  if (!isBrowser) return;
  try {
    if (user) window.localStorage.setItem(SESSION_CACHE_KEY, JSON.stringify(user));
    else window.localStorage.removeItem(SESSION_CACHE_KEY);
  } catch {
    /* storage unavailable — the session simply does not survive a reload */
  }
}

interface TokenResponse {
  access_token: string;
  refresh_token: string;
}

export async function signIn(identifier: string, password: string): Promise<SessionUser> {
  const tokens = await httpPost<TokenResponse>("/auth/login", { email: identifier.trim(), password }, { auth: false });
  storeTokens({ accessToken: tokens.access_token, refreshToken: tokens.refresh_token });

  const me = await httpGet<MeResponse>("/auth/me");
  // The JWT itself carries the permission list `/auth/me` doesn't repeat
  // (it's derived server-side from the role, not stored on the user row).
  // Decode it client-side — it's already an authenticated response we just
  // received over TLS from our own backend, not an untrusted third party.
  const permissions = decodePermissionsFromToken(tokens.access_token);
  const user: SessionUser = { ...toSessionUserFromMe(me), permissions };
  writeSessionCache(user);
  return user;
}

function decodePermissionsFromToken(accessToken: string): PermissionCode[] {
  try {
    const payloadB64 = accessToken.split(".")[1];
    const json = isBrowser ? window.atob(payloadB64) : Buffer.from(payloadB64, "base64").toString("utf-8");
    const payload = JSON.parse(json) as { permissions?: string[] };
    return (payload.permissions ?? []) as PermissionCode[];
  } catch {
    return [];
  }
}

export async function signOut(): Promise<void> {
  const tokens = getStoredTokens();
  storeTokens(null);
  writeSessionCache(null);
  if (tokens) {
    try {
      await httpPost("/auth/logout", { refresh_token: tokens.refreshToken }, { auth: false });
    } catch {
      /* best-effort — the client-side tokens are already cleared either way */
    }
  }
}

/** The cached principal, or null when signed out. Synchronous for guards —
 * refreshed on every `signIn()` and `getSession()`. */
export function currentSession(): SessionUser | null {
  return readSessionCache();
}

export async function getSession(): Promise<SessionUser | null> {
  const tokens = getStoredTokens();
  if (!tokens) {
    writeSessionCache(null);
    return null;
  }
  try {
    const me = await httpGet<MeResponse>("/auth/me");
    // Decoded from the *current* stored access token, not the cache — if a
    // role change forced a fresh token (BR-AUTH-11), this always reflects it.
    const permissions = decodePermissionsFromToken(tokens.accessToken);
    const user: SessionUser = { ...toSessionUserFromMe(me), permissions };
    writeSessionCache(user);
    return user;
  } catch {
    storeTokens(null);
    writeSessionCache(null);
    return null;
  }
}

/**
 * `PATCH /auth/me` — edit your own name and phone. Needs no permission beyond
 * being signed in; email, role, status and godown scope stay with whoever
 * holds `user.manage`. Refreshes the session cache so the header shows the
 * new name straight away.
 */
export async function updateMyProfile(input: { fullName: string; phone: string }): Promise<SessionUser> {
  const me = await httpPatch<MeResponse>("/auth/me", {
    full_name: input.fullName.trim(),
    phone: input.phone.trim(),
  });
  const tokens = getStoredTokens();
  const permissions = tokens ? decodePermissionsFromToken(tokens.accessToken) : [];
  const user: SessionUser = { ...toSessionUserFromMe(me), permissions };
  writeSessionCache(user);
  return user;
}

/* ------------------------------------ Multi-company login (BR-AUTH-13) */

interface CompanyMembershipOut {
  company_id: string;
  company_name: string;
  company_status: CompanyMembership["companyStatus"];
  role_code: string;
  role_name: string;
  is_home: boolean;
  is_current: boolean;
}

/** Companies this login can act in, home first. One entry for most people;
 * the header only offers switching when there is more than one. */
export async function listMyCompanies(): Promise<CompanyMembership[]> {
  const rows = await httpGet<CompanyMembershipOut[]>("/auth/me/companies");
  return rows.map((r) => ({
    companyId: r.company_id,
    companyName: r.company_name,
    companyStatus: r.company_status,
    roleCode: r.role_code,
    roleName: r.role_name,
    isHome: r.is_home,
    isCurrent: r.is_current,
  }));
}

/**
 * Move this session into another company the login belongs to. The server
 * checks the membership and hands back a new token pair scoped to that
 * company (with the role held *there*); the old refresh token is sent along
 * so it is revoked rather than left lying around.
 *
 * Callers should reload the app afterwards: every cached list on screen
 * belongs to the company being left.
 */
export async function switchCompany(companyId: Id): Promise<SessionUser> {
  const tokens = getStoredTokens();
  const out = await httpPost<TokenResponse>("/auth/switch-company", {
    company_id: companyId,
    refresh_token: tokens?.refreshToken,
  });
  storeTokens({ accessToken: out.access_token, refreshToken: out.refresh_token });
  const me = await httpGet<MeResponse>("/auth/me");
  const user: SessionUser = { ...toSessionUserFromMe(me), permissions: decodePermissionsFromToken(out.access_token) };
  writeSessionCache(user);
  return user;
}

export function currentImpersonation(): ImpersonationSession | null {
  return readSession()?.impersonation ?? null;
}

/** The account the sign-in screen offers. Only one exists in the seeded
 * backend today (`app/db/seed.py::seed_demo_company`). */
export function demoAccounts(): { username: string; password: string; label: string; roleName: string }[] {
  return [{ username: "owner@acme-demo.test", password: "Demo@12345", label: "Demo Owner", roleName: "Owner" }];
}

/* ------------------------------------------------------ Password reset */

/** Always resolves, whatever the address: the backend answers 202 either
 * way so the screen cannot be used to find out who has an account. */
export async function requestPasswordReset(email: string): Promise<void> {
  if (!EMAIL_PATTERN.test(email.trim())) {
    validationFailed([{ field: "email", message: "Enter the email address you sign in with." }]);
  }
  await httpPost("/auth/forgot-password", { email: email.trim() }, { auth: false });
}

export async function resetPassword(token: string, newPassword: string): Promise<void> {
  validateNewPassword(newPassword, "newPassword");
  await httpPost("/auth/reset-password", { token, new_password: newPassword }, { auth: false });
}

/** `POST /invitations/accept` — public: the invitee has no account yet. The
 * backend creates the user from the invitation and returns it; the person then
 * signs in normally. */
export async function acceptInvitation(token: string, password: string, fullName?: string): Promise<void> {
  validateNewPassword(password, "password");
  await httpPost(
    "/invitations/accept",
    { invitation_token: token, password, full_name: fullName?.trim() || undefined },
    { auth: false },
  );
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  validateNewPassword(newPassword, "newPassword");
  if (currentPassword === newPassword) {
    validationFailed([{ field: "newPassword", message: "The new password must be different from the current one." }]);
  }
  await httpPost("/auth/change-password", {
    current_password: currentPassword,
    new_password: newPassword,
  });
  // Changing a password ends every session, including this one (the server
  // revokes them), so the client stops pretending otherwise.
  storeTokens(null);
  writeSessionCache(null);
  writeSession(null);
}

const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** BR-AUTH-02, checked here so the form can answer without a round trip.
 * The backend enforces the same rule and returns `PASSWORD_TOO_WEAK`. */
function validateNewPassword(password: string, field: string): void {
  const problems: string[] = [];
  if (password.length < 8) problems.push("at least 8 characters");
  if (!/[a-zA-Z]/.test(password)) problems.push("a letter");
  if (!/[0-9]/.test(password)) problems.push("a number");
  if (problems.length) {
    validationFailed([{ field, message: `The password needs ${problems.join(" and ")}.` }]);
  }
}

/* -------------------------------------------------------- Impersonation */

interface ImpersonationOut {
  id: string;
  platform_user_id: string;
  target_user_id: string;
  target_user_name: string;
  target_company_id: string;
  target_company_name: string;
  reason: string | null;
  ended_at: string | null;
}

interface ImpersonationTokenOut {
  access_token: string;
  expires_in: number;
  impersonation: ImpersonationOut;
}

/** Where the platform admin's own tokens wait while they are looking
 * through someone else's eyes. Kept separate from the live token pair so
 * "Return to Super Admin" restores rather than re-authenticates. */
const ADMIN_TOKENS_KEY = "inventoryai.platform_tokens.v1";

function stashAdminTokens(): void {
  const tokens = getStoredTokens();
  if (!isBrowser || !tokens) return;
  try {
    window.localStorage.setItem(ADMIN_TOKENS_KEY, JSON.stringify(tokens));
  } catch {
    /* without this the admin simply signs in again after stopping */
  }
}

function popAdminTokens(): { accessToken: string; refreshToken: string } | null {
  if (!isBrowser) return null;
  try {
    const raw = window.localStorage.getItem(ADMIN_TOKENS_KEY);
    window.localStorage.removeItem(ADMIN_TOKENS_KEY);
    return raw ? (JSON.parse(raw) as { accessToken: string; refreshToken: string }) : null;
  } catch {
    return null;
  }
}

export async function startImpersonation(targetUserId: Id, reason: string): Promise<SessionUser> {
  if (reason.trim().length < 3) {
    validationFailed([{ field: "reason", message: "A reason is required — it goes into the audit trail." }]);
  }
  stashAdminTokens();
  try {
    const out = await httpPost<ImpersonationTokenOut>("/platform/impersonate", {
      user_id: targetUserId,
      reason: reason.trim(),
    });
    // BR-AUTH-07: no refresh token exists for an impersonation session, so
    // the pair stores the access token in both slots — a refresh attempt
    // then presents an access token to `/auth/refresh`, which never matches
    // a stored refresh-token hash, so it fails. That is the intended
    // behaviour rather than an oversight.
    //
    // It cannot be stored as `""`: `getStoredTokens` treats a missing half
    // as "not signed in" and returns null, so every request during the
    // impersonation session would go out with no Authorization header at
    // all and come back 401 — which is exactly what happened before.
    storeTokens({ accessToken: out.access_token, refreshToken: out.access_token });
    const me = await httpGet<MeResponse>("/auth/me");
    const user: SessionUser = {
      ...toSessionUserFromMe(me),
      permissions: decodePermissionsFromToken(out.access_token),
    };
    writeSessionCache(user);
    writeSession({ userId: out.impersonation.platform_user_id, impersonation: toImpersonation(out.impersonation) });
    return user;
  } catch (error) {
    // Put the admin's own tokens back: a refused impersonation must not
    // leave them signed out.
    const admin = popAdminTokens();
    if (admin) storeTokens(admin);
    throw error;
  }
}

function toImpersonation(o: ImpersonationOut): ImpersonationSession {
  return {
    id: o.id,
    platformUserId: o.platform_user_id,
    platformUserName: "Platform Admin",
    targetUserId: o.target_user_id,
    targetUserName: o.target_user_name,
    targetCompanyId: o.target_company_id,
    targetCompanyName: o.target_company_name,
    reason: o.reason ?? "",
    startedAt: new Date().toISOString(),
    expiresAt: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
    endedAt: o.ended_at,
  };
}

export async function endImpersonation(): Promise<SessionUser | null> {
  try {
    await httpPost("/platform/impersonate/stop");
  } catch {
    // Already ended or expired server-side — either way, stop locally.
  }
  writeSession(null);
  const admin = popAdminTokens();
  if (!admin) {
    storeTokens(null);
    writeSessionCache(null);
    return null;
  }
  storeTokens(admin);
  return getSession();
}

/* ------------------------------------------------------------ Directory */

// The impersonation picker used to read `/users` here, which is a *tenant*
// endpoint: a platform admin's token carries no company, so it returned
// nothing for the one person allowed to impersonate. It now comes from
// `adminApi.listPlatformUsers` (`/platform/users`), which is cross-tenant
// and already excludes platform admins — they cannot be impersonated.
