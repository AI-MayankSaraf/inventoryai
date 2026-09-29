/**
 * Presentation formatting: dates, identifiers, greetings.
 *
 * Money formatting lives in `lib/domain/money.ts` alongside the arithmetic
 * that produces it, so there is exactly one place that decides what a rupee
 * value looks like. The re-exports below keep the familiar names working.
 */

export {
  formatMoney as formatCurrencyValue,
  formatMoneyCompact,
  formatPercent,
  formatQuantity,
  formatVariancePct,
} from "@/lib/domain/money";

import { formatMoney, formatMoneyCompact } from "@/lib/domain/money";

/** ₹12,48,500 — pass `withPaise` for ₹12,48,500.00 */
export function formatCurrency(value: number, withPaise = false): string {
  return formatMoney(value, withPaise);
}

/** ₹12.49L / ₹1.25Cr — compact Indian units for KPI cards */
export function formatCompactINR(value: number): string {
  return formatMoneyCompact(value);
}

const number = new Intl.NumberFormat("en-IN");

/** 12,48,500 */
export function formatNumber(value: number): string {
  return number.format(value);
}

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/** 10 Jan 2026 */
export function formatDate(value: string | Date): string {
  const d = typeof value === "string" ? new Date(value) : value;
  return `${String(d.getDate()).padStart(2, "0")} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

/** 10-01-2026 (input-friendly Indian format) */
export function formatDateShort(value: string | Date): string {
  const d = typeof value === "string" ? new Date(value) : value;
  return d.toLocaleDateString("en-GB").replace(/\//g, "-");
}

/** 10 Jan 2026, 4:32 PM — for audit trails and other timestamped activity. */
export function formatDateTime(value: string | Date): string {
  const d = typeof value === "string" ? new Date(value) : value;
  const time = d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", hour12: true });
  return `${formatDate(d)}, ${time}`;
}

/** "3 minutes ago" / "2 hours ago" / "5 days ago" — falls back to formatDateTime beyond a week. */
export function formatRelativeTime(value: string | Date, now: Date = new Date()): string {
  const d = typeof value === "string" ? new Date(value) : value;
  const seconds = Math.max(0, Math.round((now.getTime() - d.getTime()) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days} day${days === 1 ? "" : "s"} ago`;
  return formatDateTime(d);
}

/** Good Morning / Good Afternoon / Good Evening */
export function greeting(now: Date = new Date()): string {
  const h = now.getHours();
  if (h < 12) return "Good Morning";
  if (h < 17) return "Good Afternoon";
  return "Good Evening";
}

/** 27AABCU9603R1ZM → 27AABCU9603R1ZM (validated shape only) */
export const GSTIN_REGEX =
  /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/;
export const PAN_REGEX = /^[A-Z]{5}[0-9]{4}[A-Z]{1}$/;
export const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
