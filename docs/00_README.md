# InventoryAI — Backend Architecture Documentation

Reverse-engineered from the existing Next.js frontend prototype (audited 14 Sep 2026), reconciled with the business workflow and with production database design practice.

**Status:** design only. No frontend file was modified. No backend code was written. Nothing here is implemented until you approve it.

---

## Read in this order

| # | Document | What it answers | Read it if you are… |
|---|---|---|---|
| **01** | `01_UI_AUDIT.md` | What exists today: 34 routes, every screen, field, enum, calculation, and what is faked | …anyone starting on this project |
| **02** | `02_DATABASE_DESIGN.md` | The PostgreSQL schema — 60+ tables with full column specs, the inventory ledger, the procurement chain, GST, indexes, constraints, soft-delete policy | …writing migrations |
| **03** | `03_DATABASE_ERD.md` | The same schema as Mermaid diagrams, by domain, plus cardinalities | …trying to picture it |
| **04** | `04_API_SPECIFICATION.md` | ~135 endpoints, conventions, and detailed specs for the 23 that carry real risk | …building FastAPI routers |
| **05** | `05_UI_API_MAPPING.md` | Screen → endpoint map, mock-service cutover table, and 10 workflow sequence diagrams | …wiring the frontend to the backend |
| **06** | `06_BUSINESS_RULES.md` | ~90 numbered rules, state machines, audit requirements, tenant-isolation checklist | …writing service-layer logic |
| **07** | `07_RBAC_MATRIX.md` | Roles, permission codes, the full matrix, godown scoping, enforcement design | …implementing auth |
| **08** | `08_AI_DATA_MODEL.md` | AI jobs, extraction, review, schema mapping, the SKU-match ladder, guardrails, cost control | …building the AI pipeline |
| **09** | `09_GAPS_AND_RECOMMENDATIONS.md` | 14 critical findings, 20 important ones, missing screens, sequencing plan, final architecture, quality-check verification | **…deciding what to do next — start here if you only read one** |

---

## The five-minute version

**What the prototype does well:** the domain language is right (godown, RFQ, GRN, proforma), the AI provenance model is thoughtful (per-field confidence, `ai_extracted → needs_review → user_approved`, approval blocked while a line is unmatched), the GRN discrepancy vocabulary matches real Indian wholesale practice, the tax engine is close to correct, and the document print conventions are sensible.

**What is fundamentally broken:** stock is static data — confirming a Goods Receipt posts nothing, and the Product form edits stock directly. Money is computed in the browser by two different formulas. Access control is three client-side `if` statements. Document numbers are `max + 1` in `localStorage`. The Supplier Invoice module does not exist. Rejected goods have nowhere to go.

**What that means:** the backend is not "adding persistence behind the UI". It is moving the system of record from the browser to the database, and the schema in `02` is designed for that, not for mirroring the prototype's shape.

**Five decisions needed from you before work starts** — see `09 §10`: product/variant split, batch tracking in the Phase 1 schema, Supplier Invoice in Phase 1, PO approval policy, and what to do about the `reserved` field.

---

## Conventions used throughout

- 🔴 marks a rule the current prototype violates
- ⊕ marks an endpoint backing a UI control that is decorative today
- ⊗ marks an endpoint with no UI at all
- **MUST HAVE / RECOMMENDED / OPTIONAL / FUTURE** priorities on every entity in `02 §2`
- Rule ids (`BR-GRN-06`) are referenced from the API spec and are intended to appear in API error responses
