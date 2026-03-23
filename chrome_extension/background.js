async function solveWith2Captcha(apiKey, sitekey, pageUrl) {
  const inUrl = new URL("https://2captcha.com/in.php");
  inUrl.searchParams.set("key", apiKey);
  inUrl.searchParams.set("method", "userrecaptcha");
  inUrl.searchParams.set("googlekey", sitekey);
  inUrl.searchParams.set("pageurl", pageUrl);
  inUrl.searchParams.set("json", "1");

  const submitRes = await fetch(inUrl.toString());
  const submitJson = await submitRes.json();
  if (submitJson.status !== 1) {
    throw new Error(`2Captcha submit failed: ${submitJson.request}`);
  }

  const id = submitJson.request;
  const start = Date.now();
  while (Date.now() - start < 120000) {
    await new Promise(r => setTimeout(r, 5000));
    const resUrl = new URL("https://2captcha.com/res.php");
    resUrl.searchParams.set("key", apiKey);
    resUrl.searchParams.set("action", "get");
    resUrl.searchParams.set("id", id);
    resUrl.searchParams.set("json", "1");
    const pollRes = await fetch(resUrl.toString());
    const pollJson = await pollRes.json();
    if (pollJson.status === 1) return pollJson.request;
    if (pollJson.request !== "CAPCHA_NOT_READY") {
      throw new Error(`2Captcha poll failed: ${pollJson.request}`);
    }
  }
  throw new Error("2Captcha solve timeout");
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.type === "SOLVE_2CAPTCHA") {
    solveWith2Captcha(msg.apiKey, msg.sitekey, msg.pageUrl)
      .then(token => sendResponse({ ok: true, token }))
      .catch(err => sendResponse({ ok: false, error: err?.message || String(err) }));
    return true;
  }

  if (msg?.type === "RUN_CURRENT_TAB") {
    chrome.tabs.sendMessage(
      msg.tabId,
      { type: "EXECUTE_REVEAL", apiKey: msg.apiKey },
      (response) => {
        if (chrome.runtime.lastError) {
          sendResponse({
            ok: false,
            status: "messaging_error",
            error: chrome.runtime.lastError.message
          });
          return;
        }
        sendResponse(response || { ok: false, status: "no_response", error: "No response from content script" });
      }
    );
    return true;
  }
});
