import csv
import time
import argparse
import sys
import os
import re
import urllib.parse as urlparse
import shutil

from selenium import webdriver
import requests

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import WebDriverException
import tempfile

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
FAST_SKIP_SECONDS = int(os.environ.get("FAST_SKIP_SECONDS", "6"))
EMAIL_WAIT_SECONDS = int(os.environ.get("EMAIL_WAIT_SECONDS", "10"))
CAPTCHA_WAIT_SECONDS = int(os.environ.get("CAPTCHA_WAIT_SECONDS", "20"))
MAX_ATTEMPTS_PER_CHANNEL = int(os.environ.get("MAX_ATTEMPTS_PER_CHANNEL", "2"))

def is_valid_email(email):
    if not email or '@' not in email:
        return False
    if email.count('@') != 1:
        return False
    local, domain = email.rsplit('@', 1)
    if not local or not domain:
        return False
    if '..' in local or '..' in domain:
        return False
    if local.startswith('.') or local.endswith('.'):
        return False
    labels = domain.split('.')
    if len(labels) < 2:
        return False
    tld = labels[-1]
    if not re.fullmatch(r'[A-Za-z]{2,24}', tld or ''):
        return False
    for label in labels:
        if not label:
            return False
        if label.startswith('-') or label.endswith('-'):
            return False
        if not re.fullmatch(r'[A-Za-z0-9-]+', label):
            return False
    return True

def solve_recaptcha_2captcha(api_key, sitekey, page_url, max_wait_seconds=60):
    submit = requests.post(
        "https://2captcha.com/in.php",
        data={
            "key": api_key,
            "method": "userrecaptcha",
            "googlekey": sitekey,
            "pageurl": page_url,
            "json": 1,
        },
        timeout=60,
    ).json()
    if submit.get("status") != 1:
        raise Exception(f"2Captcha submit failed: {submit}")
    captcha_id = submit.get("request")
    polls = max(1, int(max_wait_seconds / 5))
    for _ in range(polls):
        time.sleep(5)
        res = requests.get(
            "https://2captcha.com/res.php",
            params={"key": api_key, "action": "get", "id": captcha_id, "json": 1},
            timeout=60,
        ).json()
        if res.get("status") == 1:
            return res.get("request")
        if res.get("request") not in ("CAPCHA_NOT_READY", "CAPTCHA_NOT_READY"):
            raise Exception(f"2Captcha result failed: {res}")
    raise Exception("2Captcha timed out waiting for solution")

def solve_recaptcha_anticaptcha(client_key, sitekey, page_url):
    create = requests.post(
        "https://api.anti-captcha.com/createTask",
        json={
            "clientKey": client_key,
            "task": {
                "type": "RecaptchaV2TaskProxyless",
                "websiteURL": page_url,
                "websiteKey": sitekey,
            },
        },
        timeout=60,
    ).json()
    if create.get("errorId") != 0:
        raise Exception(f"Anti-Captcha createTask failed: {create}. If your balance is 0, add funds.")
    task_id = create.get("taskId")
    for _ in range(60):
        time.sleep(5)
        res = requests.post(
            "https://api.anti-captcha.com/getTaskResult",
            json={"clientKey": client_key, "taskId": task_id},
            timeout=60,
        ).json()
        if res.get("errorId") != 0:
            raise Exception(f"Anti-Captcha getTaskResult failed: {res}")
        if res.get("status") == "ready":
            token = (res.get("solution") or {}).get("gRecaptchaResponse")
            if not token:
                raise Exception(f"Anti-Captcha returned no token: {res}")
            return token
    raise Exception("Anti-Captcha timed out waiting for solution")

def solve_recaptcha_capsolver(client_key, sitekey, page_url):
    create = requests.post(
        "https://api.capsolver.com/createTask",
        json={
            "clientKey": client_key,
            "task": {
                "type": "ReCaptchaV2TaskProxyLess",
                "websiteURL": page_url,
                "websiteKey": sitekey,
            },
        },
        timeout=60,
    ).json()
    if create.get("errorId") not in (0, None):
        raise Exception(f"CapSolver createTask failed: {create}. If your balance is 0, add funds.")
    task_id = create.get("taskId")
    if not task_id:
        raise Exception(f"CapSolver createTask returned no taskId: {create}")
    for _ in range(60):
        time.sleep(5)
        res = requests.post(
            "https://api.capsolver.com/getTaskResult",
            json={"clientKey": client_key, "taskId": task_id},
            timeout=60,
        ).json()
        if res.get("errorId") not in (0, None):
            raise Exception(f"CapSolver getTaskResult failed: {res}")
        if res.get("status") == "ready":
            token = (res.get("solution") or {}).get("gRecaptchaResponse")
            if not token:
                raise Exception(f"CapSolver returned no token: {res}")
            return token
    raise Exception("CapSolver timed out waiting for solution")

def _extract_first_email(text):
    if not text:
        return None
    m = EMAIL_REGEX.search(text)
    if not m:
        return None
    cand = m.group(0).strip().strip('.,;:()[]{}<>')
    return cand if is_valid_email(cand) else None

def _has_valid_email_field(value):
    if not value:
        return False
    if str(value).strip().lower() == "not found":
        return False
    for m in EMAIL_REGEX.findall(str(value)):
        if is_valid_email(m):
            return True
    return False

def _normalize_channel_url(url):
    if not url:
        return ""
    u = str(url).strip()
    if not u:
        return ""
    if not u.startswith("http://") and not u.startswith("https://"):
        u = "https://" + u
    if "youtube.com" not in u and "youtu.be" not in u:
        return u
    parsed = urlparse.urlparse(u)
    path = parsed.path or ""
    if not path.endswith("/about"):
        path = path.rstrip("/") + "/about"
    rebuilt = urlparse.urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))
    return rebuilt

def _save_progress(output_csv, leads):
    if not leads:
        return
    keys = leads[0].keys()
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(leads)

def _find_recaptcha_sitekey(driver):
    try:
        iframe = driver.find_element(By.XPATH, "//iframe[contains(@src, 'recaptcha')]")
        src = iframe.get_attribute("src") or ""
        parsed = urlparse.urlparse(src)
        return urlparse.parse_qs(parsed.query).get("k", [None])[0]
    except Exception:
        pass
    try:
        el = driver.find_element(By.CSS_SELECTOR, "div.g-recaptcha[data-sitekey]")
        return el.get_attribute("data-sitekey")
    except Exception:
        return None

def _wait_for_any_email(driver, timeout_s=45):
    end = time.time() + timeout_s
    while time.time() < end:
        email = _extract_first_email(driver.page_source)
        if email:
            return email
        try:
            mailto = driver.find_element(By.XPATH, "//a[starts-with(@href, 'mailto:')]")
            href = mailto.get_attribute("href") or ""
            email = href.replace("mailto:", "").strip()
            if email and is_valid_email(email):
                return email
        except Exception:
            pass
        time.sleep(0.5)
    return None

def _is_sign_in_required(driver):
    try:
        text = (driver.page_source or "").lower()
    except Exception:
        text = ""
    markers = [
        "sign in to see email address",
        "signin to see email address",
        "sign in to continue",
        "accounts.google.com",
    ]
    return any(m in text for m in markers)

def inject_recaptcha_token(driver, token):
    driver.execute_script(
        """
        const token = arguments[0];
        let el = document.getElementById('g-recaptcha-response');
        if (!el) {
          el = document.createElement('textarea');
          el.id = 'g-recaptcha-response';
          el.name = 'g-recaptcha-response';
          el.style.width = '250px';
          el.style.height = '40px';
          el.style.display = 'none';
          document.body.appendChild(el);
        }
        el.value = token;
        el.innerHTML = token;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        """
    , token)

def scrape_captcha_emails(input_csv, output_csv, twocaptcha_key=None, anticaptcha_key=None, capsolver_key=None):
    leads = []
    try:
        with open(input_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                leads.append(row)
    except FileNotFoundError:
        print(f"Error: Could not find input file '{input_csv}'")
        return
            
    needs_email = [lead for lead in leads if not _has_valid_email_field(lead.get('Emails Found'))]
    
    if not needs_email:
        print("All leads already have emails! Nothing to do.")
        return

    print(f"Found {len(needs_email)} leads missing emails.")
    if twocaptcha_key:
        print("Starting browser... 2Captcha API key provided. Will attempt to solve CAPTCHAs automatically.")
    elif anticaptcha_key:
        print("Starting browser... Anti-Captcha API key provided. Will attempt to solve CAPTCHAs automatically.")
    elif capsolver_key:
        print("Starting browser... CapSolver API key provided. Will attempt to solve CAPTCHAs automatically.")
    else:
        print("Starting browser... NOTE: You will need to manually solve the CAPTCHA when it appears in the browser window.")
    
    options = webdriver.ChromeOptions()
    is_headless = sys.platform.startswith("linux") or os.environ.get("FORCE_HEADLESS") == "1"
    
    if is_headless:
        options.add_argument('--headless=new')
        
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-software-rasterizer')
    options.add_argument('--disable-features=VizDisplayCompositor')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    options.add_argument('--remote-debugging-port=9222')
    profile_user_data_dir = os.environ.get("CHROME_USER_DATA_DIR", "").strip()
    profile_directory = os.environ.get("CHROME_PROFILE_DIR", "").strip()
    if profile_user_data_dir:
        options.add_argument(f"--user-data-dir={profile_user_data_dir}")
        if profile_directory:
            options.add_argument(f"--profile-directory={profile_directory}")
    else:
        user_data_dir = tempfile.mkdtemp(prefix="chrome-user-data-")
        options.add_argument(f'--user-data-dir={user_data_dir}')

    chromium_path = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome") or shutil.which("google-chrome-stable")
    if chromium_path:
        options.binary_location = chromium_path

    chromedriver_candidates = [
        shutil.which("chromedriver"),
        "/usr/bin/chromedriver",
        "/usr/lib/chromium/chromedriver",
        "/usr/lib/chromium-browser/chromedriver",
    ]
    chromedriver_path = next((p for p in chromedriver_candidates if p and os.path.exists(p)), None)

    def start_driver():
        if chromedriver_path:
            service = Service(chromedriver_path)
            return webdriver.Chrome(service=service, options=options)
        return webdriver.Chrome(options=options)

    try:
        driver = start_driver()
    except Exception as e:
        print(f"Failed to start Chrome driver: {e}")
        print("If running on Streamlit Cloud, make sure packages.txt is configured with chromium and chromium-driver.")
        return
    
    processed = 0
    found_count = 0
    failed_count = 0

    for lead in needs_email:
        url = lead.get('URL')
        if not url:
            continue

        target_url = _normalize_channel_url(url)
        print(f"\nProcessing: {lead.get('Channel Name')} ({target_url})")
        success = False

        for attempt in range(1, MAX_ATTEMPTS_PER_CHANNEL + 1):
            try:
                driver.get(target_url)
                time.sleep(2)
            except WebDriverException as nav_err:
                print(f"Navigation failed attempt {attempt} ({nav_err}). Restarting browser...")
                try:
                    driver.quit()
                except Exception:
                    pass
                try:
                    driver = start_driver()
                except Exception as restart_err:
                    print(f"Browser restart failed ({restart_err}).")
                    continue
                continue

            try:
                existing_email = _wait_for_any_email(driver, timeout_s=3)
                if existing_email:
                    lead["Emails Found"] = existing_email
                    success = True
                    break
                if _is_sign_in_required(driver):
                    print("Channel requires YouTube sign-in before email reveal. Skipping.")
                    lead["Emails Found"] = "Sign-in required"
                    success = True
                    break

                driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(0.7)
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(0.7)

                view_btn = None
                view_btn_xpaths = [
                    "//*[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'view email address')]",
                    "//button//*[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'view email address')]/ancestor::button[1]",
                    "//*[@aria-label and contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'view email address')]",
                    "//*[@aria-label and contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'email')]",
                    "//button[.//*[name()='svg'] and contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'email')]",
                ]
                for xp in view_btn_xpaths:
                    try:
                        view_btn = WebDriverWait(driver, 8).until(EC.element_to_be_clickable((By.XPATH, xp)))
                        break
                    except Exception:
                        continue

                has_view_flow = False
                if view_btn:
                    has_view_flow = True
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", view_btn)
                    time.sleep(0.4)
                    view_btn.click()
                else:
                    print("No view-email button. Fast-skip checks only.")

                if twocaptcha_key or anticaptcha_key or capsolver_key:
                    sitekey = _find_recaptcha_sitekey(driver)
                    if sitekey:
                        has_view_flow = True
                        if twocaptcha_key:
                            token = solve_recaptcha_2captcha(
                                twocaptcha_key,
                                sitekey,
                                driver.current_url,
                                max_wait_seconds=CAPTCHA_WAIT_SECONDS
                            )
                        elif anticaptcha_key:
                            token = solve_recaptcha_anticaptcha(anticaptcha_key, sitekey, driver.current_url)
                        else:
                            token = solve_recaptcha_capsolver(capsolver_key, sitekey, driver.current_url)

                        inject_recaptcha_token(driver, token)
                        submit_btn = None
                        submit_xpaths = [
                            "//*[@id='submit-btn']",
                            "//button[contains(., 'Submit')]",
                            "//button[contains(., 'Verify')]",
                            "//button[contains(., 'Continue')]",
                        ]
                        for xp in submit_xpaths:
                            try:
                                submit_btn = WebDriverWait(driver, 8).until(EC.element_to_be_clickable((By.XPATH, xp)))
                                break
                            except Exception:
                                continue
                        if submit_btn:
                            submit_btn.click()
                    elif _is_sign_in_required(driver):
                        print("Sign-in wall detected. 2Captcha cannot bypass account login requirement.")
                        lead["Emails Found"] = "Sign-in required"
                        success = True
                        break

                wait_s = EMAIL_WAIT_SECONDS if has_view_flow else FAST_SKIP_SECONDS
                email = _wait_for_any_email(driver, timeout_s=wait_s)
                if email:
                    print(f"Success! Found email: {email}")
                    lead["Emails Found"] = email
                    success = True
                    break

                print(f"No email found on attempt {attempt}.")
                time.sleep(1)

            except Exception as e:
                print(f"Attempt {attempt} failed ({e}).")
                try:
                    driver.quit()
                except Exception:
                    pass
                try:
                    driver = start_driver()
                except Exception:
                    pass

        processed += 1
        if success:
            found_count += 1
        else:
            failed_count += 1
            print("Could not extract email automatically for this channel.")

        _save_progress(output_csv, leads)
            
    try:
        driver.quit()
    except Exception:
        pass
    
    if leads:
        _save_progress(output_csv, leads)
        print(f"\nSaved updated leads to {output_csv}")
        print(f"Processed: {processed} | Found: {found_count} | Not Found: {failed_count}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Scrape hidden CAPTCHA emails for leads missing them.")
    parser.add_argument("--input", "-i", default="leads.csv", help="Input CSV file from the API extractor")
    parser.add_argument("--output", "-o", default="leads_updated.csv", help="Output CSV file to save updated emails")
    parser.add_argument("--twocaptcha", help="2Captcha API key for automated solving")
    parser.add_argument("--anticaptcha", help="Anti-Captcha API key for automated solving")
    parser.add_argument("--capsolver", help="CapSolver API key for automated solving")
    args = parser.parse_args()
    
    scrape_captcha_emails(args.input, args.output, args.twocaptcha, args.anticaptcha, args.capsolver)
