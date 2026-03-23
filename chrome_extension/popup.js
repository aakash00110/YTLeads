const apiKeyInput = document.getElementById("apiKey");
const saveKeyBtn = document.getElementById("saveKey");
const runCurrentBtn = document.getElementById("runCurrent");
const statusEl = document.getElementById("status");

function setStatus(message) {
  statusEl.textContent = message || "";
}

async function loadKey() {
  const data = await chrome.storage.sync.get(["twocaptchaKey"]);
  apiKeyInput.value = data.twocaptchaKey || "";
}

saveKeyBtn.addEventListener("click", async () => {
  const key = (apiKeyInput.value || "").trim();
  await chrome.storage.sync.set({ twocaptchaKey: key });
  setStatus(key ? "API key saved." : "API key cleared.");
});

runCurrentBtn.addEventListener("click", async () => {
  const key = (apiKeyInput.value || "").trim();
  if (!key) {
    setStatus("Please enter 2Captcha API key.");
    return;
  }
  setStatus("Running...");
  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tabs[0]?.id) {
      setStatus("No active tab found.");
      return;
    }
    const res = await chrome.runtime.sendMessage({
      type: "RUN_CURRENT_TAB",
      tabId: tabs[0].id,
      apiKey: key
    });
    if (!res) {
      setStatus("No response from extension.");
      return;
    }
    if (res.ok) {
      setStatus(`Done\nStatus: ${res.status}\nEmail: ${res.email || "none"}`);
    } else {
      setStatus(`Failed\nStatus: ${res.status || "error"}\nReason: ${res.error || "unknown"}`);
    }
  } catch (e) {
    setStatus(`Error: ${e?.message || e}`);
  }
});

loadKey();
