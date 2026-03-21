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

# Sidebar for Settings
with st.sidebar:
    st.header("⚙️ Settings")
    api_key_input = st.text_input("YouTube Data API v3 Key", type="password", help="Get this from Google Cloud Console", value=st.session_state.get("api_key", ""))
    if api_key_input:
        st.session_state["api_key"] = api_key_input
        
    st.markdown("---")
    st.markdown("### Auto-CAPTCHA Settings")
    captcha_service = st.selectbox("CAPTCHA Service", ["CapSolver", "Anti-Captcha", "2Captcha", "None (Manual)"], index=0)
    
    if captcha_service == "2Captcha":
        twocaptcha_key_input = st.text_input("2Captcha API Key", type="password", help="Get it from 2captcha.com", value=st.session_state.get("twocaptcha_key", ""))
        if twocaptcha_key_input:
            st.session_state["twocaptcha_key"] = twocaptcha_key_input
    elif captcha_service == "Anti-Captcha":
        anticaptcha_key_input = st.text_input("Anti-Captcha API Key", type="password", help="Get it from anti-captcha.com", value=st.session_state.get("anticaptcha_key", ""))
        if anticaptcha_key_input:
            st.session_state["anticaptcha_key"] = anticaptcha_key_input
    elif captcha_service == "CapSolver":
        capsolver_key_input = st.text_input("CapSolver API Key", type="password", help="Get it from capsolver.com", value=st.session_state.get("capsolver_key", ""))
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
                        get_channel_leads(current_api_key, query=query, max_results=max_results, output_file=output_filename)
                        sys.stdout = old_stdout
                        
                        if os.path.exists(output_filename):
                            df = pd.read_csv(output_filename)
                            st.success(f"✅ Successfully found and processed {len(df)} leads!")
                            st.dataframe(df, use_container_width=True)
                            
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
        
        with st.form("upload_form"):
            uploaded_file = st.file_uploader("Upload URLs file", type=['txt', 'csv'])
            submit_button = st.form_submit_button("Process Uploaded URLs")
            
        if submit_button:
            # Get the latest api_key from the sidebar input
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
                        get_channel_leads(current_api_key, input_file=tmp_path, output_file=output_filename)
                        sys.stdout = old_stdout
                        os.unlink(tmp_path)
                        
                        output_logs = mystdout.getvalue()
                        
                        if os.path.exists(output_filename):
                            df = pd.read_csv(output_filename)
                            st.success(f"✅ Successfully processed {len(df)} uploaded leads!")
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
