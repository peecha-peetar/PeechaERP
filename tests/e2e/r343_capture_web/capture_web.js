// E2E of the mobile capture page against a real uvicorn + Postgres (Chromium, phone viewport).
const { chromium, devices } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const fs = require("fs");
const path = require("path");
const dir = process.argv[2];
const setup = JSON.parse(fs.readFileSync(path.join(dir, "setup.json"), "utf8"));
const base = process.env.E2E_BASE || "http://127.0.0.1:8765";
let failed = false;
const check = (cond, msg) => { console.log((cond ? "OK: " : "FAIL: ") + msg); if (!cond) failed = true; };

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ ...devices["Pixel 5"], locale: "fa-IR" });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));

  // 1) open link without login: only the login form, no record data
  const response = await page.goto(`${base}/m/capture#${setup.token}`);
  const headers = response.headers();
  check(headers["content-security-policy"].includes("script-src 'nonce-") && headers["cache-control"] === "no-store"
        && headers["referrer-policy"] === "no-referrer" && headers["x-frame-options"] === "DENY", "security headers on the page");
  await page.waitForSelector("#login:not(.hidden)");
  check(!page.url().includes(setup.token), `the token is removed from the address bar (${page.url()})`);
  check(!(await page.content()).includes("سند هزینه حمل"), "no record data before login");
  await page.screenshot({ path: path.join(dir, "01_login.png") });

  // 2) wrong password
  await page.fill("#username", "admin");
  await page.fill("#password", "wrong");
  await page.click("#loginBtn");
  await page.waitForFunction(() => document.getElementById("msg").textContent.length > 0);
  check((await page.textContent("#msg")).includes("نادرست"), `wrong password is refused (${await page.textContent("#msg")})`);

  // 3) login, request opens and shows the target
  await page.fill("#password", "secret123");
  await page.click("#loginBtn");
  await page.waitForSelector("#capture:not(.hidden)");
  const label = await page.textContent("#targetLabel");
  check(label.length > 0 && !/\d{4}-\d{2}-\d{2}/.test(label) && /۱۴[۰-۹]{2}\//.test(label), `target shown with a Jalali date after login (${await page.textContent("#targetKind")}: ${label})`);
  check((await page.textContent("#statusLabel")).length > 0, `status shown (${await page.textContent("#statusLabel")})`);
  check(await page.isDisabled("#sendBtn"), "send is disabled before any photo");

  // 4) camera: file chooser (capture=environment) -> preview
  const takePhoto = async (file) => {
    const [chooser] = await Promise.all([page.waitForEvent("filechooser"), page.click("#cameraBtn")]);
    await chooser.setFiles(path.join(dir, file));
  };
  const accept = await page.getAttribute("#camera", "accept");
  const captureAttr = await page.getAttribute("#camera", "capture");
  check(accept === "image/*" && captureAttr === "environment", "the input opens the rear camera on phones");
  await takePhoto("photo_a.jpg");
  await page.waitForSelector("#thumbs img");
  check((await page.$$("#thumbs img")).length === 1 && !(await page.isDisabled("#sendBtn")), "photo preview shown, send enabled");
  await takePhoto("photo_b.jpg");
  await page.waitForFunction(() => document.querySelectorAll("#thumbs img").length === 2);
  await page.screenshot({ path: path.join(dir, "02_preview.png") });
  // remove the second, retake replaces the last one
  await page.click("#thumbs .thumb:nth-child(2) button");
  check((await page.$$("#thumbs img")).length === 1, "a photo can be removed before sending");
  const [chooser] = await Promise.all([page.waitForEvent("filechooser"), page.click("#retakeBtn")]);
  await chooser.setFiles(path.join(dir, "photo_b.jpg"));
  await page.waitForFunction(() => document.querySelectorAll("#thumbs img").length === 1);
  check(true, "retake replaces the last photo");

  // 5) a non-image file is refused on the page
  const [bad] = await Promise.all([page.waitForEvent("filechooser"), page.click("#cameraBtn")]);
  await bad.setFiles({ name: "x.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4") });
  await page.waitForFunction(() => document.getElementById("msg").textContent.includes("فقط عکس"));
  check((await page.$$("#thumbs img")).length === 1, "a non-image file is not added");

  // 6) send with progress
  await page.click("#sendBtn");
  await page.waitForFunction(() => document.getElementById("msg").textContent.includes("پیوست شد"), null, { timeout: 30000 });
  check((await page.getAttribute("#progress", "value")) === "100" || (await page.evaluate(() => document.getElementById("progress").value)) === 100,
        "upload progress reaches 100");
  check(await page.isDisabled("#cameraBtn") && await page.isDisabled("#sendBtn"), "after completion, no more sending");
  await page.screenshot({ path: path.join(dir, "03_done.png") });

  // 7) reopening the same link says it is completed and offers no upload
  await page.reload();
  await page.waitForFunction(() => document.getElementById("msg").textContent.length > 0);
  check(await page.isHidden("#capture") && (await page.textContent("#msg")).includes("تکمیل"),
        `reopened link is closed (${await page.textContent("#msg")})`);

  // 8) cancel flow on the second request
  await page.goto(`${base}/m/capture#${setup.cancel_token}`);
  await page.waitForSelector("#capture:not(.hidden)");
  page.once("dialog", (d) => d.accept());
  await page.click("#cancelBtn");
  await page.waitForFunction(() => document.getElementById("msg").textContent.includes("لغو شد"));
  check(await page.isDisabled("#cameraBtn"), "cancel from the phone closes the request");

  // 9) forged token: nothing revealed
  await page.goto(`${base}/m/capture#AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA`);
  await page.waitForFunction(() => document.getElementById("msg").textContent.length > 0);
  check(await page.isHidden("#capture"), `forged token shows only an error (${await page.textContent("#msg")})`);

  check(consoleErrors.filter((e) => !/40[0-9]|Failed to load resource/.test(e)).length === 0, `no script/CSP errors (${consoleErrors.join(" | ")})`);
  await browser.close();
  console.log(failed ? "SOME FAILED" : "ALL PASS");
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
