# InventoryAI — Frontend Prototype

AI-powered inventory & procurement management for Indian wholesalers and distributors.

## Stack

- Next.js 16 (App Router) + React 19 + TypeScript
- Tailwind CSS v4 with CSS-variable design tokens
- shadcn/ui component conventions (Radix primitives + CVA)
- lucide-react icons, Recharts for charts
- Inter (self-hosted via `@fontsource-variable/inter`)

## Getting started

```bash
npm install
npm run dev
```

Open http://localhost:3000 — `/` redirects to `/login`.

Prototype sign-in accepts any valid email and a 6+ character password.
Use the password `wrongpass` to see the server-error state.

## Project structure

```
src/
  app/
    (auth)/login/        Screen 1 — Login
    dashboard/           Screen 2 — placeholder until approved
    globals.css          Design system: colours, typography, shadows, radii
  components/
    ui/                  shadcn/ui primitives (Button, Input, Card, Badge, …)
    common/              Cross-screen pieces (Logo, StatusBadge, illustrations)
    layout/              App shell (sidebar, header) — added with Screen 2
    auth/ dashboard/ products/ suppliers/ procurement/ inventory/ documents/ ai/
  lib/
    utils.ts             cn() class merger
    format.ts            Indian currency/number/date formatting, GSTIN/PAN regex
    design-tokens.ts     Token values for charts + layout constants
  services/              Mock API layer — swap `mockRequest` for `fetch` to hit FastAPI
  types/                 Shared domain types
```

## Design system

All colour, radius and shadow tokens live as CSS custom properties in
`src/app/globals.css` and are exposed to Tailwind through `@theme inline`.

| Purpose | Token |
| --- | --- |
| Primary action | `--primary` (blue) |
| Sidebar | `--sidebar` (dark navy) |
| Success / In Stock | `--success`, `--success-subtle` |
| Warning / Low Stock | `--warning`, `--warning-subtle` |
| Error / Out of Stock | `--destructive`, `--destructive-subtle` |
| AI-derived data | `--ai`, `--ai-subtle` (violet — AI only) |

Workflow and stock statuses render through a single component,
`components/common/status-badge.tsx`, so badge colours stay consistent
across every screen.

## Connecting the FastAPI backend

Every service call goes through `src/services/http.ts`. Replace the body of
`mockRequest` with a `fetch` against `API_BASE` and set
`NEXT_PUBLIC_API_BASE_URL` — call sites do not change.

## Screens

All 17 screens are built and reachable from the sidebar.

| # | Screen | Route |
| --- | --- | --- |
| 1 | Login | `/login` |
| 2 | Dashboard | `/dashboard` |
| 3 | Product / SKU Management | `/products`, `/products/[sku]` |
| 4 | Supplier Management | `/suppliers`, `/suppliers/[id]` |
| 5 | RFQ | `/procurement/rfq`, `/procurement/rfq/new` |
| 6 | AI Document Upload | `/ai-documents` |
| 7 | AI Extraction Review | `/ai-documents/review` |
| 8 | Quotation Comparison | `/procurement/comparison` |
| 9 | Purchase Order | `/procurement/purchase-orders`, `/procurement/purchase-orders/new` |
| 10 | Proforma Invoice | `/procurement/proforma` |
| 11 | Goods Receipt (GRN) | `/goods-receipt`, `/goods-receipt/new` |
| 12 | Current Inventory | `/inventory/current-stock`, `/inventory/by-godown` |
| 13 | Inventory Transactions | `/inventory/transactions` |
| 14 | Low Stock | `/inventory/low-stock` |
| 15 | AI Inventory Assistant | `/assistant` |
| 16 | Alerts | `/alerts` |
| 17 | Reports | `/reports` |

Plus `/godowns`, `/users` and `/settings`.

## Clickable flows

- RFQ → Send → Supplier Quotations → Compare → Create Purchase Order → Send → What's Next → Proforma / GRN
- AI Documents → upload → Review extraction → match the unmatched item → Approve → Comparison
- GRN → enter short quantity → mismatch detected → Confirm Receipt → inventory + transactions
- Dashboard / Low Stock → Create RFQ; Products → Product detail → Transactions

## AI provenance

`components/ai/ai-provenance.tsx` is the contract for AI UX:

- `ProvenanceTag` — AI Extracted · AI Suggested · Needs Review · User Approved · Calculated
- `ConfidenceMeter` — always a band and a label, never a bare number
- `AiField` — violet left rail for AI-derived values, amber for anything needing review
- `AiSuggestion` — inline Accept / Keep mine for free-text normalisation

Violet (`--ai`) is reserved for AI-derived data and is used nowhere else.
