"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import { ChevronDown, PanelLeftClose, PanelLeftOpen, X } from "lucide-react";

import { LogoMark } from "@/components/common/logo";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { NAV_SECTIONS, type NavBadges, type NavItem } from "@/components/layout/nav-config";
import { useNavBadges } from "@/hooks/use-ops";
import { useIsTenantUser, usePermissions } from "@/hooks/use-session";
import { GuardedLink } from "@/lib/unsaved-changes";
import { cn } from "@/lib/utils";

function NavBadge({ value, muted }: { value: number; muted?: boolean }) {
  return (
    <span
      className={cn(
        "ml-auto inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full px-1.5 text-[10.5px] font-semibold tabular",
        muted
          ? "bg-white/10 text-white/70"
          : "bg-warning/85 text-[oklch(0.26_0.05_70)]",
      )}
    >
      {value}
    </span>
  );
}

const itemBase =
  "group relative flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-[13.5px] font-medium transition-colors duration-150 outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring/60";
const itemIdle =
  "text-sidebar-foreground/78 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground";
const itemActive = "bg-sidebar-primary/18 text-white";

export function Sidebar({
  collapsed,
  onToggleCollapsed,
  mobileOpen,
  onCloseMobile,
}: {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}) {
  const pathname = usePathname();
  const { can } = usePermissions();
  // The badge counts come from company-level endpoints. A platform admin has
  // no company, so asking would 403 on every page — skip it for them, and
  // until the session has loaded (see `useIsTenantUser`).
  const badgeQuery = useNavBadges(useIsTenantUser());
  const badges: NavBadges = badgeQuery.data ?? {};

  /**
   * Nav is filtered by permission, so a role is never shown a destination it
   * cannot use. This is presentation only — the route itself is still
   * reachable, and the server is what refuses the data.
   */
  const sections = React.useMemo(
    () =>
      NAV_SECTIONS.map((section) => ({
        ...section,
        items: section.items
          .filter((item) => can(item.permission))
          .map((item) => ({
            ...item,
            children: item.children?.filter((child) => can(child.permission)),
          }))
          .filter((item) => !item.children || item.children.length > 0),
      })).filter((section) => section.items.length > 0),
    [can],
  );

  const badgeFor = React.useCallback(
    (key?: NavItem["badgeKey"]) => {
      if (!key) return undefined;
      const value = badges[key];
      return value && value > 0 ? value : undefined;
    },
    [badges],
  );

  const isActive = React.useCallback(
    (href?: string) => !!href && (pathname === href || pathname.startsWith(href + "/")),
    [pathname],
  );

  const groupIsActive = React.useCallback(
    (item: NavItem) => item.children?.some((c) => isActive(c.href)) ?? false,
    [isActive],
  );

  // Groups start open when they contain the current route.
  const [openGroups, setOpenGroups] = React.useState<Record<string, boolean>>({});
  const groupOpen = (item: NavItem) => openGroups[item.label] ?? groupIsActive(item);

  return (
    <>
      {/* Mobile scrim */}
      <div
        onClick={onCloseMobile}
        className={cn(
          "fixed inset-0 z-40 bg-foreground/40 backdrop-blur-[2px] transition-opacity lg:hidden",
          mobileOpen ? "opacity-100" : "pointer-events-none opacity-0",
        )}
        aria-hidden="true"
      />

      <aside
        data-collapsed={collapsed}
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex flex-col bg-sidebar transition-[width,transform] duration-200 ease-out",
          collapsed ? "w-16" : "w-[248px]",
          mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
        )}
      >
        {/* Brand */}
        <div
          className={cn(
            "flex h-15 shrink-0 items-center border-b border-sidebar-border",
            collapsed ? "justify-center px-2" : "gap-2.5 px-4",
          )}
        >
          <LogoMark className="size-8 shrink-0" />
          {!collapsed && (
            <span className="truncate text-[16px] font-semibold tracking-[-0.02em] text-white">
              InventoryAI
            </span>
          )}
          <button
            onClick={onCloseMobile}
            aria-label="Close menu"
            className="ml-auto rounded-md p-1.5 text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-white lg:hidden"
          >
            <X className="size-4" />
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-x-hidden overflow-y-auto px-2.5 py-3">
          {sections.map((section, index) => (
            <div key={section.title ?? index} className={cn(index > 0 && "mt-5")}>
              {section.title && !collapsed && (
                <p className="mb-1.5 px-2.5 text-[10.5px] font-semibold tracking-[0.08em] text-sidebar-muted/80 uppercase">
                  {section.title}
                </p>
              )}
              {section.title && collapsed && index > 0 && (
                <div className="mx-2 mb-2 h-px bg-sidebar-border" />
              )}

              <ul className="space-y-0.5">
                {section.items.map((item) => {
                  const Icon = item.icon;

                  /* ---------- Collapsed: group opens as a flyout ---------- */
                  if (collapsed && item.children) {
                    return (
                      <li key={item.label}>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <button
                              aria-label={item.label}
                              className={cn(
                                itemBase,
                                "justify-center px-0",
                                groupIsActive(item) ? itemActive : itemIdle,
                              )}
                            >
                              <Icon className="size-[18px] shrink-0" strokeWidth={1.9} />
                            </button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent side="right" align="start" className="min-w-[13rem]">
                            <DropdownMenuLabel>{item.label}</DropdownMenuLabel>
                            <DropdownMenuSeparator />
                            {item.children.map((child) => (
                              <DropdownMenuItem key={child.href} asChild>
                                <GuardedLink href={child.href}>
                                  <span>{child.label}</span>
                                  {badgeFor(child.badgeKey) != null && (
                                    <span className="ml-auto text-[11px] font-semibold text-warning-subtle-foreground tabular">
                                      {badgeFor(child.badgeKey)}
                                    </span>
                                  )}
                                </GuardedLink>
                              </DropdownMenuItem>
                            ))}
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </li>
                    );
                  }

                  /* ---------- Collapsed: plain link with tooltip ---------- */
                  if (collapsed) {
                    return (
                      <li key={item.label}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <GuardedLink
                              href={item.href!}
                              onClick={onCloseMobile}
                              className={cn(
                                itemBase,
                                "justify-center px-0",
                                isActive(item.href) ? itemActive : itemIdle,
                              )}
                            >
                              <Icon className="size-[18px] shrink-0" strokeWidth={1.9} />
                              {badgeFor(item.badgeKey) != null && (
                                <span className="absolute top-1 right-1 size-1.5 rounded-full bg-warning" />
                              )}
                            </GuardedLink>
                          </TooltipTrigger>
                          <TooltipContent side="right">{item.label}</TooltipContent>
                        </Tooltip>
                      </li>
                    );
                  }

                  /* ---------- Expanded: collapsible group ---------- */
                  if (item.children) {
                    const open = groupOpen(item);
                    return (
                      <li key={item.label}>
                        <button
                          aria-expanded={open}
                          onClick={() =>
                            setOpenGroups((prev) => ({ ...prev, [item.label]: !open }))
                          }
                          className={cn(
                            itemBase,
                            groupIsActive(item) && !open ? itemActive : itemIdle,
                          )}
                        >
                          <Icon className="size-[18px] shrink-0" strokeWidth={1.9} />
                          <span className="truncate">{item.label}</span>
                          <ChevronDown
                            className={cn(
                              "ml-auto size-3.5 shrink-0 text-sidebar-muted transition-transform duration-200",
                              open && "rotate-180",
                            )}
                          />
                        </button>

                        {open && (
                          <ul className="relative mt-0.5 ml-[19px] space-y-0.5 border-l border-sidebar-border pl-3">
                            {item.children.map((child) => (
                              <li key={child.href}>
                                <GuardedLink
                                  href={child.href}
                                  onClick={onCloseMobile}
                                  className={cn(
                                    "flex items-center gap-2 rounded-md px-2.5 py-1.5 text-[13px] transition-colors",
                                    isActive(child.href)
                                      ? "bg-sidebar-primary/18 font-medium text-white"
                                      : "text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-white",
                                  )}
                                >
                                  <span className="truncate">{child.label}</span>
                                  {badgeFor(child.badgeKey) != null && (
                                    <NavBadge
                                      value={badgeFor(child.badgeKey)!}
                                      muted={!isActive(child.href)}
                                    />
                                  )}
                                </GuardedLink>
                              </li>
                            ))}
                          </ul>
                        )}
                      </li>
                    );
                  }

                  /* ---------- Expanded: plain link ---------- */
                  return (
                    <li key={item.label}>
                      <GuardedLink
                        href={item.href!}
                        onClick={onCloseMobile}
                        className={cn(
                          itemBase,
                          isActive(item.href) ? itemActive : itemIdle,
                        )}
                      >
                        <Icon className="size-[18px] shrink-0" strokeWidth={1.9} />
                        <span className="truncate">{item.label}</span>
                        {badgeFor(item.badgeKey) != null && <NavBadge value={badgeFor(item.badgeKey)!} />}
                      </GuardedLink>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>

        {/* Collapse toggle */}
        <div className="shrink-0 border-t border-sidebar-border p-2.5">
          <button
            onClick={onToggleCollapsed}
            className={cn(
              itemBase,
              itemIdle,
              "hidden lg:flex",
              collapsed && "justify-center px-0",
            )}
          >
            {collapsed ? (
              <PanelLeftOpen className="size-[18px]" strokeWidth={1.9} />
            ) : (
              <>
                <PanelLeftClose className="size-[18px]" strokeWidth={1.9} />
                <span>Collapse</span>
              </>
            )}
          </button>
        </div>
      </aside>
    </>
  );
}
