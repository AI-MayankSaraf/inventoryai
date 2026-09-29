/**
 * Godown in-charge/capacity, document-number previews, purchase register.
 *
 *   node tests/browser_godowns_numbering_register.js [http://localhost:3000]
 */
const { chromium } = require("playwright");
const BASE = process.argv[2] || process.env.APP_URL || "http://localhost:3000";
const API = process.env.API_URL || "http://127.0.0.1:8000";
const PLATFORM_DB = process.env.TEST_PLATFORM_DATABASE_URL || "postgresql://inventoryai_platform:inventoryai_platform_dev@localhost/inventoryai";
const SHOTS = require("os").tmpdir();
const T = Math.random().toString(36).slice(2, 6).toUpperCase();
let passed = 0; const failed = [];
const check = (n, c, i = "") => { if (c) { passed++; console.log("  ok   " + n); } else { failed.push(n); console.log("  FAIL " + n + " -> " + String(i).slice(0, 300)); } };

async function pick(page, trigger, text) {
  await trigger.click();
  await page.locator('[role="option"]', { hasText: text }).first().click();
}

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errs = [];
  page.on("pageerror", (e) => errs.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") errs.push(m.text()); });
  try {
    await page.goto(BASE + "/login");
    await page.fill("#email", "owner@acme-demo.test");
    await page.fill("#password", "Demo@12345");
    await page.click('button[type="submit"]');
    await page.waitForURL((u) => !u.pathname.includes("/login"));
    await page.waitForFunction(() => !!localStorage.getItem("inventoryai.access_token.v1"));
    const token = await page.evaluate(() => localStorage.getItem("inventoryai.access_token.v1"));
    const api = async (m, p, body) => {
      const r = await fetch(API + p, { method: m, headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
      return [r.status, await r.json().catch(() => null)];
    };

    // ------------------------------------------------ godown in-charge + capacity
    await page.goto(BASE + "/godowns");
    await page.click('button:has-text("Add Godown")');
    await page.fill("#gd-name", `Cold Store ${T}`);
    await page.fill("#gd-city", "Indore");
    await pick(page, page.locator('[role="dialog"] button[role="combobox"]').first(), "Madhya Pradesh");
    await pick(page, page.locator("#gd-incharge"), "Demo Owner");
    await page.fill("#gd-capacity", "5000");
    await pick(page, page.locator("#gd-capacity-unit"), "Kilogram");
    await page.locator('[role="dialog"] button:has-text("Add Godown"), [role="dialog"] button:has-text("Save")').last().click();
    await page.waitForSelector(`text=Cold Store ${T}`, { timeout: 15000 });
    await page.reload();
    await page.waitForSelector(`text=Cold Store ${T}`, { timeout: 15000 });
    const card = (await page.locator("div", { hasText: `Cold Store ${T}` }).last().textContent()).replace(/\s+/g, " ");
    const body = (await page.textContent("body")).replace(/\s+/g, " ");
    const seg = body.slice(body.indexOf(`Cold Store ${T}`), body.indexOf(`Cold Store ${T}`) + 200);
    check("G1 in-charge survives a reload", /In-charge Demo Owner/.test(seg), seg);
    check("G2 capacity survives a reload", /Capacity 5,000 Kg/.test(seg), seg);
    const [, gds] = await api("GET", "/catalog/godowns?limit=500");
    const gd = gds.find((g) => g.name === `Cold Store ${T}`);
    check("G3 stored server-side", gd && gd.capacity_value === 5000 && !!gd.incharge_user_id, gd);
    const [s404] = await api("PATCH", `/catalog/godowns/${gd.id}`, { incharge_user_id: "00000000-0000-0000-0000-000000000001" });
    check("G4 in-charge from outside the company refused (422)", s404 === 422, s404);
    const [sHalf] = await api("PATCH", `/catalog/godowns/${gd.id}`, { capacity_value: 10 });
    check("G5 capacity without a unit refused (422)", sHalf === 422, sHalf);

    // ------------------------------------------------ numbering previews
    const [, seqs] = await api("GET", "/company/document-sequences");
    const po = seqs.filter((s) => s.doc_type === "po").sort((a, b) => b.financial_year.localeCompare(a.financial_year))[0];
    const expected = po.prefix + String(po.next_number).padStart(po.padding, "0");
    await page.goto(BASE + "/procurement/purchase-orders/new");
    await page.waitForFunction(() => /PO-/.test(document.querySelector("#po-number")?.value || ""), null, { timeout: 15000 });
    const shown = await page.inputValue("#po-number");
    check("N1 PO form previews the real next number (not …-00001)", shown === expected, `${shown} vs ${expected}`);
    const [, sups] = await api("GET", "/catalog/suppliers?limit=1");
    const [, vars] = await api("GET", "/catalog/variants?limit=1");
    const [, uoms] = await api("GET", "/catalog/uoms-available");
    const [sPo, newPo] = await api("POST", "/procurement/purchase-orders", {
      supplier_id: (sups.items || sups)[0].id, delivery_godown_id: gds.find((g) => g.is_default).id,
      items: [{ product_variant_id: (vars.items || vars)[0].id, quantity: 1, uom_id: uoms.find((u) => u.code === "Nos").id, unit_price: 10, gst_rate: 18 }],
    });
    check("N2 the next PO saved gets exactly the previewed number", sPo === 201 && newPo.po_number === expected, `${newPo && newPo.po_number} vs ${expected}`);
    for (const [path, sel] of [["/procurement/rfq/new", "#rfq-number"], ["/goods-receipt/new", "#grn-number"], ["/purchase-returns/new", "#return-number"]]) {
      await page.goto(BASE + path);
      await page.waitForSelector(sel, { timeout: 15000 });
      await page.waitForFunction((s) => (document.querySelector(s)?.value || "…") !== "…", sel, { timeout: 15000 }).catch(() => {});
      const v = await page.inputValue(sel);
      check(`N3 ${path} preview is real (${v})`, /-\d{4}-\d{2}-\d+$/.test(v) || v === "Assigned on save", v);
    }

    // ------------------------------------------------ purchase register
    await page.goto(BASE + "/reports");
    await page.click("text=Purchase Register");
    await page.waitForSelector("text=Supplier invoice", { timeout: 20000 });
    const rep = (await page.textContent("body")).replace(/\s+/g, " ");
    check("R1 register lists supplier invoices", /Supplier invoice/.test(rep));
    check("R2 …and goods receipts", /Goods receipt/.test(rep));
    check("X1 no page errors", errs.filter((e) => !/Failed to load resource/.test(e)).length === 0, errs.slice(0, 3));
  } catch (e) {
    check("run completed", false, e.message);
    await page.screenshot({ path: require("path").join(SHOTS, "gaps-failure.png") });
  } finally {
    await browser.close();
  }
  console.log(`\n${passed} passed, ${failed.length} failed`, failed);
})();
