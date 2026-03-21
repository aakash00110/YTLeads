import csv
import time
import argparse
import sys
import os
import urllib.parse as urlparse
import shutil

from selenium import webdriver
import requests

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
import tempfile

def solve_recaptcha_2captcha(api_key, sitekey, page_url):
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
    for _ in range(60):
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
            
    needs_email = [lead for lead in leads if lead.get('Emails Found') == 'Not Found' or not lead.get('Emails Found')]
    
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
    is_headless = bool(twocaptcha_key or anticaptcha_key or capsolver_key)
    
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

    try:
        if chromedriver_path:
            service = Service(chromedriver_path)
            driver = webdriver.Chrome(service=service, options=options)
        else:
            driver = webdriver.Chrome(options=options)
    except Exception as e:
        print(f"Failed to start Chrome driver: {e}")
        print("If running on Streamlit Cloud, make sure packages.txt is configured with chromium and chromium-driver.")
        return
    
    for lead in needs_email:
        url = lead.get('URL')
        if not url:
            continue
            
        print(f"\nProcessing: {lead.get('Channel Name')} ({url})")
        driver.get(f"{url}/about")
        time.sleep(3)
        
        try:
            btn_xpath = "//*[contains(text(), 'View email address')]"
            view_btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, btn_xpath)))
            view_btn.click()
            
            if twocaptcha_key or anticaptcha_key or capsolver_key:
                print("Clicked 'View email address'. Waiting for reCAPTCHA to appear...")
                try:
                    iframe = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, "//iframe[contains(@src, 'recaptcha')]"))
                    )
                    src = iframe.get_attribute("src")
                    
                    parsed = urlparse.urlparse(src)
                    sitekey = urlparse.parse_qs(parsed.query).get('k', [None])[0]
                    
                    if sitekey:
                        if twocaptcha_key:
                            print("Sending CAPTCHA to 2Captcha for solving (this takes 15-45 seconds)...")
                            token = solve_recaptcha_2captcha(twocaptcha_key, sitekey, driver.current_url)
                        elif anticaptcha_key:
                            print("Sending CAPTCHA to Anti-Captcha for solving (this takes 15-45 seconds)...")
                            token = solve_recaptcha_anticaptcha(anticaptcha_key, sitekey, driver.current_url)
                        
                        elif capsolver_key:
                            print("Sending CAPTCHA to CapSolver for solving (this takes 15-45 seconds)...")
                            token = solve_recaptcha_capsolver(capsolver_key, sitekey, driver.current_url)
                                
                        print("Solved! Injecting token and clicking submit...")
                        
                        inject_recaptcha_token(driver, token)
                        
                        submit_btn = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='submit-btn'] | //button[contains(., 'Submit')]"))
                        )
                        submit_btn.click()
                    else:
                        print("Could not find sitekey for auto-solve. Please solve manually.")
                except Exception as e:
                    print(f"Auto-solve failed ({e}). Falling back to manual solve. Please click the checkbox in the browser...")
            else:
                print("Clicked 'View email address'. Please solve the CAPTCHA in the browser (you have 60 seconds)...")
            
            email_link = WebDriverWait(driver, 60).until(
                EC.presence_of_element_located((By.XPATH, "//a[starts-with(@href, 'mailto:')]"))
            )
            
            email = email_link.text
            if email:
                print(f"Success! Found email: {email}")
                lead['Emails Found'] = email
            
        except Exception as e:
            print(f"Could not extract email automatically for this channel. Skipping...")
            
    driver.quit()
    
    if leads:
        keys = leads[0].keys()
        with open(output_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(leads)
            
        print(f"\nSaved updated leads to {output_csv}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Scrape hidden CAPTCHA emails for leads missing them.")
    parser.add_argument("--input", "-i", default="leads.csv", help="Input CSV file from the API extractor")
    parser.add_argument("--output", "-o", default="leads_updated.csv", help="Output CSV file to save updated emails")
    parser.add_argument("--twocaptcha", help="2Captcha API key for automated solving")
    parser.add_argument("--anticaptcha", help="Anti-Captcha API key for automated solving")
    parser.add_argument("--capsolver", help="CapSolver API key for automated solving")
    args = parser.parse_args()
    
    scrape_captcha_emails(args.input, args.output, args.twocaptcha, args.anticaptcha, args.capsolver)
