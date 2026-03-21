import csv
import time
import argparse
import sys
import urllib.parse as urlparse

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
except ImportError:
    print("Please install selenium first: pip install selenium")
    sys.exit(1)

def scrape_captcha_emails(input_csv, output_csv, twocaptcha_key=None, anticaptcha_key=None):
    # Read existing leads
    leads = []
    try:
        with open(input_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                leads.append(row)
    except FileNotFoundError:
        print(f"Error: Could not find input file '{input_csv}'")
        return
            
    # Filter leads that need emails
    needs_email = [lead for lead in leads if lead.get('Emails Found') == 'Not Found' or not lead.get('Emails Found')]
    
    if not needs_email:
        print("All leads already have emails! Nothing to do.")
        return

    print(f"Found {len(needs_email)} leads missing emails.")
    if twocaptcha_key:
        print("Starting browser... 2Captcha API key provided. Will attempt to solve CAPTCHAs automatically.")
    elif anticaptcha_key:
        print("Starting browser... Anti-Captcha API key provided. Will attempt to solve CAPTCHAs automatically.")
    else:
        print("Starting browser... NOTE: You will need to manually solve the CAPTCHA when it appears in the browser window.")
    
    # Initialize Chrome
    options = webdriver.ChromeOptions()
    # options.add_argument('--headless') # Can't use headless because user needs to solve CAPTCHA
    driver = webdriver.Chrome(options=options)
    
    for lead in needs_email:
        url = lead.get('URL')
        if not url:
            continue
            
        print(f"\nProcessing: {lead.get('Channel Name')} ({url})")
        driver.get(f"{url}/about")
        time.sleep(3) # Wait for page load
        
        try:
            # YouTube's "View email address" button can vary in structure.
            # Usually it's a button with text "View email address"
            btn_xpath = "//*[contains(text(), 'View email address')]"
            view_btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, btn_xpath)))
            view_btn.click()
            
            if twocaptcha_key or anticaptcha_key:
                print("Clicked 'View email address'. Waiting for reCAPTCHA to appear...")
                try:
                    # Wait for the reCAPTCHA iframe to appear
                    iframe = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, "//iframe[contains(@src, 'recaptcha')]"))
                    )
                    src = iframe.get_attribute("src")
                    
                    # Extract sitekey from the iframe URL
                    parsed = urlparse.urlparse(src)
                    sitekey = urlparse.parse_qs(parsed.query).get('k', [None])[0]
                    
                    if sitekey:
                        if twocaptcha_key:
                            print("Sending CAPTCHA to 2Captcha for solving (this takes 15-45 seconds)...")
                            from twocaptcha import TwoCaptcha
                            solver = TwoCaptcha(twocaptcha_key)
                            
                            result = solver.recaptcha(sitekey=sitekey, url=driver.current_url)
                            token = result['code']
                        elif anticaptcha_key:
                            print("Sending CAPTCHA to Anti-Captcha for solving (this takes 15-45 seconds)...")
                            from anticaptchaofficial.recaptchav2proxyless import recaptchaV2Proxyless
                            solver = recaptchaV2Proxyless()
                            solver.set_verbose(1)
                            solver.set_key(anticaptcha_key)
                            solver.set_website_url(driver.current_url)
                            solver.set_website_key(sitekey)
                            
                            token = solver.solve_and_return_solution()
                            if token == 0:
                                raise Exception(f"Anti-Captcha failed: {solver.error_code}")
                                
                        print("Solved! Injecting token and clicking submit...")
                        
                        # Inject the token into the hidden recaptcha textarea
                        driver.execute_script(f'document.getElementById("g-recaptcha-response").innerHTML = "{token}";')
                        
                        # Find and click the Submit button that appears under the CAPTCHA
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
            
            # Wait for the email link (mailto:) to appear
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
    
    # Save updated leads
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
    args = parser.parse_args()
    
    scrape_captcha_emails(args.input, args.output, args.twocaptcha, args.anticaptcha)
