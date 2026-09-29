/**
 * Opens every screen (lists, forms, details) and reports API or console errors.
 *
 *   node tests/browser_screen_walk.js [http://localhost:3000]
 */
const { chromium } = require("playwright");
const BASE = process.argv[2] || process.env.APP_URL || "http://localhost:3000";
const API = process.env.API_URL || "http://127.0.0.1:8000";
const PLATFORM_DB = process.env.TEST_PLATFORM_DATABASE_URL || "postgresql://inventoryai_platform:inventoryai_platform_dev@localhost/inventoryai";
const SHOTS = require("os").tmpdir();

async function api(path, token) {
  const r = await fetch(API + path, { headers: { Authorization: "Bearer " + token } });
  const j = await r.json();
  return Array.isArray(j) ? j : j.items || [];
}

async function run(name, email, pw, routes, browser, extraRoutes) {
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await ctx.newPage();
  let cur = "login";
  const out = {};
  const rec = (r) => (out[r] ??= { api: [], console: [] });
  page.on("response", (r) => {
    const u = r.url();
    if (u.includes(":8000") && r.status() >= 400 && !(r.status() === 404 && /favicon/.test(u)))
      rec(cur).api.push(r.status() + " " + r.request().method() + " " + u.replace(API, ""));
  });
  page.on("console", (m) => { if (m.type() === "error") rec(cur).console.push(m.text().slice(0, 220)); });
  page.on("pageerror", (e) => rec(cur).console.push("PAGEERROR " + String(e).slice(0, 220)));
  await page.goto(BASE + "/login", { waitUntil: "networkidle" });
  await page.fill("#email", email);
  await page.fill("#password", pw);
  await page.click('button[type="submit"]');
  await page.waitForURL((u) => !u.pathname.includes("/login"), { timeout: 20000 });
  await page.waitForFunction(() => !!localStorage.getItem("inventoryai.access_token.v1"));
  const token = await page.evaluate(() => localStorage.getItem("inventoryai.access_token.v1"));
  const all = routes.concat(extraRoutes ? await extraRoutes(token) : []);
  let problems = 0;
  for (const r of all) {
    cur = r;
    rec(r);
    try {
      await page.goto(BASE + r, { waitUntil: "networkidle", timeout: 30000 });
    } catch (e) {
      out[r].console.push("NAV " + e.message.slice(0, 100));
    }
    await page.waitForTimeout(700);
    const text = (await page.locator("main").first().innerText().catch(() => "")).replace(/\s+/g, " ");
    const shown = /something went wrong|failed to load|could not load|not found|coming soon|not been built|application error/i.test(text);
    const redirected = !page.url().replace(BASE, "").startsWith(r.split("?")[0]);
    const bad = out[r].api.length || out[r].console.length || shown || redirected;
    if (bad) problems++;
    console.log(`${bad ? "!!" : "ok"} ${r}${redirected ? "  -> redirected to " + page.url().replace(BASE, "") : ""}`);
    out[r].api.forEach((a) => console.log("     API " + a));
    out[r].console.forEach((c) => console.log("     CON " + c));
    if (shown) console.log("     TXT " + text.slice(0, 220));
  }
  console.log(`[${name}] ${all.length} screens, ${problems} with problems\n`);
  await ctx.close();
}

(async () => {
  const browser = await chromium.launch();
  const lists = ["/dashboard", "/products", "/suppliers", "/godowns", "/procurement/rfq", "/procurement/rfq/new",
    "/procurement/quotations", "/procurement/quotations/new", "/procurement/comparison", "/procurement/proforma",
    "/procurement/purchase-orders", "/procurement/purchase-orders/new", "/goods-receipt", "/goods-receipt/new",
    "/supplier-invoices", "/supplier-invoices/new", "/purchase-returns", "/purchase-returns/new",
    "/inventory/current-stock", "/inventory/by-godown", "/inventory/transactions", "/inventory/transfers",
    "/inventory/low-stock", "/ai-documents", "/schema-mappings", "/assistant", "/alerts", "/reports", "/users",
    "/roles", "/audit", "/settings", "/profile"];
  await run("OWNER", "owner@acme-demo.test", "Demo@12345", lists, browser, async (t) => {
    const first = async (p) => (await api(p + (p.includes("?") ? "&" : "?") + "limit=1", t))[0];
    const routes = [];
    const add = async (list, fmt) => { const x = await first(list); if (x) routes.push(fmt(x)); };
    await add("/procurement/rfqs", (x) => `/procurement/rfq/${x.id}`);
    await add("/procurement/quotations", (x) => `/procurement/quotations/${x.id}`);
    await add("/procurement/comparisons", (x) => `/procurement/comparison/${x.rfq_id}`);
    await add("/procurement/purchase-orders", (x) => `/procurement/purchase-orders/${x.id}`);
    await add("/proforma-invoices", (x) => `/procurement/proforma/${x.id}`);
    await add("/procurement/goods-receipts", (x) => `/goods-receipt/${x.id}`);
    await add("/supplier-invoices", (x) => `/supplier-invoices/${x.id}`);
    await add("/purchase-returns", (x) => `/purchase-returns/${x.id}`);
    await add("/catalog/suppliers", (x) => `/suppliers/${x.id}`);
    await add("/catalog/variants", (x) => `/products/${x.id}`);
    await add("/ai/documents", (x) => `/ai-documents/review/${x.id}`);
    await add("/ai/schema-mappings", (x) => `/schema-mappings/${x.id}`);
    return routes;
  });
  await run("PLATFORM", "platform-admin@inventoryai.test", "Platform@12345", ["/system-admin", "/profile"], browser);
  // Supplier portal: public login page only (see report — it is mock-backed).
  const p = await browser.newPage();
  const errs = [];
  p.on("pageerror", (e) => errs.push(String(e)));
  await p.goto(BASE + "/supplier-portal/login", { waitUntil: "networkidle" });
  console.log(`${errs.length ? "!!" : "ok"} /supplier-portal/login ${errs.join(" ")}`);
  await browser.close();
})().catch((e) => { console.error("FATAL", e); process.exit(1); });
