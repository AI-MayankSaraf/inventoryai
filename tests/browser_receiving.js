/**
 * Browser write-path test — editing a draft goods receipt, and the detail
 * panels a confirmation fills in (postings, variances, reversal).
 *
 *   node browser_receiving.js [http://localhost:3000]
 *
 * Always use localhost (not 127.0.0.1): the dev server's allowedDevOrigins
 * check otherwise blocks hydration.
 */
const { chromium } = require("playwright");

const BASE = process.argv[2] || "http://localhost:3000";
const API = process.env.API_URL || "http://127.0.0.1:8000";
const SFX = Math.random().toString(36).slice(2, 7).toUpperCase();
const TODAY = new Date().toISOString().slice(0, 10);

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
  // ---------------------------------------------------------- fixtures
  const [, auth] = await api("POST", "/auth/login", null, { email: "owner@acme-demo.test", password: "Demo@12345" });
  const token = auth.access_token;
  const [, uoms] = await api("GET", "/catalog/uoms-available", token);
  const nos = uoms.find((u) => u.code === "Nos").id;
  const [, godowns] = await api("GET", "/catalog/godowns?limit=5", token);
  const godown = godowns[0].id;
  const [, supplier] = await api("POST", "/catalog/suppliers", token, {
    name: `Browser Recv ${SFX}`, supplier_type: "Distributor", gst_treatment: "unregistered",
    city: "Pune", state_code: "27", state_name: "Maharashtra",
  });
  const [, product] = await api("POST", "/catalog/products", token, { name: `Recv Item ${SFX}`, base_uom_id: nos, hsn_code: "8471", gst_rate: 18 });
  const [, variant] = await api("POST", "/catalog/variants", token, {
    product_id: product.id, sku: `RCV-${SFX}`, uom_id: nos, purchase_price: 100, sale_price: 140, mrp: 160,
  });
  const [, po] = await api("POST", "/procurement/purchase-orders", token, {
    supplier_id: supplier.id, delivery_godown_id: godown, expected_delivery_date: TODAY,
    items: [{ product_variant_id: variant.id, quantity: 10, uom_id: nos, unit_price: 100, gst_rate: 18 }],
  });
  await api("POST", `/procurement/purchase-orders/${po.id}/submit`, token);
  await api("POST", `/procurement/purchase-orders/${po.id}/approve`, token);
  const [, poFull] = await api("GET", `/procurement/purchase-orders/${po.id}`, token);
  const [, grn] = await api("POST", "/procurement/goods-receipts", token, {
    supplier_id: supplier.id, purchase_order_id: po.id, godown_id: godown, grn_date: TODAY,
    items: [{ purchase_order_item_id: poFull.items[0].id, product_variant_id: variant.id,
              received_quantity: 4, accepted_quantity: 4, uom_id: nos }],
  });

  const browser = await chromium.launch(process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {});
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));

  try {
    await page.goto(`${BASE}/login`);
    await page.fill("#email", "owner@acme-demo.test");
    await page.fill("#password", "Demo@12345");
    await page.click('button[type="submit"]');
    await page.waitForURL((u) => !u.pathname.includes("/login"), { timeout: 20000 });
    // The login form stores its tokens just after the redirect — navigating
    // in the same tick loses them and every later call 401s.
    await page.waitForFunction(() => !!localStorage.getItem("inventoryai.access_token.v1"), { timeout: 15000 });
    check("R01 signed in", true);

    // ------------------------------------------------- draft detail
    await page.goto(`${BASE}/goods-receipt/${grn.id}`);
    await page.waitForSelector("text=Receipt Details", { timeout: 20000 });
    const draftText = (await page.textContent("body")).replace(/\s+/g, " ");
    check("R02 a draft shows its lines as not posted", /Not posted/.test(draftText), "");
    check("R03 a draft offers Edit Draft", await page.isVisible('a[href$="/edit"]'), "");

    // ----------------------------------------------------- the edit
    await page.click('a[href$="/edit"]');
    await page.waitForSelector("text=Edit Goods Receipt", { timeout: 20000 });
    // The form seeds itself from the draft once it loads.
    await page.waitForFunction(
      (n) => document.querySelector("#grn-number")?.value === n,
      grn.grn_number,
      { timeout: 20000 },
    );
    const poField = await page.inputValue("#grn-po");
    check("R04 the edit form is seeded from the draft (PO + GRN number)",
          poField === poFull.po_number && (await page.inputValue("#grn-number")) === grn.grn_number,
          { poField, number: await page.inputValue("#grn-number") });

    await page.fill("#grn-vehicle", `MH99${SFX}`).catch(() => {});
    const qtyInput = page.locator('input[type="number"]').first();
    await qtyInput.fill("6");
    await qtyInput.blur();
    const accepted = page.locator('input[type="number"]').nth(1);
    await accepted.fill("6");
    await accepted.blur();
    // 6 of 10 pending marks the line short, and BR-GRN-05 then wants a note.
    const noteBox = page.locator(`input[aria-label="Remarks for RCV-${SFX}"]`).first();
    await noteBox.waitFor({ timeout: 10000 });
    check("R04b a short line asks for a note rather than calling it optional",
          (await noteBox.getAttribute("placeholder")) === "Required — what happened?",
          await noteBox.getAttribute("placeholder"));
    await noteBox.fill("Balance due next week");
    await page.click('button:has-text("Save Changes")');
    await page.waitForURL((u) => u.pathname === `/goods-receipt/${grn.id}`, { timeout: 20000 });
    check("R05 saving returns to the receipt", true);

    const [, afterEdit] = await api("GET", `/procurement/goods-receipts/${grn.id}`, token);
    check("R06 the edit reached the server (4 → 6, version bumped)",
          afterEdit.items[0].received_quantity === 6 && afterEdit.row_version > grn.row_version, afterEdit.items[0]);

    // A second save from the stale page must be refused, not silently win.
    const [staleStatus] = await api("PATCH", `/procurement/goods-receipts/${grn.id}`, token, {
      grn_date: TODAY, godown_id: godown, row_version: grn.row_version,
      items: [{ purchase_order_item_id: poFull.items[0].id, product_variant_id: variant.id,
                received_quantity: 9, accepted_quantity: 9, uom_id: nos }],
    });
    check("R07 a stale save is refused (409)", staleStatus === 409, staleStatus);

    // ------------------------------------------------- confirm + panels
    await page.reload();
    await page.waitForSelector('button:has-text("Confirm Receipt")', { timeout: 20000 });
    // The header button opens the confirm dialog; the dialog's own button
    // (the last one on the page) actually confirms.
    await page.locator('button:has-text("Confirm Receipt")').first().click();
    await page.locator('[role="dialog"] button:has-text("Confirm Receipt")').click();
    await page.waitForSelector("text=Receipt confirmed", { timeout: 20000 });
    const confirmedText = (await page.textContent("body")).replace(/\s+/g, " ");
    check("R08 the confirmation panel lists the real posting", /Inventory postings/i.test(confirmedText) && /\+6/.test(confirmedText), "");
    check("R09 the PO's new progress is shown", /is now 60% received|is now 60/.test(confirmedText), confirmedText.match(/is now [^.]{0,20}/));
    check("R10 the short delivery was recorded as a variance",
          /Variances recorded against the PO/i.test(confirmedText) && /less than what was ordered/i.test(confirmedText), "");

    await page.reload();
    await page.waitForSelector("text=Stock Postings", { timeout: 20000 });
    const postedText = (await page.textContent("body")).replace(/\s+/g, " ");
    check("R11 the receipt now shows its ledger row and no longer offers Edit",
          /Stock Postings/.test(postedText) && !(await page.isVisible('a[href$="/edit"]')), "");
    check("R12 the variances panel is on the receipt itself", /Differences flagged against the purchase order/i.test(postedText), "");

    // ---------------------------------------------------- reversal
    await page.click('button:has-text("Reverse")');
    await page.fill("#grn-reverse-reason", "Counted wrong at the gate").catch(async () => {
      await page.fill("textarea", "Counted wrong at the gate");
    });
    await page.click('button:has-text("Reverse Receipt")').catch(() => page.click('button:has-text("Reverse")'));
    await page.waitForSelector("text=This receipt was reversed", { timeout: 20000 });
    const reversedText = (await page.textContent("body")).replace(/\s+/g, " ");
    check("R13 the reversal banner names who, when and why",
          /Counted wrong at the gate/.test(reversedText) && /Demo Owner/.test(reversedText), reversedText.match(/This receipt was reversed[^.]{0,120}/));
    check("R14 the offsetting ledger row is on the same receipt", /Reversal/.test(reversedText) && /-6/.test(reversedText), "");

    check("R15 no console errors during the whole run",
          consoleErrors.filter((e) => !/favicon|404 \(Not Found\)|Failed to load resource: the server responded with a status of 409/i.test(e)).length === 0,
          consoleErrors.slice(0, 3));
  } catch (err) {
    check("run completed without throwing", false, err && err.message);
    await page.screenshot({ path: "/tmp/browser-receiving-failure.png", fullPage: true }).catch(() => {});
  } finally {
    await browser.close();
  }

  console.log(`\n${passed} passed, ${failed.length} failed`);
  failed.forEach((f) => console.log("  - " + f));
  process.exit(failed.length ? 1 : 0);
})();
