/**
 * Browser write-path test — supplier contacts, unit conversions, per-godown
 * reorder levels, and the read-only panels around them.
 *
 *   node browser_supplier_catalogue.js [http://localhost:3000]
 *
 * Always use localhost (not 127.0.0.1): the dev server's allowedDevOrigins
 * check otherwise blocks hydration.
 */
const { chromium } = require("playwright");

const BASE = process.argv[2] || "http://localhost:3000";
const API = "http://127.0.0.1:8000";
const SFX = Math.random().toString(36).slice(2, 7).toUpperCase();

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
  const [, supplier] = await api("POST", "/catalog/suppliers", token, {
    name: `Browser Supplier ${SFX}`, supplier_type: "Distributor", gst_treatment: "unregistered",
    city: "Pune", state_code: "27", state_name: "Maharashtra",
  });
  const [, product] = await api("POST", "/catalog/products", token, { name: `Browser Item ${SFX}`, base_uom_id: nos, hsn_code: "8471", gst_rate: 18 });
  const [, variant] = await api("POST", "/catalog/variants", token, {
    product_id: product.id, sku: `BRW-${SFX}`, uom_id: nos, purchase_price: 100, sale_price: 140, mrp: 160,
    reorder_point: 10, reorder_qty: 40,
  });

  const browser = await chromium.launch(process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {});
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));
  if (process.env.TRACE) page.on("response", (r) => { if (r.url().includes(":8000") && r.status() >= 400) console.log("   ", r.status(), r.request().method(), r.url().replace("http://127.0.0.1:8000", "")); });

  try {
    // ------------------------------------------------------------ login
    await page.goto(`${BASE}/login`);
    await page.fill("#email", "owner@acme-demo.test");
    await page.fill("#password", "Demo@12345");
    await page.click('button[type="submit"]');
    await page.waitForURL((u) => !u.pathname.includes("/login"), { timeout: 20000 });
    // The login form stores its tokens just after the redirect — navigating
    // in the same tick loses them and every later call 401s.
    await page.waitForFunction(() => !!localStorage.getItem("inventoryai.access_token.v1"), { timeout: 15000 });
    check("W01 signed in", !page.url().includes("/login"), page.url());

    // -------------------------------------------------- supplier detail
    await page.goto(`${BASE}/suppliers/${supplier.id}`);
    await page.waitForSelector("text=No contacts yet", { timeout: 20000 });
    check("W02 supplier detail opens with an empty contacts card", true);

    await page.click('[data-testid="add-contact"]');
    await page.fill("#ct-name", "Meera Shah");
    await page.fill("#ct-designation", "Sales Head");
    await page.fill("#ct-phone", "9820011111");
    await page.fill("#ct-email", `meera.${SFX.toLowerCase()}@browser.test`);
    await page.click('button:has-text("Add Contact")');
    await page.waitForSelector('[data-testid="supplier-contact"]', { timeout: 15000 });
    const firstRow = await page.textContent('[data-testid="supplier-contact"]');
    check("W03 contact added and shown as primary", /Meera Shah/.test(firstRow) && /Primary/.test(firstRow), firstRow);
    const [, saved] = await api("GET", `/catalog/suppliers/${supplier.id}/contacts`, token);
    check("W04 the write really hit the API", saved.length === 1 && saved[0].name === "Meera Shah" && saved[0].is_primary, saved);

    await page.click('button[aria-label="Edit Meera Shah"]');
    await page.fill("#ct-designation", "Director");
    await page.click('button:has-text("Save Changes")');
    await page.waitForSelector("text=Director", { timeout: 15000 });
    check("W05 contact edit refreshes the card without a reload", true);

    // Invalid input comes back from the server as a field error.
    await page.click('[data-testid="add-contact"]');
    await page.fill("#ct-name", "Broken");
    await page.fill("#ct-email", "not-an-email");
    await page.click('button:has-text("Add Contact")');
    await page.waitForSelector("text=/valid email/i", { timeout: 10000 });
    check("W06 a bad email is refused with a field error", true);
    await page.keyboard.press("Escape");

    await page.click('button[aria-label="Remove Meera Shah"]');
    await page.click('button:has-text("Remove")');
    await page.waitForSelector("text=No contacts yet", { timeout: 15000 });
    const [, after] = await api("GET", `/catalog/suppliers/${supplier.id}/contacts`, token);
    check("W07 contact removed here and on the server", after.length === 0, after);

    const pageText = await page.textContent("body");
    check("W08 performance panel renders real (zero) figures for a new supplier", /On-time delivery/.test(pageText) && /Open variances/.test(pageText), "");

    // --------------------------------------------------- product detail
    await page.goto(`${BASE}/products/${variant.id}`);
    await page.waitForSelector("text=Unit Conversions", { timeout: 20000 });
    check("W09 product detail shows the new panels", /Reorder Levels by Godown/.test(await page.textContent("body")), "");

    await page.click('[data-testid="add-conversion"]');
    await page.click("#cv-unit");
    await page.click('[role="option"]:has-text("Box")');
    await page.fill("#cv-factor", "12");
    await page.click('button:has-text("Add Conversion")');
    await page.waitForSelector('[data-testid="uom-conversion"]', { timeout: 15000 });
    const convText = await page.textContent('[data-testid="uom-conversion"]');
    check("W10 conversion added: 1 Box = 12 Nos", /1 Box = 12 Nos/.test(convText.replace(/\s+/g, " ")), convText);
    const [, convs] = await api("GET", `/catalog/variants/${variant.id}/uom-conversions`, token);
    check("W11 conversion persisted, as the purchase default", convs.length === 1 && convs[0].is_purchase_default, convs);

    await page.click('[data-testid="edit-godown-levels"]');
    await page.waitForSelector("text=Reorder levels by godown", { timeout: 10000 });
    const firstGodownInput = page.locator('input[aria-label$="reorder point"]').first();
    const godownLabel = (await firstGodownInput.getAttribute("aria-label")).replace(" reorder point", "");
    await firstGodownInput.fill("25");
    await page.locator('input[aria-label$="reorder quantity"]').first().fill("75");
    await page.click('button:has-text("Save Levels")');
    await page.waitForSelector('[data-testid="godown-level"]', { timeout: 15000 });
    const levelText = (await page.textContent('[data-testid="godown-level"]')).replace(/\s+/g, " ");
    check("W12 per-godown level saved and listed", levelText.includes(godownLabel) && /Reorder at 25/.test(levelText), levelText);
    const [, policies] = await api("GET", `/catalog/variants/${variant.id}/godown-policies`, token);
    check("W13 level persisted server-side", policies.length === 1 && Number(policies[0].reorder_point) === 25 && Number(policies[0].reorder_qty) === 75, policies);

    await page.click('button[aria-label="Remove Box conversion"]');
    await page.click('button:has-text("Remove")');
    await page.waitForSelector("text=No conversions", { timeout: 15000 });
    const [, convs2] = await api("GET", `/catalog/variants/${variant.id}/uom-conversions`, token);
    check("W14 conversion removed here and on the server", convs2.length === 0, convs2);

    check("W15 no console errors during the whole run", consoleErrors.filter((e) => !/favicon|404 \(Not Found\)/i.test(e)).length === 0, consoleErrors.slice(0, 3));
  } catch (err) {
    check("run completed without throwing", false, err && err.message);
    await page.screenshot({ path: "/tmp/browser-failure.png", fullPage: true }).catch(() => {});
  } finally {
    await browser.close();
  }

  console.log(`\n${passed} passed, ${failed.length} failed`);
  failed.forEach((f) => console.log("  - " + f));
  process.exit(failed.length ? 1 : 0);
})();
