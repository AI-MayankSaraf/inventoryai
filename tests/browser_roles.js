/**
 * Browser write-path test — defining, editing and deleting a custom role.
 *
 *   node browser_roles.js [http://localhost:3000]
 */
const { chromium } = require("playwright");

const BASE = process.argv[2] || "http://localhost:3000";
const API = process.env.API_URL || "http://127.0.0.1:8000";
const SFX = Math.random().toString(36).slice(2, 6).toUpperCase();
const ROLE_NAME = `Store Supervisor ${SFX}`;

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
  const [, auth] = await api("POST", "/auth/login", null, { email: "owner@acme-demo.test", password: "Demo@12345" });
  const token = auth.access_token;

  // Earlier E2E runs leave custom roles behind; a 30-row list makes this
  // test about scrolling rather than about roles.
  const [, existing] = await api("GET", "/roles", token);
  for (const role of existing.filter((r) => !r.is_system && r.user_count === 0)) {
    await api("DELETE", `/roles/${role.id}`, token);
  }

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
    await page.waitForFunction(() => !!localStorage.getItem("inventoryai.access_token.v1"), { timeout: 20000 });

    await page.goto(`${BASE}/roles`);
    await page.waitForSelector('button:has-text("New Role")', { timeout: 25000 });
    // The list itself arrives a beat later than the header button.
    await page.waitForSelector("text=Built-in", { timeout: 25000 });
    const listText = (await page.textContent("body")).replace(/\s+/g, " ");
    check("C01 the roles screen lists the built-ins as built-in",
          /Built-in/.test(listText) && /Owner/.test(listText), "");

    // ------------------------------------------------------- create
    await page.click('button:has-text("New Role")');
    await page.waitForSelector("#role-name", { timeout: 10000 });
    check("C02 Create is unavailable until the role has a name",
          await page.locator('[role="dialog"] button:has-text("Create Role")').isDisabled(), "");
    await page.fill("#role-name", ROLE_NAME);
    await page.click('button:has-text("Create Role")');
    await page.waitForSelector("text=/at least one thing this role may do/i", { timeout: 10000 });
    check("C02b …and a role with no permissions is refused", true);

    await page.fill("#role-description", "Receives stock at the gate");
    for (const code of ["grn.view", "grn.create", "inventory.view"]) {
      await page.locator(`[role="dialog"] button[aria-label="${code}"]`).click();
    }
    await page.click('button:has-text("Create Role")');
    await page.waitForSelector(`text=${ROLE_NAME}`, { timeout: 20000 });
    const [, roles] = await api("GET", "/roles", token);
    const created = roles.find((r) => r.name === ROLE_NAME);
    check("C03 the role reached the server with exactly the chosen permissions",
          !!created && created.is_system === false
            && JSON.stringify(created.permissions.sort()) === JSON.stringify(["grn.create", "grn.view", "inventory.view"]),
          created);

    // ------------------------------------------------------- edit
    const row = page.locator(`[data-testid="role-${created.code}"]`);
    await row.scrollIntoViewIfNeeded();
    await row.click();
    await page.waitForSelector(`button[aria-label="Edit ${ROLE_NAME}"]`, { timeout: 15000 });
    await page.click(`button[aria-label="Edit ${ROLE_NAME}"]`);
    await page.waitForSelector("#role-name", { timeout: 10000 });
    await page.locator('[role="dialog"] button[aria-label="supplier.view"]').click();
    await page.click('button:has-text("Save Role")');
    await page.waitForSelector('[role="dialog"]', { state: "detached", timeout: 20000 });
    const [, afterEdit] = await api("GET", `/roles/${created.id}`, token);
    check("C04 editing adds the permission server-side",
          afterEdit.permissions.includes("supplier.view"), afterEdit.permissions);

    // ------------------------------------------------------- guards
    const ownerRole = roles.find((r) => r.code === "owner");
    await page.locator('[data-testid="role-owner"]').click();
    await page.waitForTimeout(800);
    const builtInText = (await page.textContent("body")).replace(/\s+/g, " ");
    check("C05 a built-in role says it is fixed and offers no edit",
          /is a built-in role/.test(builtInText)
            && !(await page.isVisible(`button[aria-label="Edit ${ownerRole.name}"]`)), "");

    // ------------------------------------------------------- delete
    const rowAgain = page.locator(`[data-testid="role-${created.code}"]`);
    await rowAgain.scrollIntoViewIfNeeded();
    await rowAgain.click();
    await page.waitForSelector(`button[aria-label="Delete ${ROLE_NAME}"]`, { timeout: 15000 });
    await page.click(`button[aria-label="Delete ${ROLE_NAME}"]`);
    await page.locator('[role="dialog"] button:has-text("Delete role")').click();
    await page.waitForSelector('[role="dialog"]', { state: "detached", timeout: 20000 });
    const [, rolesAfter] = await api("GET", "/roles", token);
    check("C06 deleting it removes it everywhere", !rolesAfter.some((r) => r.name === ROLE_NAME),
          rolesAfter.map((r) => r.name));

    check("C07 no console errors during the whole run",
          consoleErrors.filter((e) => !/favicon|404 \(Not Found\)|status of 4\d\d/i.test(e)).length === 0,
          consoleErrors.slice(0, 3));
  } catch (err) {
    check("run completed without throwing", false, err && err.message);
    await page.screenshot({ path: "/tmp/browser-roles-failure.png", fullPage: true }).catch(() => {});
  } finally {
    await browser.close();
  }

  console.log(`\n${passed} passed, ${failed.length} failed`);
  failed.forEach((f) => console.log("  - " + f));
  process.exit(failed.length ? 1 : 0);
})();
