/**
 * Browser write-path test — the Platform System Admin console.
 *
 * Exercises the two things that only a browser can prove: that onboarding a
 * tenant through the dialog produces a real, working company on the server,
 * and that an impersonation round trip actually swaps the session and puts
 * it back. Everything else about the console (who may call what) is the job
 * of scripts/e2e_platform.py.
 *
 *   node browser_platform.js [http://localhost:3000]
 */
const { chromium } = require("playwright");

const BASE = process.argv[2] || "http://localhost:3000";
const API = process.env.API_URL || "http://127.0.0.1:8000";
const SFX = Math.random().toString(36).slice(2, 6).toLowerCase();
const COMPANY = `Browser Traders ${SFX.toUpperCase()}`;
const OWNER_EMAIL = `browser.plat.${SFX}@browser.test`;

const PLATFORM_EMAIL = "platform-admin@inventoryai.test";
const PLATFORM_PASSWORD = "Platform@12345";

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
    email: PLATFORM_EMAIL, password: PLATFORM_PASSWORD,
  });
  const token = auth.access_token;

  const browser = await chromium.launch(process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {});
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));

  try {
    await page.goto(`${BASE}/login`);
    await page.fill("#email", PLATFORM_EMAIL);
    await page.fill("#password", PLATFORM_PASSWORD);
    await page.click('button[type="submit"]');
    // The token lands a beat after the redirect; navigating before it does
    // leaves every request on the next screen unauthenticated.
    await page.waitForFunction(() => !!localStorage.getItem("inventoryai.access_token.v1"), { timeout: 20000 });

    await page.goto(`${BASE}/system-admin`);
    await page.waitForSelector('[data-testid="system-admin-screen"]', { timeout: 25000 });
    await page.waitForSelector('[data-testid="onboard-company"]', { timeout: 25000 });

    // ------------------------------------------------------------- KPIs
    const [, kpis] = await api("GET", "/platform/kpis", token);
    await page.waitForFunction(
      (n) => document.body.innerText.includes(String(n)),
      kpis.companies,
      { timeout: 15000 },
    );
    const headText = (await page.textContent("body")).replace(/\s+/g, " ");
    check("P01 the console renders the server's KPIs, not a client-side sum",
          headText.includes(String(kpis.companies)) && headText.includes(String(kpis.users)),
          { companies: kpis.companies, users: kpis.users });
    check("P02 the demo tenant is listed", /Acme Trading Co/.test(headText), "");

    // -------------------------------------------------------- onboarding
    await page.click('[data-testid="onboard-company"]');
    await page.waitForSelector('[data-testid="onboard-name"]', { timeout: 10000 });

    await page.click('[data-testid="onboard-submit"]');
    await page.waitForSelector("text=/Enter the company's name/i", { timeout: 10000 });
    check("P03 an empty form is refused client-side, before a request goes out", true);

    await page.fill('[data-testid="onboard-name"]', COMPANY);
    await page.click('[data-testid="onboard-state"]');
    await page.click('[role="option"]:has-text("Karnataka")');
    await page.fill("#onb-city", "Bengaluru");
    await page.fill('[data-testid="onboard-owner-name"]', "Browser Owner");
    await page.fill('[data-testid="onboard-owner-email"]', "not-an-email");
    await page.click('[data-testid="onboard-submit"]');
    await page.waitForSelector("text=/doesn't look like an email address/i", { timeout: 10000 });
    check("P04 …and so is a malformed owner email", true);

    await page.fill('[data-testid="onboard-owner-email"]', OWNER_EMAIL);
    await page.click('[data-testid="onboard-submit"]');
    await page.waitForSelector('[data-testid="onboard-invite-token"]', { timeout: 20000 });
    check("P05 the dialog reports the invite rather than a password", true);

    const [, companies] = await api("GET", `/platform/companies?q=${SFX.toUpperCase()}`, token);
    const created = companies.find((c) => c.name === COMPANY);
    check("P06 the company really exists on the server", !!created, companies);
    check("P07 …on the state the dialog chose", created && created.state_code === "29", created);
    check("P08 …with the pending Owner attached, not a blank owner",
          created && created.owner_email === OWNER_EMAIL, created);
    check("P09 …and no users yet, because the Owner has only been invited",
          created && created.user_count === 0, created);

    const inviteLink = await page.inputValue('[data-testid="onboard-invite-token"]');
    const inviteToken = inviteLink.split("token=")[1];
    check("P10 the development invite link carries a token", !!inviteToken && inviteToken.length > 20, inviteLink);

    await page.click('[role="dialog"] button:has-text("Done")');
    await page.waitForSelector(`text=${COMPANY}`, { timeout: 20000 });
    check("P11 the new tenant appears in the table without a reload", true);

    // ----------------------------------------------------- suspend / reactivate
    const row = page.locator(`[data-testid="company-status-${created.id}"]`);
    await row.scrollIntoViewIfNeeded();
    await row.click();
    await page.waitForSelector("#suspend-reason", { timeout: 10000 });
    check("P12 suspending asks for a reason before it will proceed",
          await page.locator(`[data-testid="company-status-confirm-${created.id}"]`).isDisabled(), "");
    await page.fill("#suspend-reason", "Browser test — payment overdue");
    await page.click(`[data-testid="company-status-confirm-${created.id}"]`);
    await page.waitForFunction(
      (id) => {
        const el = document.querySelector(`[data-testid="company-status-${id}"]`);
        return el && /Reactivate/i.test(el.textContent || "");
      },
      created.id,
      { timeout: 20000 },
    );
    const [, afterSuspend] = await api("GET", `/platform/companies/${created.id}`, token);
    check("P13 the suspension reached the server with its reason",
          afterSuspend.status === "suspended" && /payment overdue/i.test(afterSuspend.suspended_reason || ""),
          afterSuspend);

    await page.click(`[data-testid="company-status-${created.id}"]`);
    await page.waitForSelector('[role="dialog"] :text("Reactivate")', { timeout: 10000 });
    await page.click(`[data-testid="company-status-confirm-${created.id}"]`);
    await page.waitForFunction(
      (id) => {
        const el = document.querySelector(`[data-testid="company-status-${id}"]`);
        return el && /Suspend/i.test(el.textContent || "");
      },
      created.id,
      { timeout: 20000 },
    );
    const [, afterReactivate] = await api("GET", `/platform/companies/${created.id}`, token);
    check("P14 reactivating clears both the status and the reason",
          afterReactivate.status === "active" && !afterReactivate.suspended_reason, afterReactivate);

    // -------------------------------------------------- impersonation round trip
    await page.click('button[role="tab"]:has-text("Impersonate")');
    await page.waitForSelector('[data-testid="impersonate-company"]', { timeout: 15000 });
    await page.click('[data-testid="impersonate-company"]');
    await page.click('[role="option"]:has-text("Acme Trading Co")');
    await page.waitForSelector('[data-testid="impersonate-owner@acme-demo.test"]', { timeout: 20000 });
    const pickerText = (await page.textContent("body")).replace(/\s+/g, " ");
    check("P15 the picker lists the tenant's users", /owner@acme-demo\.test/.test(pickerText), "");
    check("P16 …and never the platform admin, who cannot be impersonated",
          !pickerText.includes(PLATFORM_EMAIL), "");

    await page.click('[data-testid="impersonate-owner@acme-demo.test"]');
    await page.waitForSelector("#imp-reason", { timeout: 10000 });
    check("P17 impersonating is blocked until a reason is given",
          await page.locator('[data-testid="impersonate-confirm"]').isDisabled(), "");
    await page.fill("#imp-reason", `Browser test ${SFX} — checking a support ticket`);
    await page.click('[data-testid="impersonate-confirm"]');
    await page.waitForURL(/\/dashboard/, { timeout: 25000 });

    const impersonationToken = await page.evaluate(() => localStorage.getItem("inventoryai.access_token.v1"));
    const [meStatus, me] = await api("GET", "/auth/me", impersonationToken);
    check("P18 the browser now holds the target's session", meStatus === 200 && me.email === "owner@acme-demo.test", me);
    const [consoleStatus] = await api("GET", "/platform/kpis", impersonationToken);
    check("P19 …which cannot reach the platform console", consoleStatus === 403, consoleStatus);

    await page.waitForSelector("text=/Return to Super Admin/i", { timeout: 20000 });
    const banner = (await page.textContent("body")).replace(/\s+/g, " ");
    check("P20 the banner says whose session this is and who is accountable for it",
          /Viewing as Demo Owner/.test(banner) && /Acme Trading Co/.test(banner)
            && /logged against Platform Admin/.test(banner),
          banner.slice(0, 200));

    // Stopping through the UI, not the API: the point is that the admin's
    // own token comes back, which only the browser flow does.
    await page.click('button:has-text("Return to Super Admin")');
    await page.waitForURL(/\/system-admin/, { timeout: 25000 });
    await page.waitForFunction(
      (impToken) => localStorage.getItem("inventoryai.access_token.v1") !== impToken,
      impersonationToken,
      { timeout: 20000 },
    );
    const restored = await page.evaluate(() => localStorage.getItem("inventoryai.access_token.v1"));
    const [restoredStatus] = await api("GET", "/platform/kpis", restored);
    check("P21 stopping puts the platform admin's own token back", restoredStatus === 200, restoredStatus);
    const [deadStatus] = await api("GET", "/auth/me", impersonationToken);
    check("P22 …and the impersonation token dies on the very next request", deadStatus === 401, deadStatus);
    await page.waitForSelector('[data-testid="onboard-company"]', { timeout: 25000 });
    check("P23 …landing back on the console, not a dead screen", true);

    // ---------------------------------------------------------- activity
    const [, feed] = await api("GET", "/platform/activity?limit=50", token);
    check("P24 onboarding and suspension are in the cross-tenant feed",
          feed.some((r) => r.entity_label === COMPANY && r.action === "created")
            && feed.some((r) => r.entity_label === COMPANY && r.action === "suspended"),
          feed.slice(0, 3));
    check("P25 the impersonated session is in the feed, stamped",
          feed.some((r) => /Browser test/.test(r.description || "") && r.action === "impersonated"),
          feed.filter((r) => r.action === "impersonated").slice(0, 2));

    // Two sources of expected noise, both deliberate rather than broken:
    // P19 asks the console for a 403 on purpose, and stopping an
    // impersonation swaps the token while the dashboard is still mounted,
    // so its in-flight tenant queries land on the platform admin's token.
    // Anything that is not a failed HTTP response is a real script error.
    const realErrors = consoleErrors.filter(
      (e) => !/favicon|Download the React DevTools|hydrat/i.test(e)
        && !/Failed to load resource: the server responded with a status of 40[13]/.test(e),
    );
    check("P26 no unexpected console errors along the way", realErrors.length === 0, realErrors.slice(0, 5));
  } finally {
    await browser.close();
  }

  console.log(`\n${passed} passed, ${failed.length} failed`);
  failed.forEach((f) => console.log("  - " + f));
  process.exit(failed.length ? 1 : 0);
})();
