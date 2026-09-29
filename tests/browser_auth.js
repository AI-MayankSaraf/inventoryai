/**
 * Browser write-path test — the auth gaps: forgot/reset password, the
 * email settings panel, and changing your own password.
 *
 *   node tests/browser_auth.js [http://localhost:3000]
 */
const { chromium } = require("playwright");

// Owner-role connection for the direct reads/writes below: TEST_DATABASE_URL,
// else backend/.env's DATABASE_URL without the +asyncpg driver suffix.
function ownerDbUrl() {
  if (process.env.TEST_DATABASE_URL) return process.env.TEST_DATABASE_URL;
  const envFile = require("path").join(__dirname, "..", "backend", ".env");
  const line = require("fs").readFileSync(envFile, "utf8").split(/\r?\n/).find((l) => l.startsWith("DATABASE_URL="));
  if (!line) throw new Error("Set TEST_DATABASE_URL, or DATABASE_URL in backend/.env");
  return line.slice("DATABASE_URL=".length).trim().replace("+asyncpg", "");
}
const DB_URL = ownerDbUrl();

const BASE = process.argv[2] || process.env.APP_URL || "http://localhost:3000";
const API = process.env.API_URL || "http://127.0.0.1:8000";
const SFX = Math.random().toString(36).slice(2, 7).toLowerCase();
const EMAIL = `browser.auth.${SFX}@acme-demo.test`;

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

/** Reads the emailed link out of `outbound_messages` — the console provider
 * "delivers" by logging, so the row is the only place the token exists. */
function resetTokenFor(email) {
  const { execSync } = require("child_process");
  const sql =
    "SELECT body_preview FROM outbound_messages WHERE lower(to_address) = lower('" + email +
    "') AND message_type = 'password_reset' ORDER BY queued_at DESC LIMIT 1";
  const out = execSync(
    `psql "${DB_URL}" -At -c "${sql}"`,
  ).toString();
  const m = out.match(/reset-password\?token=([A-Za-z0-9_\-]+)/);
  return m ? m[1] : null;
}

(async () => {
  const [, auth] = await api("POST", "/auth/login", null, { email: "owner@acme-demo.test", password: "Demo@12345" });
  const token = auth.access_token;
  // A user of our own to reset, so the demo Owner's password stays put.
  // Inserted directly: the invite flow only creates the user once the
  // invitation is accepted, and this test is about the reset path.
  const { execSync } = require("child_process");
  execSync(
    `psql "${DB_URL}" -c ` +
    `"INSERT INTO users (company_id, email, full_name, role_id, is_platform_admin, has_all_godowns, status, ` +
    `password_hash, password_changed_at) SELECT u.company_id, '${EMAIL}', 'Browser Auth ${SFX}', ` +
    `(SELECT id FROM roles WHERE company_id IS NULL AND code='viewer'), false, true, 'active', ` +
    `u.password_hash, now() FROM users u WHERE u.email='owner@acme-demo.test'"`,
  );

  // Start from "never configured", so the validation checks below are about
  // the form rather than about whatever a previous run left behind.
  execSync(
    `psql "${DB_URL}" -c ` +
    `"DELETE FROM company_email_settings WHERE company_id = (SELECT id FROM companies WHERE name='Acme Trading Co')"`,
  );

  const browser = await chromium.launch(process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {});
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));

  try {
    // ------------------------------------------------ forgot password
    await page.goto(`${BASE}/login`);
    await page.waitForSelector("#email", { timeout: 20000 });
    check("A01 the sign-in screen offers a working 'Forgot password?' link",
          await page.isVisible('a[href="/forgot-password"]'), "");
    await page.click('a[href="/forgot-password"]');
    await page.waitForSelector("#fp-email", { timeout: 20000 });

    await page.fill("#fp-email", "not-an-email");
    await page.click('button:has-text("Send reset link")');
    await page.waitForSelector("text=/email address you sign in with/i", { timeout: 10000 });
    check("A02 a malformed address is caught before the request", true);

    await page.fill("#fp-email", `nobody.${SFX}@acme-demo.test`);
    await page.click('button:has-text("Send reset link")');
    await page.waitForSelector("text=/a reset link is on its way/i", { timeout: 15000 });
    const unknownText = (await page.textContent("body")).replace(/\s+/g, " ");
    check("A03 an unknown address gets the same confirmation (no account enumeration)",
          /If nobody\.\w+@acme-demo\.test belongs to an account/i.test(unknownText), "");

    await page.click("text=try a different address");
    await page.fill("#fp-email", EMAIL);
    await page.click('button:has-text("Send reset link")');
    await page.waitForSelector("text=/a reset link is on its way/i", { timeout: 15000 });
    const resetToken = resetTokenFor(EMAIL);
    check("A04 a real address really does get a token", !!resetToken, resetToken);

    // ------------------------------------------------- reset password
    await page.goto(`${BASE}/reset-password`);
    await page.waitForSelector("text=/missing its token/i", { timeout: 20000 });
    check("A05 the reset screen refuses a link with no token", true);

    await page.goto(`${BASE}/reset-password?token=${resetToken}`);
    await page.waitForSelector("#rp-password", { timeout: 20000 });
    await page.fill("#rp-password", "weak");
    await page.fill("#rp-confirm", "weak");
    await page.click('button:has-text("Set new password")');
    await page.waitForSelector("text=/needs at least 8 characters/i", { timeout: 10000 });
    check("A06 a weak password is refused with the rule spelled out", true);

    await page.fill("#rp-password", "Browser@12345");
    await page.fill("#rp-confirm", "Browser@99999");
    await page.click('button:has-text("Set new password")');
    await page.waitForSelector("text=/don't match/i", { timeout: 10000 });
    check("A07 mismatched confirmation is caught", true);

    await page.fill("#rp-confirm", "Browser@12345");
    await page.click('button:has-text("Set new password")');
    await page.waitForURL((u) => u.pathname === "/login", { timeout: 20000 });
    const loginText = (await page.textContent("body")).replace(/\s+/g, " ");
    check("A08 a successful reset lands on sign-in with a confirmation",
          /password has been changed/i.test(loginText), loginText.slice(0, 120));

    const [st] = await api("POST", "/auth/login", null, { email: EMAIL, password: "Browser@12345" });
    check("A09 the new password actually works", st === 200, st);
    const [stReuse] = await api("POST", "/auth/reset-password", null, { token: resetToken, new_password: "Again@12345" });
    check("A10 the link cannot be used twice", stReuse === 422, stReuse);

    // ------------------------------------------------- email settings
    await page.fill("#email", "owner@acme-demo.test");
    await page.fill("#password", "Demo@12345");
    await page.click('button[type="submit"]');
    await page.waitForFunction(() => !!localStorage.getItem("inventoryai.access_token.v1"), { timeout: 20000 });
    await page.goto(`${BASE}/settings`);
    await page.waitForSelector('[data-testid="email-settings"]', { timeout: 25000 });
    check("A11 Settings has an outgoing-email panel", true);

    await page.click("#em-provider");
    await page.click('[role="option"]:has-text("Your own SMTP server")');
    await page.click('button:has-text("Save email settings")');
    await page.waitForSelector("text=/mail server's host name/i", { timeout: 10000 });
    check("A12 SMTP without a host is refused, with the field named", true);

    await page.fill("#em-host", "smtp.example.test");
    await page.fill("#em-from", `no-reply.${SFX}@acme.test`);
    await page.fill("#em-password", "hunter2!");
    await page.click('button:has-text("Save email settings")');
    // The card reloads itself from the API after a save; the password field
    // then advertises that one is stored.
    await page.waitForFunction(
      () => document.querySelector("#em-password")?.placeholder?.includes("unchanged"),
      null,
      { timeout: 20000 },
    );
    const [, saved] = await api("GET", "/company/email-settings", token);
    check("A13 the settings save and the password is stored write-only",
          saved.provider === "smtp" && saved.has_password === true && !("smtp_password" in saved), saved);

    await page.click('button:has-text("Send test")');
    await page.waitForSelector("text=/Could not send/i", { timeout: 30000 });
    check("A14 a test against an unreachable server reports the failure", true);

    // Put it back so the rest of the app keeps logging invitations.
    await page.click("#em-provider");
    await page.click('[role="option"]:has-text("Not configured")');
    await page.click('button:has-text("Save email settings")');
    await page.waitForTimeout(1500);
    const [, back] = await api("GET", "/company/email-settings", token);
    check("A15 switching back to 'not configured' sticks", back.provider === "console", back);

    check("A16 no console errors during the whole run",
          consoleErrors.filter((e) => !/favicon|404 \(Not Found\)|status of 4\d\d/i.test(e)).length === 0,
          consoleErrors.slice(0, 3));
  } catch (err) {
    check("run completed without throwing", false, err && err.message);
    await page.screenshot({ path: "/tmp/browser-auth-failure.png", fullPage: true }).catch(() => {});
  } finally {
    await browser.close();
  }

  console.log(`\n${passed} passed, ${failed.length} failed`);
  failed.forEach((f) => console.log("  - " + f));
  process.exit(failed.length ? 1 : 0);
})();
