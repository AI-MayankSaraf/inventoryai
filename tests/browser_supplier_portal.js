/**
 * Supplier Portal in the browser: grant, email link, set password, dashboard, revoke.
 *
 *   node tests/browser_supplier_portal.js [http://localhost:3000]
 */
const { chromium } = require("playwright");
const BASE = process.argv[2] || process.env.APP_URL || "http://localhost:3000";
const API = process.env.API_URL || "http://127.0.0.1:8000";
const PLATFORM_DB = process.env.TEST_PLATFORM_DATABASE_URL || "postgresql://inventoryai_platform:inventoryai_platform_dev@localhost/inventoryai";
const SHOTS = require("os").tmpdir();
const { execSync } = require("child_process");
const path = require("path");
const DIR = SHOTS;
const T = Math.random().toString(36).slice(2, 7);
const EMAIL = `portal.${T}@supplier.example`;
let passed = 0; const failed = [];
const check = (n, c, i = "") => { if (c) { passed++; console.log("  ok   " + n); } else { failed.push(n); console.log("  FAIL " + n + " -> " + String(i).slice(0, 300)); } };
const psql = (sql) => execSync(`psql "${PLATFORM_DB}" -At -c "${sql}"`).toString().trim();

(async () => {
  // The flow-test supplier: has an RFQ, a quotation and a sent PO.
  const supplierId = psql("select s.id from suppliers s where exists (select 1 from rfq_suppliers r where r.supplier_id=s.id) and exists (select 1 from supplier_quotations q where q.supplier_id=s.id) and exists (select 1 from purchase_orders p where p.supplier_id=s.id and p.status in ('sent','partially_received','received','closed')) limit 1");
  const browser = await chromium.launch();
  const staff = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errs = [];
  for (const p of [staff]) { p.on("pageerror", (e) => errs.push(String(e))); p.on("console", (m) => { if (m.type() === "error") errs.push(m.text()); }); }
  try {
    await staff.goto(BASE + "/login");
    await staff.fill("#email", "owner@acme-demo.test");
    await staff.fill("#password", "Demo@12345");
    await staff.click('button[type="submit"]');
    await staff.waitForURL((u) => !u.pathname.includes("/login"));
    await staff.waitForFunction(() => !!localStorage.getItem("inventoryai.access_token.v1"));

    // ---- staff: give access from the supplier screen
    await staff.goto(`${BASE}/suppliers/${supplierId}`);
    await staff.waitForSelector('[data-testid="portal-access-card"]', { timeout: 20000 });
    await staff.click('[data-testid="portal-grant"]');
    await staff.fill("#portal-name", "Meena Iyer");
    await staff.fill("#portal-email", EMAIL);
    await staff.click('button:has-text("Send invitation")');
    await staff.waitForSelector(`text=Invitation sent to ${EMAIL}`, { timeout: 15000 });
    check("S1 staff give access from the supplier screen", true);
    // The list refetches after the toast; wait for the new row, not a fixed delay.
    await staff
      .waitForFunction(
        () => /Waiting for password/.test(document.querySelector('[data-testid="portal-access-card"]')?.textContent || ""),
        null,
        { timeout: 15000 },
      )
      .catch(() => {});
    const card = (await staff.textContent('[data-testid="portal-access-card"]')).replace(/\s+/g, " ");
    check("S2 card shows the contact waiting for a password", /Meena Iyer/.test(card) && /Waiting for password/.test(card), card.slice(0, 200));
    await staff.locator('[data-testid="portal-access-card"]').screenshot({ path: path.join(DIR, "portal-card.png") });

    // ---- supplier: open the emailed link, set password
    await new Promise((r) => setTimeout(r, 1500));
    const body = psql(`select body_preview from outbound_messages where to_address='${EMAIL}' order by queued_at desc limit 1`);
    const link = (body.match(/https?:\/\/\S+set-password\?token=[A-Za-z0-9_\-]+/) || [])[0];
    check("E1 invitation email carries a portal link", !!link, body);
    const sup = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    sup.on("pageerror", (e) => errs.push(String(e)));
    await sup.goto(link.replace(/^https?:\/\/[^/]+/, BASE));
    await sup.fill("#sp-password", "Portal@2026x");
    await sup.fill("#sp-confirm", "Portal@2026x");
    await sup.click('button:has-text("Set password")');
    await sup.waitForSelector('[data-testid="portal-password-set"]', { timeout: 15000 });
    check("E2 supplier sets their password from the link", true);

    // ---- supplier: sign in, see their documents
    await sup.click("text=Go to Supplier Portal sign-in");
    await sup.waitForURL(/supplier-portal\/login/);
    const loginText = await sup.textContent("body");
    check("L0 no prototype demo login any more", !/Prototype demo login/i.test(loginText));
    await sup.fill("#supplier-email", EMAIL);
    await sup.fill("#supplier-password", "Portal@2026x");
    await sup.click('button[type="submit"]');
    await sup.waitForURL(/supplier-portal\/dashboard/, { timeout: 20000 });
    await sup.waitForSelector("text=RFQs sent to you");
    await sup.waitForTimeout(1500);
    const dash = (await sup.textContent("body")).replace(/\s+/g, " ");
    check("L1 dashboard names the company and who they are there", /Working with Acme Trading Co/.test(dash) && /Meena Iyer/.test(dash), dash.slice(0, 300));
    check("L2 real RFQ, quotation and PO numbers are shown", /RFQ-2026-27-\d+/.test(dash) && /PO-2026-27-\d+/.test(dash) && /Your quotations/.test(dash), dash.slice(0, 600));
    check("L3 prototype notice is gone", !/UI prototype|mock data/i.test(dash));
    await sup.screenshot({ path: path.join(DIR, "portal-dashboard.png") });

    // ---- staff revoke; supplier loses it
    await staff.reload();
    await staff.waitForSelector('[data-testid="portal-access-row"]');
    const row = staff.locator('[data-testid="portal-access-row"]', { hasText: EMAIL });
    const rowText = (await row.textContent()).replace(/\s+/g, " ");
    check("R0 staff now see the contact as active", /Active/.test(rowText), rowText);
    await row.locator('button:has-text("Revoke")').click();
    await staff.locator('[role="dialog"] button:has-text("Revoke access")').click();
    await staff.waitForSelector("text=Access revoked", { timeout: 15000 });
    check("R1 staff revoke access", true);
    await sup.reload();
    await sup.waitForTimeout(2500);
    const after = (await sup.textContent("body")).replace(/\s+/g, " ");
    check("R2 supplier no longer sees the company", !/PO-2026-27-\d+/.test(after), after.slice(0, 300));
    check("X1 no page errors", errs.filter((e) => !/Failed to load resource/.test(e)).length === 0, errs.slice(0, 3));
  } catch (e) {
    check("run completed", false, e.message);
  } finally {
    await browser.close();
  }
  console.log(`\n${passed} passed, ${failed.length} failed`, failed);
  process.exit(failed.length ? 1 : 0);
})();
