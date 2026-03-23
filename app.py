import streamlit as st
import pandas as pd
import os
import subprocess
import tempfile
import sys
import io
import json
from youtube_lead_extractor import get_channel_leads

# Set page config
st.set_page_config(page_title="YouTube Lead Extractor", page_icon="▶️", layout="wide")

# Custom CSS for better UI
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #FF0000;
        margin-bottom: 0rem;
    }
    .sub-header {
        font-size: 1.2rem;
        color: #666;
        margin-bottom: 2rem;
    }
    .stButton>button {
        width: 100%;
        background-color: #FF0000;
        color: white;
    }
    .stButton>button:hover {
        background-color: #CC0000;
        color: white;
    }
    .success-text {
        color: #00CC00;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<p class="main-header">▶️ YouTube Lead Extractor</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">Find leads based on your ICP and extract their contact info.</p>', unsafe_allow_html=True)

is_streamlit_cloud = os.environ.get("HOME", "").startswith("/home/adminuser") or "streamlit" in os.environ.get("SERVER_SOFTWARE", "").lower()

def detect_last_used_chrome_profile():
    try:
        local_state_path = os.path.expanduser("~/Library/Application Support/Google/Chrome/Local State")
        with open(local_state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        last_used = (data.get("profile", {}) or {}).get("last_used", "")
        return last_used or "Default"
    except Exception:
        return "Default"

def detect_default_chrome_user_data_dir():
    candidates = [
        os.path.expanduser("~/Library/Application Support/Google/Chrome"),
        os.path.expanduser("~/Library/Application Support/Chromium"),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    return ""

def normalize_profile_path(text):
    v = (text or "").strip()
    if v.startswith("- "):
        v = v[2:].strip()
    v = v.strip('"').strip("'")
    return os.path.expanduser(v)

def run_email_reveal_bot(
    twocaptcha_key,
    input_csv="leads.csv",
    output_csv="leads_updated.csv",
    chrome_user_data_dir="",
    chrome_profile_dir="",
    fast_skip_seconds=6,
    email_wait_seconds=10,
    captcha_wait_seconds=20,
    max_attempts_per_channel=2,
    require_signed_in_profile=True,
):
    cmd = [sys.executable, "scrape_missing_emails.py", "--input", input_csv, "--output", output_csv]
    if twocaptcha_key:
        cmd.extend(["--twocaptcha", twocaptcha_key])
    else:
        raise Exception("No Auto-CAPTCHA API key provided for the selected service.")
    env = os.environ.copy()
    if chrome_user_data_dir:
        cmd.extend(["--chrome-user-data-dir", chrome_user_data_dir])
    if chrome_profile_dir:
        cmd.extend(["--chrome-profile-dir", chrome_profile_dir])
    if require_signed_in_profile:
        cmd.append("--require-signed-in-profile")
    env["FAST_SKIP_SECONDS"] = str(int(fast_skip_seconds))
    env["EMAIL_WAIT_SECONDS"] = str(int(email_wait_seconds))
    env["CAPTCHA_WAIT_SECONDS"] = str(int(captcha_wait_seconds))
    env["MAX_ATTEMPTS_PER_CHANNEL"] = str(int(max_attempts_per_channel))
    return cmd, env

# Sidebar for Settings
with st.sidebar:
    st.header("⚙️ Settings")
    api_key_input = st.text_input(
        "YouTube Data API v3 Key",
        type="password",
        help="Get this from Google Cloud Console",
        value=st.session_state.get("api_key", "") or os.environ.get("YOUTUBE_API_KEY", ""),
    )
    if api_key_input:
        st.session_state["api_key"] = api_key_input
        
    st.markdown("---")
    st.markdown("### 2Captcha Settings")
    twocaptcha_key_input = st.text_input(
        "2Captcha API Key",
        type="password",
        help="Get it from 2captcha.com",
        value=st.session_state.get("twocaptcha_key", "") or os.environ.get("TWOCAPTCHA_API_KEY", ""),
    )
    if twocaptcha_key_input:
        st.session_state["twocaptcha_key"] = twocaptcha_key_input
    st.markdown("---")
    st.markdown("### Signed-in Browser (Required for Step 2)")
    chrome_user_data_dir = st.text_input(
        "Chrome User Data Dir",
        value=st.session_state.get("chrome_user_data_dir", "") or os.environ.get("CHROME_USER_DATA_DIR", ""),
        help="Leave blank to auto-detect on macOS.",
    )
    chrome_profile_dir = st.text_input(
        "Chrome Profile Dir",
        value=st.session_state.get("chrome_profile_dir", "") or os.environ.get("CHROME_PROFILE_DIR", "") or detect_last_used_chrome_profile(),
        help="Leave blank to auto-detect last used profile.",
    )
    st.session_state["chrome_user_data_dir"] = chrome_user_data_dir
    st.session_state["chrome_profile_dir"] = chrome_profile_dir
    st.markdown("---")
    st.markdown("### Step 2 Speed")
    fast_skip_seconds = st.number_input("Fast Skip Seconds", min_value=2, max_value=30, value=int(st.session_state.get("fast_skip_seconds", 6)))
    email_wait_seconds = st.number_input("Email Wait Seconds", min_value=3, max_value=60, value=int(st.session_state.get("email_wait_seconds", 10)))
    captcha_wait_seconds = st.number_input("Captcha Wait Seconds", min_value=5, max_value=120, value=int(st.session_state.get("captcha_wait_seconds", 20)))
    max_attempts_per_channel = st.number_input("Max Attempts Per Channel", min_value=1, max_value=5, value=int(st.session_state.get("max_attempts_per_channel", 2)))
    st.session_state["fast_skip_seconds"] = int(fast_skip_seconds)
    st.session_state["email_wait_seconds"] = int(email_wait_seconds)
    st.session_state["captcha_wait_seconds"] = int(captcha_wait_seconds)
    st.session_state["max_attempts_per_channel"] = int(max_attempts_per_channel)
        
    st.markdown("---")
    st.markdown("### How to use:")
    st.markdown("1. Enter your API Key above.\n2. Use **Step 1** to upload your CSV/TXT file with channel links.\n3. Use **Step 2** with 2Captcha to reveal hidden emails and download updated list.")

# Check for API Key
api_key = st.session_state.get("api_key", "")

# Create tabs for the two steps
tab1, tab2 = st.tabs(["Step 1: Get Leads (API)", "Step 2: Scrape Hidden Emails (Bot)"])

with tab1:
    st.header("🔍 Get Leads")
    st.markdown("Upload a `.txt` or `.csv` file containing YouTube channel URLs. The app will extract all channel links and build `leads.csv`.")
    uploaded_file = st.file_uploader("Upload URLs file", type=['txt', 'csv'], key="upload_urls_file")
    if uploaded_file is not None:
        st.caption(f"Selected file: {uploaded_file.name}")
    submit_button = st.button("Process Uploaded URLs", key="process_uploaded_urls")

    if submit_button:
        current_api_key = st.session_state.get("api_key", "")
        if not current_api_key:
            st.error("⚠️ Please enter your YouTube API Key in the sidebar first.")
        elif uploaded_file is None:
            st.warning("Please upload a file first.")
        else:
            with st.spinner("Processing uploaded channels..."):
                file_ext = '.csv' if uploaded_file.name.endswith('.csv') else '.txt'
                tmp_dir = os.path.join(os.getcwd(), "temp_uploads")
                os.makedirs(tmp_dir, exist_ok=True)
                tmp_path = os.path.join(tmp_dir, f"uploaded_list{file_ext}")

                with open(tmp_path, 'wb') as tmp:
                    tmp.write(uploaded_file.getvalue())

                output_filename = "leads.csv"
                old_stdout = sys.stdout
                sys.stdout = mystdout = io.StringIO()

                try:
                    get_channel_leads(
                        current_api_key,
                        input_file=tmp_path,
                        output_file=output_filename,
                        scan_videos_count=0,
                        crawl_links=False,
                        crawl_max_urls=0,
                    )
                    sys.stdout = old_stdout
                    os.unlink(tmp_path)

                    output_logs = mystdout.getvalue()

                    if os.path.exists(output_filename):
                        df = pd.read_csv(output_filename)
                        if "Emails Found" in df.columns:
                            df["Public Emails Found"] = df["Emails Found"].fillna("")
                            df["Emails Found"] = "Not Found"
                            df.to_csv(output_filename, index=False)
                        st.success(f"✅ Step 1 complete. Processed {len(df)} channels.")
                        st.info("View-email-only mode active: Step 2 will process all channels for hidden email reveal.")
                        st.text("Extraction Logs:")
                        st.code(output_logs)
                        st.dataframe(df, use_container_width=True)

                        with open(output_filename, "rb") as file:
                            st.download_button(
                                label="⬇️ Download Leads CSV",
                                data=file,
                                file_name="youtube_custom_leads.csv",
                                mime="text/csv",
                            )
                    else:
                        st.warning("No leads found or error occurred.")
                        st.text(mystdout.getvalue())

                except Exception as e:
                    sys.stdout = old_stdout
                    st.error(f"An error occurred: {e}")

with tab2:
    st.header("🤖 Scrape Hidden Emails (CAPTCHA Solver)")
    if is_streamlit_cloud:
        st.error("❌ Step 2 is disabled on Streamlit Cloud.")
        st.warning("Streamlit Cloud currently fails to install a compatible Chromium build (apt dependency conflict). This is why you see errors like `libasound2t64` / broken packages.")
        st.info("Use Step 2 by running the app locally on your computer (localhost), or deploy a separate Docker worker (Render/Railway/Fly) for the scraping bot.")
    else:
        st.markdown("""
        Step 2 reads `leads.csv`, opens each channel About page, and uses **2Captcha** to solve the YouTube "View email address" CAPTCHA.
        It writes a new file `leads_updated.csv` with emails next to channels.
        """)
    
    if (not is_streamlit_cloud) and st.button("Start Browser Bot"):
        if not os.path.exists("leads.csv"):
            st.error("⚠️ 'leads.csv' not found. Please run Step 1 first.")
        else:
            df_check = pd.read_csv("leads.csv")
            missing = df_check[df_check['Emails Found'].isna() | (df_check['Emails Found'] == 'Not Found')]
            
            if len(missing) == 0:
                st.info("✅ All leads in your file already have emails! Nothing to do.")
            else:
                st.warning(f"Found {len(missing)} leads missing emails. Starting browser...")
                
                twocaptcha_key = st.session_state.get("twocaptcha_key", "")
                if not twocaptcha_key:
                    st.error("⚠️ Please enter your 2Captcha API Key in the sidebar before starting Step 2.")
                    st.stop()
                profile_user_data_dir = normalize_profile_path(st.session_state.get("chrome_user_data_dir", "")) or detect_default_chrome_user_data_dir()
                profile_dir = (st.session_state.get("chrome_profile_dir", "") or "").strip()
                if profile_dir.startswith("- "):
                    profile_dir = profile_dir[2:].strip()
                profile_dir = profile_dir.strip('"').strip("'") or detect_last_used_chrome_profile()
                st.session_state["chrome_user_data_dir"] = profile_user_data_dir
                st.session_state["chrome_profile_dir"] = profile_dir
                if not profile_user_data_dir or not profile_dir:
                    st.error("⚠️ Could not auto-detect a Chrome profile. Please set Chrome User Data Dir and Chrome Profile Dir.")
                    st.stop()
                if not os.path.isdir(profile_user_data_dir):
                    st.error(f"⚠️ Chrome User Data Dir not found: {profile_user_data_dir}")
                    st.stop()
                if not os.path.isdir(os.path.join(profile_user_data_dir, profile_dir)):
                    st.error(f"⚠️ Chrome profile folder not found: {os.path.join(profile_user_data_dir, profile_dir)}")
                    st.stop()
                if sys.platform == "darwin":
                    lock_candidates = [
                        os.path.join(profile_user_data_dir, "SingletonLock"),
                        os.path.join(profile_user_data_dir, "SingletonCookie"),
                        os.path.join(profile_user_data_dir, "SingletonSocket"),
                    ]
                    if any(os.path.exists(p) for p in lock_candidates):
                        st.error("⚠️ Chrome is currently running. Close all Chrome windows, then retry Step 2.")
                        st.stop()
                st.info(f"Using signed-in Chrome profile: {profile_dir}")
                st.info("🤖 2Captcha key detected. Running auto reveal...")
                spinner_text = "Bot is running... moving channel by channel."
                
                with st.spinner(spinner_text):
                    try:
                        cmd, env = run_email_reveal_bot(
                            twocaptcha_key,
                            input_csv="leads.csv",
                            output_csv="leads_updated.csv",
                            chrome_user_data_dir=st.session_state.get("chrome_user_data_dir", ""),
                            chrome_profile_dir=st.session_state.get("chrome_profile_dir", ""),
                            fast_skip_seconds=st.session_state.get("fast_skip_seconds", 6),
                            email_wait_seconds=st.session_state.get("email_wait_seconds", 10),
                            captcha_wait_seconds=st.session_state.get("captcha_wait_seconds", 20),
                            max_attempts_per_channel=st.session_state.get("max_attempts_per_channel", 2),
                            require_signed_in_profile=True,
                        )
                            
                        process = subprocess.Popen(
                            cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                            env=env
                        )
                        
                        log_placeholder = st.empty()
                        logs = []
                        
                        for line in process.stdout:
                            logs.append(line.strip())
                            if len(logs) > 10:
                                logs.pop(0)
                            log_placeholder.code('\n'.join(logs))
                            
                        process.wait()
                        
                        if os.path.exists("leads_updated.csv"):
                            st.success("✅ Finished scraping! Check the results below.")
                            df_updated = pd.read_csv("leads_updated.csv")
                            st.dataframe(df_updated, use_container_width=True)
                            
                            with open("leads_updated.csv", "rb") as file:
                                st.download_button(
                                    label="⬇️ Download Updated Leads CSV",
                                    data=file,
                                    file_name="youtube_leads_updated.csv",
                                    mime="text/csv",
                                )
                                
                    except Exception as e:
                        st.error(f"Error running bot: {e}")
