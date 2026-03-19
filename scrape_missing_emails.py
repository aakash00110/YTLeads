import csv
import time
import argparse
import sys
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
except ImportError:
    print("Please install selenium first: pip install selenium")
    sys.exit(1)

def scrape_captcha_emails(input_csv, output_csv):
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
    args = parser.parse_args()
    
    scrape_captcha_emails(args.input, args.output)
