/**
 * Browser write-path test — the AI document pipeline.
 *
 * The one thing only a browser can prove about this feature: that a real
 * file, dropped into the page by a person, comes back as a reviewable
 * extraction and ends as a quotation whose totals are the server's
 * arithmetic rather than the supplier's printed figures.
 *
 * Everything about *rules* — who may approve, what the ladder does, what
 * happens to a hostile document — is scripts/e2e_ai_documents.py's job.
 *
 *   node browser_ai_documents.js [http://localhost:3000]
 */
const { chromium } = require("playwright");

const BASE = process.argv[2] || "http://localhost:3000";
const API = process.env.API_URL || "http://127.0.0.1:8000";
const SFX = Math.random().toString(36).slice(2, 6).toUpperCase();
const NUMBER = `Q-BR-${SFX}`;

let passed = 0;
const failed = [];
function check(name, cond, info = "") {
  if (cond) { passed++; console.log("  ok   " + name); }
  else { failed.push(name); console.log("  FAIL " + name + "  -> " + String(info).slice(0, 300)); }
}

async function api(method, path, token, body) {
  const res = await fetch(API + path, {
    method,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: "Bearer " + token } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  return [res.status, text ? JSON.parse(text) : null];
}

(async () => {
  const [, auth] = await api("POST", "/auth/login", null, {
    email: "owner@acme-demo.test", password: "Demo@12345",
  });
  const token = auth.access_token;
  const [, variants] = await api("GET", "/catalog/variants?limit=2", token);
  const [, suppliers] = await api("GET", "/catalog/suppliers?limit=1", token);
  const supplier = suppliers[0];

  const [, products] = await api("GET", "/catalog/products?limit=200", token);
  const nameOf = (variantId) => {
    const v = variants.find((x) => x.id === variantId);
    const p = products.find((x) => x.id === (v && v.product_id));
    return (p && p.name) || (v && v.sku) || "";
  };

  // Printed amounts are wrong on purpose: 10 x 1450 is 14,500, not 99,999.
  // The quotation this becomes must disagree with the paper.
  const csv =
    `${supplier.name}\n` +
    "Plot 14, MIDC Industrial Area, Pune 411019\n" +
    "QUOTATION\n" +
    "\n" +
    `Quotation No: ${NUMBER}\n` +
    "Date: 12/09/2026\n" +
    "Valid Till: 12/10/2026\n" +
    "\n" +
    "Item Code,Description,HSN,Qty,UOM,Rate,GST %,Amount\n" +
    `${variants[0].sku},${nameOf(variants[0].id)},8517,10,Nos,1450.00,18,99999.00\n` +
    `,${nameOf(variants[1].id)} premium,8517,5,Nos,2200.00,18,11000.00\n` +
    "ZZ-999,Completely Unknown Gadget XL,8517,3,Nos,500.00,18,1500.00\n" +
    "Total,,,,,,,112499.00\n";

  const browser = await chromium.launch(process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {});
  const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));

  try {
    await page.goto(`${BASE}/login`);
    await page.fill("#email", "owner@acme-demo.test");
    await page.fill("#password", "Demo@12345");
    await page.click('button[type="submit"]');
    await page.waitForFunction(() => !!localStorage.getItem("inventoryai.access_token.v1"), { timeout: 20000 });

    await page.goto(`${BASE}/ai-documents`);
    // The input is deliberately `hidden` (the dropzone is the visible
    // control), so wait for it to exist rather than to be visible —
    // setInputFiles works on a hidden input, a real click would not.
    await page.waitForSelector('input[type="file"]', { state: "attached", timeout: 25000 });

    // ------------------------------------------------------------ upload
    await page.setInputFiles('input[type="file"]', {
      name: `browser-quote-${SFX}.csv`,
      mimeType: "text/csv",
      buffer: Buffer.from(csv),
    });
    // Uploading goes straight to the review screen, which shows the worker's
    // progress and then the extraction once the file has been read.
    await page.waitForURL(/\/ai-documents\/review\//, { timeout: 40000 });
    const documentId = page.url().split("/review/")[1];
    check("D01 dropping a file in the page uploads and lands on review", !!documentId, page.url());
    await page.waitForSelector("text=/Approve and create quotation/i", { timeout: 90000 });

    const [, doc] = await api("GET", `/ai/documents/${documentId}`, token);
    check("D02 the server read it: three items, not zero", doc.items_found === 3, doc);
    check("D03 …recognised the document type", doc.document_type === "supplier_quotation", doc.document_type);
    check("D04 …and the supplier from the letterhead", doc.supplier_id === supplier.id, doc);
    check("D05 …and it is waiting for review, not approved",
          doc.processing_status === "review_required", doc.processing_status);

    await page.waitForSelector("text=/Approve and create quotation/i", { timeout: 25000 });
    const screen = (await page.textContent("body")).replace(/\s+/g, " ");
    check("D06 the review screen shows the supplier's own quotation number",
          screen.includes(NUMBER), screen.slice(0, 200));
    check("D07 …and says the semantic rungs did not run, rather than implying a model read the file",
          /Semantic matching is off|Column mappings are proposed by header synonyms|matched by meaning \(suggestions only/i.test(screen), "");

    const approveDisabled = await page.locator('[data-testid="approve-extraction"]').isDisabled();
    check("D08 Approve is disabled while lines are unresolved", approveDisabled, "");

    // -------------------------------------------------- resolve the lines
    await page.locator('[data-testid="use-candidate-2"]').first().click();
    await page.waitForFunction(
      () => {
        const el = document.querySelector('[data-testid="skip-line-3"]');
        return !!el;
      },
      undefined,
      { timeout: 20000 },
    );
    const [, afterConfirm] = await api("GET", `/ai/documents/${documentId}/extraction`, token);
    check("D09 confirming a suggestion reaches the server",
          afterConfirm.lines[1].final_variant_id !== null, afterConfirm.lines[1]);
    check("D10 …and the screen re-read it rather than showing a stale view",
          (await page.textContent("body")).includes("Approve and create quotation"), "");

    await page.locator('[data-testid="skip-line-3"]').first().click();
    await page.waitForFunction(
      () => {
        const el = document.querySelector('[data-testid="approve-extraction"]');
        return el && !el.disabled;
      },
      undefined,
      { timeout: 20000 },
    );
    check("D11 skipping the unrecognised line unblocks Approve", true);

    const [, ready] = await api("GET", `/ai/documents/${documentId}/extraction`, token);
    check("D12 the server agrees it can be approved", ready.can_approve && !ready.blocking_reason, ready.blocking_reason);
    check("D13 the preview total is computed from the lines, not from the page",
          Math.abs(ready.totals.total - 30090) < 0.01, ready.totals);

    // ---------------------------------------------------------- approve
    await page.locator('[data-testid="approve-extraction"]').click();
    await page.waitForURL(/\/procurement\/quotations\//, { timeout: 30000 });
    const quotationId = page.url().split("/quotations/")[1].split(/[?#]/)[0];
    check("D14 approving lands on the quotation it created", !!quotationId, page.url());

    const [, quotation] = await api("GET", `/procurement/quotations/${quotationId}`, token);
    check("D15 the quotation carries the supplier's number", quotation.quotation_number === NUMBER, quotation);
    check("D16 …and only the lines that were settled", quotation.items.length === 2, quotation.items.length);
    check("D17 …with totals recomputed server-side (BR-AI-02)",
          Math.abs(Number(quotation.subtotal) - 25500) < 0.01
            && Math.abs(Number(quotation.total_amount) - 30090) < 0.01,
          { subtotal: quotation.subtotal, total: quotation.total_amount });
    check("D18 …disagreeing with the printed total, which was wrong",
          Math.abs(Number(quotation.total_amount) - 112499) > 1, quotation.total_amount);

    const [, approved] = await api("GET", `/ai/documents/${documentId}/extraction`, token);
    check("D19 the extraction records what it became",
          approved.review_status === "approved" && approved.promoted_to_id === quotationId, approved.review_status);

    // ----------------------------------------------------- the list view
    await page.goto(`${BASE}/ai-documents`);
    await page.waitForSelector(`text=browser-quote-${SFX}.csv`, { timeout: 25000 });
    const list = (await page.textContent("body")).replace(/\s+/g, " ");
    check("D20 the document list shows the file and its supplier",
          list.includes(`browser-quote-${SFX}.csv`) && list.includes(supplier.name), "");

    // -------------------------------------------------------- assistant
    await page.goto(`${BASE}/inventory`);
    await page.waitForLoadState("networkidle");
    const [, answer] = await api("POST", "/ai/assistant", token, { question: "what is my inventory worth?" });
    check("D21 the assistant answers from the database, and says which query it ran",
          answer.intent === "inventory_value" && /stock_balances/.test(answer.source), answer);

    const realErrors = consoleErrors.filter(
      (e) => !/favicon|Download the React DevTools|hydrat/i.test(e)
        && !/Failed to load resource: the server responded with a status of 40[134]/.test(e),
    );
    check("D22 no unexpected console errors along the way", realErrors.length === 0, realErrors.slice(0, 5));
  } finally {
    await browser.close();
  }

  console.log(`\n${passed} passed, ${failed.length} failed`);
  failed.forEach((f) => console.log("  - " + f));
  process.exit(failed.length ? 1 : 0);
})();
