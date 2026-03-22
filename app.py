import streamlit as st
import pandas as pd
import os
import subprocess
import tempfile
import sys
import io
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

def run_email_reveal_bot(captcha_service, twocaptcha_key="", anticaptcha_key="", capsolver_key="", input_csv="leads.csv", output_csv="leads_updated.csv"):
    cmd = [sys.executable, "scrape_missing_emails.py", "--input", input_csv, "--output", output_csv]
    if captcha_service == "2Captcha" and twocaptcha_key:
        cmd.extend(["--twocaptcha", twocaptcha_key])
    elif captcha_service == "Anti-Captcha" and anticaptcha_key:
        cmd.extend(["--anticaptcha", anticaptcha_key])
    elif captcha_service == "CapSolver" and capsolver_key:
        cmd.extend(["--capsolver", capsolver_key])
    else:
        raise Exception("No Auto-CAPTCHA API key provided for the selected service.")
    return cmd

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
    st.markdown("### Auto-CAPTCHA Settings")
    captcha_service = st.selectbox("CAPTCHA Service", ["CapSolver", "Anti-Captcha", "2Captcha", "None (Manual)"], index=0)
    
    if captcha_service == "2Captcha":
        twocaptcha_key_input = st.text_input(
            "2Captcha API Key",
            type="password",
            help="Get it from 2captcha.com",
            value=st.session_state.get("twocaptcha_key", "") or os.environ.get("TWOCAPTCHA_API_KEY", ""),
        )
        if twocaptcha_key_input:
            st.session_state["twocaptcha_key"] = twocaptcha_key_input
    elif captcha_service == "Anti-Captcha":
        anticaptcha_key_input = st.text_input(
            "Anti-Captcha API Key",
            type="password",
            help="Get it from anti-captcha.com",
            value=st.session_state.get("anticaptcha_key", "") or os.environ.get("ANTICAPTCHA_API_KEY", ""),
        )
        if anticaptcha_key_input:
            st.session_state["anticaptcha_key"] = anticaptcha_key_input
    elif captcha_service == "CapSolver":
        capsolver_key_input = st.text_input(
            "CapSolver API Key",
            type="password",
            help="Get it from capsolver.com",
            value=st.session_state.get("capsolver_key", "") or os.environ.get("CAPSOLVER_API_KEY", ""),
        )
        if capsolver_key_input:
            st.session_state["capsolver_key"] = capsolver_key_input
        
    st.markdown("---")
    st.markdown("### How to use:")
    st.markdown("1. Enter your API Key above.\n2. Use **Step 1** to search by ICP or upload your own URLs.\n3. Use **Step 2** to solve CAPTCHAs for hidden emails.")

# Check for API Key
api_key = st.session_state.get("api_key", "")

# Create tabs for the two steps
tab1, tab2 = st.tabs(["Step 1: Get Leads (API)", "Step 2: Scrape Hidden Emails (Bot)"])

with tab1:
    st.header("🔍 Get Leads")
    
    input_method = st.radio("How do you want to get leads?", ["Search by ICP", "Upload my own list (.txt or .csv)"], horizontal=True)
    
    if input_method == "Search by ICP":
        col1, col2 = st.columns([3, 1])
        with col1:
            query = st.text_input("Ideal Customer Profile (ICP) Search Query", placeholder="e.g. Life advice coach, fitness tech reviewer")
        with col2:
            # Increased max value to 1000
            max_results = st.number_input("Max Results", min_value=1, max_value=1000, value=50, help="YouTube Search API supports fetching up to ~500-1000 results per query via pagination.")
        
        adv1, adv2 = st.columns(2)
        with adv1:
            crawl_links = st.checkbox("Crawl Links", value=True, help="Fetch external links from channel description and scan for emails.")
        with adv2:
            crawl_max_urls = st.number_input("Max Link Fetches", min_value=0, max_value=10, value=3, help="Max external pages fetched per channel.")

        auto_reveal = st.checkbox("Captcha Priority (Auto Reveal Emails)", value=True, help="After Step 1 finishes, automatically run the email reveal bot for remaining Not Found emails.")
            
        if st.button("Start Search"):
            current_api_key = st.session_state.get("api_key", "")
            if not current_api_key:
                st.error("⚠️ Please enter your YouTube API Key in the sidebar first.")
            elif not query:
                st.warning("Please enter a search query.")
            else:
                with st.spinner(f"Searching YouTube for '{query}' (Targeting {max_results} results, this may take a moment)..."):
                    output_filename = "leads.csv"
                    old_stdout = sys.stdout
                    sys.stdout = mystdout = io.StringIO()
                    
                    try:
                        get_channel_leads(
                            current_api_key,
                            query=query,
                            max_results=max_results,
                            output_file=output_filename,
                            scan_videos_count=0,
                            crawl_links=bool(crawl_links),
                            crawl_max_urls=int(crawl_max_urls),
                        )
                        sys.stdout = old_stdout
                        
                        if os.path.exists(output_filename):
                            df = pd.read_csv(output_filename)
                            st.success(f"✅ Successfully found and processed {len(df)} leads!")
                            st.dataframe(df, use_container_width=True)

                            if auto_reveal:
                                if is_streamlit_cloud:
                                    st.error("Captcha Priority cannot run on Streamlit Cloud. Use localhost.")
                                else:
                                    twocaptcha_key = st.session_state.get("twocaptcha_key", "") if captcha_service == "2Captcha" else ""
                                    anticaptcha_key = st.session_state.get("anticaptcha_key", "") if captcha_service == "Anti-Captcha" else ""
                                    capsolver_key = st.session_state.get("capsolver_key", "") if captcha_service == "CapSolver" else ""
                                    with st.spinner("Running CAPTCHA email reveal for missing emails..."):
                                        cmd = run_email_reveal_bot(
                                            captcha_service,
                                            twocaptcha_key=twocaptcha_key,
                                            anticaptcha_key=anticaptcha_key,
                                            capsolver_key=capsolver_key,
                                            input_csv=output_filename,
                                            output_csv="leads_updated.csv",
                                        )
                                        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                                        log_placeholder = st.empty()
                                        logs = []
                                        for line in process.stdout:
                                            logs.append(line.strip())
                                            if len(logs) > 12:
                                                logs.pop(0)
                                            log_placeholder.code("\n".join(logs))
                                        process.wait()
                                        if os.path.exists("leads_updated.csv"):
                                            df_updated = pd.read_csv("leads_updated.csv")
                                            st.success("✅ Auto reveal finished. Updated results:")
                                            st.dataframe(df_updated, use_container_width=True)
                                            with open("leads_updated.csv", "rb") as file:
                                                st.download_button(
                                                    label="⬇️ Download Updated Leads CSV",
                                                    data=file,
                                                    file_name="youtube_leads_updated.csv",
                                                    mime="text/csv",
                                                )
                            
                            with open(output_filename, "rb") as file:
                                st.download_button(
                                    label="⬇️ Download Leads CSV",
                                    data=file,
                                    file_name="youtube_leads.csv",
                                    mime="text/csv",
                                )
                        else:
                            st.warning("No leads found or error occurred.")
                            st.text(mystdout.getvalue())
                            
                    except Exception as e:
                        sys.stdout = old_stdout
                        st.error(f"An error occurred: {e}")
                        
    else:
        st.markdown("Upload a `.txt` or `.csv` file containing YouTube channel URLs. If using CSV, the script will automatically find any column containing YouTube links.")
        
        uploaded_file = st.file_uploader("Upload URLs file", type=['txt', 'csv'], key="upload_urls_file")
        if uploaded_file is not None:
            st.caption(f"Selected file: {uploaded_file.name}")
            
        adv1, adv2 = st.columns(2)
        with adv1:
            crawl_links_upload = st.checkbox("Crawl Links (Upload)", value=True, help="Fetch external links from channel description and scan for emails.", key="crawl_links_upload")
        with adv2:
            crawl_max_urls_upload = st.number_input("Max Link Fetches (Upload)", min_value=0, max_value=10, value=3, help="Max external pages fetched per channel.", key="crawl_max_urls_upload")

        auto_reveal_upload = st.checkbox("Captcha Priority (Auto Reveal Emails) (Upload)", value=True, help="After processing upload, automatically run email reveal for missing emails.", key="auto_reveal_upload")
        submit_button = st.button("Process Uploaded URLs", key="process_uploaded_urls")

        if submit_button:
            current_api_key = st.session_state.get("api_key", "")
            if not current_api_key:
                st.error("⚠️ Please enter your YouTube API Key in the sidebar first.")
            elif uploaded_file is None:
                st.warning("Please upload a file first.")
            else:
                with st.spinner("Processing your URLs..."):
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
                            crawl_links=bool(crawl_links_upload),
                            crawl_max_urls=int(crawl_max_urls_upload),
                        )
                        sys.stdout = old_stdout
                        os.unlink(tmp_path)
                        
                        output_logs = mystdout.getvalue()
                        
                        if os.path.exists(output_filename):
                            df = pd.read_csv(output_filename)
                            st.success(f"✅ Successfully processed {len(df)} uploaded leads!")
                            st.text("Extraction Logs:")
                            st.code(output_logs)
                            st.dataframe(df, use_container_width=True)

                            if auto_reveal_upload:
                                if is_streamlit_cloud:
                                    st.error("Captcha Priority cannot run on Streamlit Cloud. Use localhost.")
                                else:
                                    twocaptcha_key = st.session_state.get("twocaptcha_key", "") if captcha_service == "2Captcha" else ""
                                    anticaptcha_key = st.session_state.get("anticaptcha_key", "") if captcha_service == "Anti-Captcha" else ""
                                    capsolver_key = st.session_state.get("capsolver_key", "") if captcha_service == "CapSolver" else ""
                                    with st.spinner("Running CAPTCHA email reveal for missing emails..."):
                                        cmd = run_email_reveal_bot(
                                            captcha_service,
                                            twocaptcha_key=twocaptcha_key,
                                            anticaptcha_key=anticaptcha_key,
                                            capsolver_key=capsolver_key,
                                            input_csv=output_filename,
                                            output_csv="leads_updated.csv",
                                        )
                                        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                                        log_placeholder = st.empty()
                                        logs = []
                                        for line in process.stdout:
                                            logs.append(line.strip())
                                            if len(logs) > 12:
                                                logs.pop(0)
                                            log_placeholder.code("\n".join(logs))
                                        process.wait()
                                        if os.path.exists("leads_updated.csv"):
                                            df_updated = pd.read_csv("leads_updated.csv")
                                            st.success("✅ Auto reveal finished. Updated results:")
                                            st.dataframe(df_updated, use_container_width=True)
                                            with open("leads_updated.csv", "rb") as file:
                                                st.download_button(
                                                    label="⬇️ Download Updated Leads CSV",
                                                    data=file,
                                                    file_name="youtube_custom_leads_updated.csv",
                                                    mime="text/csv",
                                                )
                            
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
        If your `leads.csv` has channels with **"Not Found"** in the email column, this bot will open Chrome and click the "View email address" button. 
        If you selected an **Auto-CAPTCHA Service** in the sidebar, it will automatically solve the CAPTCHA for you! Otherwise, you will need to click it manually.
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
                
                twocaptcha_key = st.session_state.get("twocaptcha_key", "") if captcha_service == "2Captcha" else ""
                anticaptcha_key = st.session_state.get("anticaptcha_key", "") if captcha_service == "Anti-Captcha" else ""
                capsolver_key = st.session_state.get("capsolver_key", "") if captcha_service == "CapSolver" else ""
                
                if twocaptcha_key or anticaptcha_key or capsolver_key:
                    st.info(f"🤖 {captcha_service} API Key detected! Running invisibly in the background to auto-solve CAPTCHAs. Please wait...")
                    spinner_text = "Bot is running invisibly in the background... Please wait!"
                else:
                    # BLOCK MANUAL MODE ON CLOUD
                    if "streamlit" in os.environ.get("SERVER_SOFTWARE", "").lower() or sys.platform.startswith('linux'):
                        st.error("❌ **Manual mode is blocked on Streamlit Cloud.**")
                        st.warning("Because this app is running on a cloud server without a screen, it cannot physically pop open a Chrome window for you to click the CAPTCHA. \n\n**To use this website, you MUST select 'Anti-Captcha' or '2Captcha' in the sidebar and provide an API key.** \n\n*(If you want to use manual mode for free, you must run this code locally on your own Mac/PC).*")
                        st.stop()
                    else:
                        st.info("💡 No Auto-CAPTCHA API Key provided. A physical Chrome window will pop up shortly. Please solve the CAPTCHA manually when prompted.")
                        spinner_text = "Bot is launching... Check your computer for the Chrome window!"
                
                with st.spinner(spinner_text):
                    try:
                        cmd = [sys.executable, "scrape_missing_emails.py"]
                        if twocaptcha_key:
                            cmd.extend(["--twocaptcha", twocaptcha_key])
                        elif anticaptcha_key:
                            cmd.extend(["--anticaptcha", anticaptcha_key])
                        elif capsolver_key:
                            cmd.extend(["--capsolver", capsolver_key])
                            
                        process = subprocess.Popen(
                            cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True
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
