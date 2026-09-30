/**
 * Company lists, subscription plans, record dates and the other things that
 * used to be fixed in the frontend: payment/delivery terms and supplier
 * types from Settings > Lists, plans from the platform console, assistant
 * suggestions from the backend, PO notes, GRN cancellation reason, the full
 * list of states.
 *
 *   node tests/browser_lists_plans_records.js [http://localhost:3000]
 */
const { chromium } = require("playwright");
const BASE = process.argv[2] || process.env.APP_URL || "http://localhost:3000";
const API = process.env.API_URL || "http://127.0.0.1:8000";
const SHOTS = require("os").tmpdir();
const T = Math.random().toString(36).slice(2, 6).toUpperCase();
let passed = 0; const failed = [];
const check = (n, c, i = "") => { if (c) { passed++; console.log("  ok   " + n); } else { failed.push(n); console.log("  FAIL " + n + " -> " + String(i).slice(0, 300)); } };

async function login(page, email, password) {
  await page.goto(BASE + "/login");
  await page.fill("#email", email);
  await page.fill("#password", password);
  await page.click('button[type="submit"]');
  await page.waitForURL((u) => !u.pathname.includes("/login"));
  await page.waitForFunction(() => !!localStorage.getItem("inventoryai.access_token.v1"));
  // Let the landing page finish its first requests (including any token
  // refresh) before the test navigates away.
  await page.waitForLoadState("networkidle");
  const token = await page.evaluate(() => localStorage.getItem("inventoryai.access_token.v1"));
  return async (m, p, body) => {
    const r = await fetch(API + p, { method: m, headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    return [r.status, await r.json().catch(() => null)];
  };
}

async function optionTexts(page, trigger) {
  await page.locator(trigger).click();
  await page.waitForSelector('[role="option"]');
  const texts = await page.locator('[role="option"]').allTextContents();
  await page.keyboard.press("Escape");
  return texts.map((t) => t.trim());
}

(async () => {
  const browser = await chromium.launch(process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {});
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errs = [];
  page.on("pageerror", (e) => errs.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") errs.push(m.text()); });
  try {
    const api = await login(page, "owner@acme-demo.test", "Demo@12345");

    // ------------------------------------------------ Settings > Lists
    const term = `60 Days ${T}`;
    await page.goto(BASE + "/settings");
    const card = page.locator('[data-testid="company-lists-card"]');
    await card.waitFor({ timeout: 20000 });
    await card.locator('input[aria-label="New value for Payment terms"]').fill(term);
    await card.locator('button:has-text("Add")').click();
    await card.locator(`text=${term}`).waitFor({ timeout: 10000 });
    check("S1 a payment term added in Settings shows in the list", true);

    await page.goto(BASE + "/procurement/purchase-orders/new");
    await page.waitForSelector("#po-payment");
    let terms = await optionTexts(page, "#po-payment");
    check("S2 ...and is offered on the PO form", terms.includes(term), terms);
    const deliveries = await optionTexts(page, "#po-delivery-terms");
    check("S3 PO delivery terms come from the list", deliveries.includes("FOR") && deliveries.includes("Ex-Works"), deliveries);

    const [, lists] = await api("GET", "/company/lists?key=payment_terms");
    const added = lists[0].items.find((i) => i.value === term);
    await api("PATCH", `/company/lists/${added.id}`, { is_active: false });
    await page.reload();
    await page.waitForSelector("#po-payment");
    terms = await optionTexts(page, "#po-payment");
    check("S4 switched off in Settings -> no longer offered", !terms.includes(term), terms);
    await api("DELETE", `/company/lists/${added.id}`);

    // supplier types
    const type = `Wholesaler ${T}`;
    await api("POST", "/company/lists", { list_key: "supplier_type", value: type });
    await page.goto(BASE + "/suppliers");
    await page.locator('button:has-text("Add Supplier")').first().click();
    await page.waitForSelector("#sf-type");
    const types = await optionTexts(page, "#sf-type");
    check("S5 supplier types come from the list (custom value included)", types.includes(type) && types.includes("Importer"), types);
    const supplierTerms = await optionTexts(page, "#sf-payment-terms");
    check("S6 supplier payment terms are a pick-list", supplierTerms.includes("30 Days"), supplierTerms);
    await page.keyboard.press("Escape");
    const [, tl] = await api("GET", "/company/lists?key=supplier_type");
    await api("DELETE", `/company/lists/${tl[0].items.find((i) => i.value === type).id}`);

    // every state on the company profile
    await page.goto(BASE + "/settings");
    await page.waitForSelector("#s-state");
    const states = await optionTexts(page, "#s-state");
    check("S7 Settings offers every state (e.g. Kerala, Assam, Ladakh)", ["Kerala", "Assam", "Ladakh"].every((s) => states.includes(s)) && states.length >= 38, states.length);
    const account = (await page.textContent("body")).replace(/\s+/g, " ");
    check("S8 company profile shows plan and owner", /\w+ plan · Owner owner@acme-demo\.test · Customer since/.test(account),
      account.match(/.{0,40}plan ·.{0,80}/));

    // ------------------------------------------------ PO notes + record dates
    const [, sups] = await api("GET", "/catalog/suppliers?limit=1");
    const [, vars] = await api("GET", "/catalog/variants?limit=1");
    const [, uoms] = await api("GET", "/catalog/uoms-available");
    const [, gds] = await api("GET", "/catalog/godowns?limit=100");
    const note = `Deliver before Diwali ${T}`;
    const [sPo, po] = await api("POST", "/procurement/purchase-orders", {
      supplier_id: (sups.items || sups)[0].id, delivery_godown_id: gds.find((g) => g.is_default).id, notes: note,
      items: [{ product_variant_id: (vars.items || vars)[0].id, quantity: 1, uom_id: uoms.find((u) => u.code === "Nos").id, unit_price: 10, gst_rate: 18 }],
    });
    check("R1 PO saved with notes", sPo === 201 && po.notes === note, po);
    await api("POST", `/procurement/purchase-orders/${po.id}/cancel`, { reason: `Test cancel ${T}` });
    await page.goto(BASE + `/procurement/purchase-orders/${po.id}`);
    await page.waitForSelector(`text=${note}`, { timeout: 20000 });
    const poText = (await page.textContent("body")).replace(/\s+/g, " ");
    check("R2 PO detail shows notes, created, last updated", poText.includes(note) && /Created/.test(poText) && /Last Updated/.test(poText), poText.slice(0, 200));
    check("R3 PO detail shows who cancelled it", /Cancelled\s*\d.{0,40}by Demo Owner/.test(poText), poText.match(/Cancelled\s*\d.{0,80}/));

    // ------------------------------------------------ GRN cancellation reason
    const [sG, grn] = await api("POST", "/procurement/goods-receipts", {
      supplier_id: (sups.items || sups)[0].id, godown_id: gds.find((g) => g.is_default).id,
      items: [{ product_variant_id: (vars.items || vars)[0].id, received_quantity: 1, accepted_quantity: 1, uom_id: uoms.find((u) => u.code === "Nos").id }],
    });
    const reason = `Truck turned back ${T}`;
    const [sC, cancelled] = await api("POST", `/procurement/goods-receipts/${grn.id}/cancel`, { reason });
    check("G1 draft GRN cancel stores the reason", sG === 201 && sC === 200 && cancelled.cancellation_reason === reason, cancelled);
    await page.goto(BASE + `/goods-receipt/${grn.id}`);
    await page.waitForSelector(`text=${reason}`, { timeout: 20000 });
    const grnText = (await page.textContent("body")).replace(/\s+/g, " ");
    check("G2 GRN detail shows reason and who cancelled", grnText.includes(reason) && /by Demo Owner/.test(grnText));

    // ------------------------------------------------ assistant suggestions
    await page.goto(BASE + "/assistant");
    await page.waitForSelector("text=What is low on stock?", { timeout: 20000 });
    const [, sug] = await api("GET", "/ai/assistant/suggestions");
    const chips = await page.locator("button.rounded-full").allTextContents();
    check("A1 assistant chips are the backend's suggestions", sug.every((s) => chips.includes(s.question)), chips);
    await page.locator('button:has-text("What is low on stock?")').click();
    await page.waitForSelector("text=at or below the reorder point", { timeout: 20000 });
    check("A2 'What is low on stock?' gets a real answer", true);
    await page.locator('button:has-text("Are there any unresolved variances?")').click();
    await page.waitForSelector("text=unresolved variance", { timeout: 20000 });
    check("A3 'Are there any unresolved variances?' gets a real answer", true);

    // ------------------------------------------------ platform plans
    const plat = await login(page, "platform-admin@inventoryai.test", "Platform@12345");
    const plan = `Scale ${T}`;
    await page.goto(BASE + "/system-admin");
    await page.locator('[role="tab"]:has-text("Plans")').click();
    await page.fill('input[aria-label="New plan name"]', plan);
    await page.locator('button:has-text("Add plan")').click();
    await page.locator(`[data-testid="plans-table"] >> text=${plan}`).waitFor({ timeout: 10000 });
    check("P1 plan added in the console", true);
    await page.locator('[role="tab"]:has-text("Companies")').click();
    await page.locator('[data-testid="onboard-company"]').click();
    await page.waitForSelector("#onb-plan");
    const onbPlans = await optionTexts(page, "#onb-plan");
    check("P2 new plan offered when onboarding", onbPlans.includes(plan) && onbPlans.includes("Trial"), onbPlans);
    await page.keyboard.press("Escape");
    const [, plans] = await plat("GET", "/platform/plans");
    const [sDel] = await plat("DELETE", `/platform/plans/${plans.find((p) => p.name === plan).id}`);
    check("P3 unused plan deleted", sDel === 204, sDel);

    check("X1 no page errors", errs.filter((e) => !/Failed to load resource/.test(e)).length === 0, errs.slice(0, 3));
  } catch (e) {
    check("run completed", false, e.message);
    await page.screenshot({ path: require("path").join(SHOTS, "lists-plans-failure.png") });
  } finally {
    await browser.close();
  }
  console.log(`\n${passed} passed, ${failed.length} failed`, failed);
  process.exit(failed.length ? 1 : 0);
})();
