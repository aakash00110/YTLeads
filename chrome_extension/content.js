function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

function toAboutUrl(url) {
  const u = new URL(url);
  if (!u.hostname.includes("youtube.com")) return url;
  if (u.pathname.endsWith("/about")) return u.toString();
  if (u.pathname.startsWith("/@")) {
    u.pathname = u.pathname.replace(/\/+$/, "") + "/about";
    return u.toString();
  }
  return u.toString();
}

function findViewEmailButton() {
  const xpath = "//yt-formatted-string[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'view email address')]/ancestor::*[@role='button' or self::button][1]";
  const node = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
  return node;
}

function findRecaptchaSitekey() {
  const el = document.querySelector(".g-recaptcha[data-sitekey], div[data-sitekey]");
  if (el?.dataset?.sitekey) return el.dataset.sitekey;
  const iframe = document.querySelector("iframe[src*='recaptcha']");
  if (!iframe?.src) return null;
  const m = iframe.src.match(/[?&]k=([^&]+)/) || iframe.src.match(/\/anchor\?k=([^&]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

function injectRecaptchaToken(token) {
  let ta = document.getElementById("g-recaptcha-response");
  if (!ta) {
    ta = document.createElement("textarea");
    ta.id = "g-recaptcha-response";
    ta.name = "g-recaptcha-response";
    ta.style.display = "none";
    document.body.appendChild(ta);
  }
  ta.value = token;
  ta.innerHTML = token;
  ta.dispatchEvent(new Event("input", { bubbles: true }));
  ta.dispatchEvent(new Event("change", { bubbles: true }));
}

function findSubmitButton() {
  const selectors = [
    "button#submit",
    "button[type='submit']",
    "yt-button-renderer#submit button",
    "button.yt-spec-button-shape-next"
  ];
  for (const sel of selectors) {
    const btn = document.querySelector(sel);
    if (btn) return btn;
  }
  return null;
}

function getVisibleEmail() {
  const source = document.body?.innerText || "";
  const m = source.match(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/);
  return m ? m[0] : null;
}

function isSignInRequired() {
  const txt = (document.body?.innerText || "").toLowerCase();
  return txt.includes("sign in to see email address") || txt.includes("sign in");
}

async function ensureAboutPage() {
  const next = toAboutUrl(location.href);
  if (next !== location.href) {
    location.href = next;
    await sleep(2500);
  }
}

async function solveCaptcha(apiKey, sitekey, pageUrl) {
  return await chrome.runtime.sendMessage({
    type: "SOLVE_2CAPTCHA",
    apiKey,
    sitekey,
    pageUrl
  });
}

async function executeReveal(apiKey) {
  await ensureAboutPage();
  await sleep(1500);

  const preEmail = getVisibleEmail();
  if (preEmail) return { ok: true, status: "revealed", email: preEmail };
  if (isSignInRequired()) return { ok: false, status: "sign_in_required", error: "YouTube sign-in required" };

  const viewBtn = findViewEmailButton();
  if (!viewBtn) return { ok: false, status: "no_view_email", error: "View email button not found" };

  viewBtn.scrollIntoView({ block: "center" });
  await sleep(400);
  viewBtn.click();
  await sleep(1200);

  const sitekey = findRecaptchaSitekey();
  if (!sitekey) {
    const directEmail = getVisibleEmail();
    if (directEmail) return { ok: true, status: "revealed", email: directEmail };
    if (isSignInRequired()) return { ok: false, status: "sign_in_required", error: "Sign-in wall detected" };
    return { ok: false, status: "captcha_missing", error: "reCAPTCHA sitekey not found" };
  }

  const solveRes = await solveCaptcha(apiKey, sitekey, location.href);
  if (!solveRes?.ok || !solveRes.token) {
    return { ok: false, status: "captcha_failed", error: solveRes?.error || "2Captcha failed" };
  }

  injectRecaptchaToken(solveRes.token);
  await sleep(300);
  const submitBtn = findSubmitButton();
  if (submitBtn) {
    submitBtn.click();
  } else {
    const form = document.querySelector("form");
    if (form) form.submit();
  }

  for (let i = 0; i < 20; i++) {
    await sleep(500);
    const email = getVisibleEmail();
    if (email) return { ok: true, status: "revealed", email };
  }
  return { ok: false, status: "not_found", error: "Email not revealed after captcha submit" };
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.type === "EXECUTE_REVEAL") {
    executeReveal(msg.apiKey)
      .then(res => sendResponse(res))
      .catch(err => sendResponse({ ok: false, status: "error", error: err?.message || String(err) }));
    return true;
  }
});
