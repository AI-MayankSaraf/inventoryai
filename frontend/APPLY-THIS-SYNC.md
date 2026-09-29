# Applying this sync

The frontend correction phase replaced a whole layer, so files were **deleted** as well as added. A file-by-file copy would leave the old ones behind and the build would fail. Replace the `src` folder wholesale instead.

## Steps

1. Back up your current folder (one command, from `D:\E\Sharad Docs\inventoryai\frontend`):

   ```
   ren src src-before-correction
   ```

2. Extract `inventoryai-frontend-src.tar.gz` into that same folder. It contains a single top-level `src/` directory, so you should end up with `D:\E\Sharad Docs\inventoryai\frontend\src`.

   With 7-Zip, Windows tar, or:
   ```
   tar -xzf inventoryai-frontend-src.tar.gz
   ```

3. Install and build:

   ```
   npm install
   npx tsc --noEmit      → expect 0 errors
   npm run build         → expect 38 routes
   npm run dev
   ```

4. Sign in with `owner@acme-demo.test` / `Demo@12345`, or `platform-admin@inventoryai.test` / `Platform@12345` for the platform console.

5. Once it builds, delete `src-before-correction`.

## What was removed (and must not come back)

- `src/data/` — 10 static-data files
- `src/services/` — 7 files
- `src/lib/record-store.ts`, `po-store.ts`, `rfq-store.ts`, `grn-store.ts`, `product-store.ts`, `supplier-store.ts`, `quotation-store.ts`, `transaction-store.ts`, `godown-store.ts`, `team-store.ts`, `tax.ts`, `audit-log.ts`

## One thing to know on first run

The mock database lives in a single `localStorage` key. If you had the old prototype open in the same browser, clear site data once so the new seed loads cleanly.
