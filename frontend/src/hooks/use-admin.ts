"use client";

/** Feature hooks for users, roles, godowns, settings and the platform console. */

import { useCallback } from "react";
import { adminApi, authApi } from "@/lib/api";
import { previewNumber } from "@/lib/domain/numbering";
import type { CompanySettings, Id, Invitation, ListParams, PermissionCode, DocSequenceType } from "@/types";
import { useApiMutation, useApiQuery } from "./use-api";

export function useUsers(params: ListParams) {
  return useApiQuery(["users", params], () => adminApi.listUsers(params));
}

export function useInvitations() {
  return useApiQuery(["invitations"], () => adminApi.listInvitations());
}

export function useInviteUser(onSuccess?: (invitation: Invitation) => void) {
  return useApiMutation(adminApi.inviteUser, { onSuccess });
}

export function useResendInvitation(onSuccess?: (invitation: Invitation) => void) {
  return useApiMutation(adminApi.resendInvitation, { onSuccess });
}

export function useRevokeInvitation(onSuccess?: () => void) {
  return useApiMutation(adminApi.revokeInvitation, { onSuccess });
}

export function useUpdateUserAccess(onSuccess?: () => void) {
  const action = useCallback(
    (input: { userId: Id; patch: Parameters<typeof adminApi.updateUserAccess>[1] }) =>
      adminApi.updateUserAccess(input.userId, input.patch),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

export function useRemoveUser(onSuccess?: () => void) {
  return useApiMutation(adminApi.removeUser, { onSuccess });
}

export function useRoles() {
  return useApiQuery(["roles"], () => adminApi.listRoles());
}

export function useRole(roleId: Id | undefined) {
  return useApiQuery(["role", roleId], () => adminApi.getRole(roleId!), { enabled: !!roleId });
}

export function useGodownsWithUsage() {
  return useApiQuery(["godowns-with-usage"], () => adminApi.listGodownsWithUsage());
}

export function useGodownUsage(godownId: Id | undefined) {
  return useApiQuery(
    ["godown-usage", godownId],
    () => adminApi.getGodownUsage(godownId!),
    { enabled: !!godownId },
  );
}

export function useCreateGodown(onSuccess?: () => void) {
  return useApiMutation(adminApi.createGodown, { onSuccess });
}

export function useUpdateGodown(onSuccess?: () => void) {
  const action = useCallback(
    (input: { godownId: Id; data: adminApi.GodownInput }) => adminApi.updateGodown(input.godownId, input.data),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

export function useDeactivateGodown(onSuccess?: () => void) {
  return useApiMutation(adminApi.deactivateGodown, { onSuccess });
}

export function useCompanySettings() {
  return useApiQuery(["company-settings"], () => adminApi.getCompanySettings());
}

export function useUpdateCompanySettings(onSuccess?: () => void) {
  const action = useCallback((patch: Partial<CompanySettings>) => adminApi.updateCompanySettings(patch), []);
  return useApiMutation(action, { onSuccess });
}

export function useUpdateCompanyProfile(onSuccess?: () => void) {
  return useApiMutation(adminApi.updateCompanyProfile, { onSuccess });
}

export function useDocumentSequences() {
  return useApiQuery(["document-sequences"], () => adminApi.listDocumentSequences());
}

/** What the next document of this type would be numbered, read from the
 *  real sequence — a preview; the server assigns the number on save. */
export function useNextDocumentNumber(docType: DocSequenceType): string {
  const sequences = useDocumentSequences();
  if (sequences.isLoading && !sequences.data) return "…";
  return previewNumber(sequences.data, docType) ?? "Assigned on save";
}

export function useCloseInventoryPeriod(onSuccess?: () => void) {
  return useApiMutation(adminApi.closeInventoryPeriod, { onSuccess });
}

export function useCompanies(params: ListParams) {
  return useApiQuery(["companies", params], () => adminApi.listCompanies(params));
}

export function useSetCompanyStatus(onSuccess?: () => void) {
  const action = useCallback(
    (input: { companyId: Id; status: Parameters<typeof adminApi.setCompanyStatus>[1]; reason?: string }) =>
      adminApi.setCompanyStatus(input.companyId, input.status, input.reason),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

export function useUpdateCompany(onSuccess?: () => void) {
  const action = useCallback(
    (input: { companyId: Id; patch: Parameters<typeof adminApi.updateCompany>[1] }) =>
      adminApi.updateCompany(input.companyId, input.patch),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

/** One tenant's full detail row, for the console's Manage-tenant drill-down. */
export function useCompany(companyId: Id | undefined) {
  return useApiQuery(["company", companyId], () => adminApi.getCompany(companyId!), { enabled: !!companyId });
}

export function useCompanyInvitations(companyId: Id | undefined) {
  return useApiQuery(["company-invitations", companyId], () => adminApi.listCompanyInvitations(companyId!), {
    enabled: !!companyId,
  });
}

export function useInviteCompanyOwner(onSuccess?: (result: adminApi.ResentInvitation) => void) {
  const action = useCallback(
    (input: { companyId: Id; email: string; fullName: string }) =>
      adminApi.inviteCompanyOwner(input.companyId, { email: input.email, fullName: input.fullName }),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

export function useResendCompanyInvitation(onSuccess?: (result: adminApi.ResentInvitation) => void) {
  const action = useCallback(
    (input: { companyId: Id; invitationId: Id }) =>
      adminApi.resendCompanyInvitation(input.companyId, input.invitationId),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

export function useUserDirectory(filters: adminApi.DirectoryFilters) {
  return useApiQuery(["user-directory", filters], () => adminApi.listUserDirectory(filters));
}

export function useUpdatePlatformUserProfile(onSuccess?: () => void) {
  const action = useCallback(
    (input: { userId: Id; fullName: string; phone: string }) =>
      adminApi.updatePlatformUserProfile(input.userId, { fullName: input.fullName, phone: input.phone }),
    [],
  );
  return useApiMutation(action, { onSuccess: () => onSuccess?.() });
}

export function useSetTenantUserStatus(onSuccess?: () => void) {
  const action = useCallback(
    (input: { userId: Id; status: "active" | "inactive" }) =>
      adminApi.setTenantUserStatus(input.userId, input.status),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

/* ------------------------------------------ Linked owners (BR-AUTH-13) */

export function useCompanyMembers(companyId: Id | undefined) {
  return useApiQuery(["company-members", companyId], () => adminApi.listCompanyMembers(companyId!), {
    enabled: !!companyId,
  });
}

export function useAddCompanyMember(onSuccess?: () => void) {
  const action = useCallback(
    (input: { companyId: Id; email: string }) => adminApi.addCompanyMember(input.companyId, input.email),
    [],
  );
  return useApiMutation(action, { onSuccess: () => onSuccess?.() });
}

export function useRemoveCompanyMember(onSuccess?: () => void) {
  const action = useCallback(
    (input: { companyId: Id; userId: Id }) => adminApi.removeCompanyMember(input.companyId, input.userId),
    [],
  );
  return useApiMutation(action, { onSuccess: () => onSuccess?.() });
}

/** The four counters at the top of the console — one aggregate query, not
 * a client-side sum over a page of companies. */
export function usePlatformKpis(refreshKey = 0) {
  return useApiQuery(["platform-kpis", refreshKey], () => adminApi.getPlatformKpis());
}

export function useOnboardCompany(onSuccess?: (result: Awaited<ReturnType<typeof adminApi.onboardCompany>>) => void) {
  return useApiMutation(adminApi.onboardCompany, { onSuccess });
}

export function usePlatformUsers(companyId: Id | undefined, q?: string) {
  return useApiQuery(
    ["platform-users", companyId, q],
    () => adminApi.listPlatformUsers(companyId, q),
    { enabled: !!companyId },
  );
}

/** `refreshKey` is bumped by the console when something it did wrote an
 * audit row, so the feed re-reads as part of the query key rather than from
 * an effect that would race the first load. */
export function usePlatformActivity(limit = 100, companyId?: Id, refreshKey = 0) {
  return useApiQuery(
    ["platform-activity", limit, companyId, refreshKey],
    () => adminApi.listPlatformActivity(limit, companyId),
  );
}

/* ------------------------------------------------- Outgoing email / SMTP */

export function useEmailSettings() {
  return useApiQuery(["email-settings"], () => adminApi.getEmailSettings());
}

export function useSaveEmailSettings(onSuccess?: () => void) {
  return useApiMutation(adminApi.saveEmailSettings, { onSuccess: () => onSuccess?.() });
}

export function useSendTestEmail(onSuccess?: () => void) {
  const action = useCallback((toAddress?: string) => adminApi.sendTestEmail(toAddress), []);
  return useApiMutation(action, { onSuccess: () => onSuccess?.() });
}

export function useChangePassword(onSuccess?: () => void) {
  const action = useCallback(
    (input: { currentPassword: string; newPassword: string }) =>
      authApi.changePassword(input.currentPassword, input.newPassword),
    [],
  );
  return useApiMutation(action, { onSuccess: () => onSuccess?.() });
}

export function useUpdateMyProfile(onSuccess?: () => void) {
  return useApiMutation(authApi.updateMyProfile, { onSuccess: () => onSuccess?.() });
}

/* --------------------------------------------------------- Custom roles */

export function useCreateRole(onSuccess?: (role: { id: Id }) => void) {
  return useApiMutation(adminApi.createRole, { onSuccess });
}

export function useUpdateRole(roleId: Id, onSuccess?: () => void) {
  const action = useCallback(
    (patch: { name?: string; description?: string; permissions?: PermissionCode[] }) =>
      adminApi.updateRole(roleId, patch),
    [roleId],
  );
  return useApiMutation(action, { onSuccess: () => onSuccess?.() });
}

export function useRoleUsage(roleId: Id | undefined) {
  return useApiQuery(["role-usage", roleId], () => adminApi.getRoleUsage(roleId!), { enabled: !!roleId });
}

export function useDeleteRole(onSuccess?: () => void) {
  return useApiMutation(adminApi.deleteRole, { onSuccess: () => onSuccess?.() });
}

/* ----------------------------------------------------- Company pick-lists */

export function useCompanyLists(options: { activeOnly?: boolean } = {}) {
  return useApiQuery(["company-lists", !!options.activeOnly], () => adminApi.getCompanyLists(options));
}

/** The active values of one list, for a form's picker. */
export function useListValues(key: adminApi.CompanyListKey): string[] {
  const lists = useCompanyLists({ activeOnly: true });
  return lists.data?.find((l) => l.key === key)?.items.map((i) => i.value) ?? [];
}

export function useAddListItem(onSuccess?: () => void) {
  return useApiMutation(adminApi.addListItem, { onSuccess });
}

export function useUpdateListItem(onSuccess?: () => void) {
  return useApiMutation(adminApi.updateListItem, { onSuccess });
}

export function useDeleteListItem(onSuccess?: () => void) {
  return useApiMutation(adminApi.deleteListItem, { onSuccess });
}

/* ------------------------------------------------- Subscription plans */

export function usePlans() {
  return useApiQuery(["subscription-plans"], () => adminApi.listPlans());
}

export function useCreatePlan(onSuccess?: () => void) {
  return useApiMutation(adminApi.createPlan, { onSuccess });
}

export function useUpdatePlan(onSuccess?: () => void) {
  return useApiMutation(adminApi.updatePlan, { onSuccess });
}

export function useDeletePlan(onSuccess?: () => void) {
  return useApiMutation(adminApi.deletePlan, { onSuccess });
}
