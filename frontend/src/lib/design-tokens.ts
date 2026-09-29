/**
 * Design tokens mirrored in TypeScript.
 * The source of truth is `src/app/globals.css` (CSS custom properties).
 * These are here for chart libraries and any JS that needs raw values.
 */

export const chartColors = {
  primary: "var(--chart-1)",
  success: "var(--chart-2)",
  warning: "var(--chart-3)",
  danger: "var(--chart-4)",
  ai: "var(--chart-5)",
} as const;

export const chartSeries = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

/** Application spacing rhythm (px) — keep layouts on this scale. */
export const spacing = {
  page: 24,
  section: 20,
  card: 20,
  field: 14,
  inline: 8,
} as const;

/** Layout constants used by the app shell. */
export const layout = {
  sidebarWidth: 248,
  sidebarCollapsedWidth: 64,
  headerHeight: 60,
  contentMaxWidth: 1600,
} as const;
