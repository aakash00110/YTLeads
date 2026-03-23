import os
import re
import csv
import argparse
import time
import urllib.parse
import requests
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

EMAIL_REGEX = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'

URL_REGEX = r'(?:(?:https?://)|(?:www\.))[^\s<>\]\)"]+'

OBF_AT = r'(?:\(|\[|\{)?\s*at\s*(?:\)|\]|\})?'
OBF_DOT = r'(?:\(|\[|\{)?\s*dot\s*(?:\)|\]|\})?'
PUBLIC_EMAIL_PROVIDERS = {
    "gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com",
    "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com", "gmx.com", "yandex.com"
}

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

def _email_domain(email):
    try:
        return email.rsplit("@", 1)[1].lower()
    except Exception:
        return ""

def _root_domain(host_or_domain):
    if not host_or_domain:
        return ""
    h = host_or_domain.lower().split(":")[0].strip(".")
    if h.startswith("www."):
        h = h[4:]
    parts = [p for p in h.split(".") if p]
    if len(parts) < 2:
        return h
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in {"co", "com", "org", "net", "gov", "edu"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])

def _domains_from_urls(urls):
    out = set()
    for u in urls or []:
        try:
            netloc = urllib.parse.urlparse(u).netloc
            rd = _root_domain(netloc)
            if rd:
                out.add(rd)
        except Exception:
            continue
    return out

def _score_email(email, company_domains):
    domain = _email_domain(email)
    if not domain:
        return 0, "invalid"
    root = _root_domain(domain)
    if root in company_domains:
        return 100, "company_domain_match"
    if domain in PUBLIC_EMAIL_PROVIDERS:
        return 80, "public_mail_provider"
    return 85, "custom_domain"

def _rank_emails(emails, company_domains):
    scored = []
    for e in sorted(set(emails)):
        if not is_valid_email(e):
            continue
        score, tag = _score_email(e, company_domains)
        scored.append((score, tag, e))
    scored.sort(key=lambda x: (-x[0], x[2]))
    return scored

def _extract_obfuscated_emails(text):
    if not text:
        return []
    matches = []
    pattern = re.compile(
        r'(?i)(?<![a-z0-9])'
        r'([a-z0-9][a-z0-9._%+-]{0,63})'
        r'\s*' + OBF_AT + r'\s*'
        r'([a-z0-9][a-z0-9.-]{0,251})'
        r'(?:\s*' + OBF_DOT + r'\s*([a-z]{2,24}))'
        r'(?:\s*' + OBF_DOT + r'\s*([a-z]{2,24}))?'
        r'(?![a-z0-9])'
    )
    for m in pattern.finditer(text):
        local = m.group(1)
        domain = m.group(2)
        tld1 = m.group(3)
        tld2 = m.group(4)
        if not tld1:
            continue
        email = f"{local}@{domain}.{tld1}"
        if tld2:
            email = f"{email}.{tld2}"
        matches.append(email)
    return matches

def extract_emails(text):
    t = (text or "").replace('mailto:', '')
    emails = set()
    for e in re.findall(EMAIL_REGEX, t):
        e = e.strip().strip('.,;:()[]{}<>')
        if e and is_valid_email(e):
            emails.add(e)
    for e in _extract_obfuscated_emails(t):
        e = e.strip().strip('.,;:()[]{}<>')
        if e and is_valid_email(e):
            emails.add(e)
    return sorted(emails)

def extract_urls(text):
    if not text:
        return []
    candidates = re.findall(URL_REGEX, text, flags=re.IGNORECASE)
    urls = []
    for c in candidates:
        u = c.strip().strip('.,;:()[]{}<>')
        if u.lower().startswith('www.'):
            u = 'https://' + u
        try:
            parsed = urllib.parse.urlparse(u)
            if parsed.scheme in ('http', 'https') and parsed.netloc:
                urls.append(u)
        except Exception:
            continue
    return sorted(set(urls))

def _is_youtube_domain(url):
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return False
    return host.endswith("youtube.com") or host.endswith("youtu.be") or host.endswith("music.youtube.com")

def _extract_same_domain_links(base_url, html_text):
    if not html_text:
        return []
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', html_text, flags=re.IGNORECASE)
    parsed_base = urllib.parse.urlparse(base_url)
    base_domain = parsed_base.netloc.lower()
    candidates = []
    for href in hrefs:
        try:
            full = urllib.parse.urljoin(base_url, href.strip())
            p = urllib.parse.urlparse(full)
            if p.scheme not in ("http", "https"):
                continue
            if p.netloc.lower() != base_domain:
                continue
            low = full.lower()
            if any(k in low for k in ["/contact", "/about", "/reach", "/team", "/support", "/business"]):
                candidates.append(full.split("#")[0])
        except Exception:
            continue
    return sorted(set(candidates))

def crawl_urls_for_emails(urls, max_urls=3, timeout_s=12, max_bytes=1_000_000):
    found = set()
    picked = [u for u in urls if not _is_youtube_domain(u)]
    picked = picked[:max_urls]
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    for u in picked:
        try:
            resp = requests.get(u, headers=headers, timeout=timeout_s, allow_redirects=True, stream=True)
            resp.raise_for_status()
            content = b""
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    break
                content += chunk
                if len(content) >= max_bytes:
                    break
            text = content.decode(resp.encoding or "utf-8", errors="replace")
            for e in extract_emails(text):
                found.add(e)

            extra_links = _extract_same_domain_links(resp.url, text)[:3]
            for ex in extra_links:
                try:
                    ex_resp = requests.get(ex, headers=headers, timeout=timeout_s)
                    ex_resp.raise_for_status()
                    ex_text = ex_resp.text or ""
                    for e in extract_emails(ex_text):
                        found.add(e)
                except Exception:
                    continue
        except Exception:
            continue
        time.sleep(0.5)
    return sorted(found)

def _get_uploads_playlist_id(channel_item):
    try:
        return channel_item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    except Exception:
        return None

def scan_recent_videos_for_emails(youtube, uploads_playlist_id, max_videos=10):
    if not uploads_playlist_id or max_videos <= 0:
        return [], []
    video_ids = []
    next_token = None
    while len(video_ids) < max_videos:
        fetch_count = min(50, max_videos - len(video_ids))
        resp = youtube.playlistItems().list(
            playlistId=uploads_playlist_id,
            part="contentDetails",
            maxResults=fetch_count,
            pageToken=next_token,
        ).execute()
        for item in resp.get("items", []):
            vid = item.get("contentDetails", {}).get("videoId")
            if vid:
                video_ids.append(vid)
        next_token = resp.get("nextPageToken")
        if not next_token:
            break
    if not video_ids:
        return [], []
    emails = set()
    urls = set()
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        vresp = youtube.videos().list(id=",".join(batch), part="snippet").execute()
        for v in vresp.get("items", []):
            desc = v.get("snippet", {}).get("description", "")
            for e in extract_emails(desc):
                emails.add(e)
            for u in extract_urls(desc):
                urls.add(u)
    return sorted(emails), sorted(urls)

def process_channels(youtube, channel_ids=None, handles=None, usernames=None, scan_videos_count=0, crawl_links=False, crawl_max_urls=3):
    leads = []
    try:
        items = []
        seen_ids = set()

        if channel_ids:
            for i in range(0, len(channel_ids), 50):
                batch = [b for b in channel_ids[i:i+50] if b and re.fullmatch(r'[A-Za-z0-9_-]{10,40}', b)]
                if not batch:
                    continue
                try:
                    resp = youtube.channels().list(id=",".join(batch), part="snippet,statistics,contentDetails").execute()
                    for it in resp.get("items", []):
                        cid = it.get("id")
                        if cid and cid not in seen_ids:
                            seen_ids.add(cid)
                            items.append(it)
                except HttpError:
                    for cid in batch:
                        try:
                            r = youtube.channels().list(id=cid, part="snippet,statistics,contentDetails").execute()
                            for it in r.get("items", []):
                                rcid = it.get("id")
                                if rcid and rcid not in seen_ids:
                                    seen_ids.add(rcid)
                                    items.append(it)
                        except HttpError:
                            continue

        if handles:
            for handle in handles:
                h = str(handle or "").strip()
                if not h:
                    continue
                if not h.startswith("@"):
                    h = "@" + h
                h = "@" + h[1:].split("/")[0].split("?")[0].strip()
                if not re.fullmatch(r'@[A-Za-z0-9._-]{2,60}', h):
                    continue
                try:
                    resp = youtube.channels().list(forHandle=h, part="snippet,statistics,contentDetails").execute()
                    for it in resp.get("items", []):
                        cid = it.get("id")
                        if cid and cid not in seen_ids:
                            seen_ids.add(cid)
                            items.append(it)
                except HttpError:
                    continue

        if usernames:
            for un in usernames:
                u = str(un or "").strip().split("/")[0].split("?")[0].strip()
                if not re.fullmatch(r'[A-Za-z0-9._-]{2,80}', u):
                    continue
                try:
                    resp = youtube.channels().list(forUsername=u, part="snippet,statistics,contentDetails").execute()
                    for it in resp.get("items", []):
                        cid = it.get("id")
                        if cid and cid not in seen_ids:
                            seen_ids.add(cid)
                            items.append(it)
                except HttpError:
                    continue

        for channel in items:
            title = channel.get("snippet", {}).get("title", "Unknown")
            desc = channel.get("snippet", {}).get("description", "")
            cid = channel.get("id")
            curl = channel.get("snippet", {}).get("customUrl", "")
            url = f"https://www.youtube.com/{curl}" if curl else f"https://www.youtube.com/channel/{cid}"

            subs = channel.get("statistics", {}).get("subscriberCount", "0")
            views = channel.get("statistics", {}).get("viewCount", "0")

            emails = set(extract_emails(desc))
            urls = set(extract_urls(desc))
            sources = set()
            if emails:
                sources.add("channel_description")

            if scan_videos_count and scan_videos_count > 0:
                uploads_id = _get_uploads_playlist_id(channel)
                ve, vu = scan_recent_videos_for_emails(youtube, uploads_id, max_videos=scan_videos_count)
                for e in ve:
                    emails.add(e)
                for u in vu:
                    urls.add(u)
                if ve:
                    sources.add("video_descriptions")

            if crawl_links:
                crawled_emails = crawl_urls_for_emails(sorted(urls), max_urls=crawl_max_urls)
                for e in crawled_emails:
                    emails.add(e)
                if crawled_emails:
                    sources.add("external_links")

            company_domains = _domains_from_urls(urls)
            ranked = _rank_emails(emails, company_domains)
            ranked_emails = [e for _, _, e in ranked]
            verification_tags = sorted(set(tag for _, tag, _ in ranked))
            top_email = ranked_emails[0] if ranked_emails else ""

            leads.append({
                "Channel Name": title,
                "URL": url,
                "Subscribers": subs,
                "Total Views": views,
                "Emails Found": ", ".join(ranked_emails) if ranked_emails else "Not Found",
                "Primary Email": top_email,
                "Email Verification": "; ".join(verification_tags),
                "Email Sources": "; ".join(sorted(sources)) if sources else "",
                "Description Snippet": desc[:100].replace("\n", " ") + "..." if desc else "",
            })
    except HttpError as e:
        print(f"API Error: {e}")
    return leads

def get_channel_leads(api_key, query=None, input_file=None, max_results=10, output_file="leads.csv", scan_videos_count=0, crawl_links=False, crawl_max_urls=3):
    youtube = build('youtube', 'v3', developerKey=api_key)
    all_leads = []
    
    if query:
        print(f"Searching for channels related to your ICP: '{query}'... (Target: {max_results})")
        cids = []
        next_page_token = None
        
        while len(cids) < max_results:
            fetch_count = min(50, max_results - len(cids))
            req = youtube.search().list(
                q=query, 
                type='channel', 
                part='id', 
                maxResults=fetch_count,
                pageToken=next_page_token
            )
            search_response = req.execute()
            
            new_cids = [item['id']['channelId'] for item in search_response.get('items', [])]
            cids.extend(new_cids)
            
            next_page_token = search_response.get('nextPageToken')
            if not next_page_token or not new_cids:
                break
                
        cids = cids[:max_results]
        
        if cids:
            print(f"Found {len(cids)} channels. Fetching details...")
            all_leads.extend(process_channels(youtube, channel_ids=cids, scan_videos_count=scan_videos_count, crawl_links=crawl_links, crawl_max_urls=crawl_max_urls))
            
    if input_file:
        print(f"Reading existing URLs from {input_file}...")
        urls = []
        if input_file.endswith('.csv'):
            try:
                # Try reading with different encodings if standard utf-8 fails
                with open(input_file, 'r', encoding='utf-8', errors='replace') as f:
                    # Use a basic split instead of strict csv.reader to handle poorly formatted CSVs
                    for line in f:
                        cols = line.split(',')
                        for col in cols:
                            col_str = str(col).strip()
                            if 'youtube.com/' in col_str or 'youtu.be/' in col_str:
                                if 'http' in col_str:
                                    start_idx = col_str.find('http')
                                    # Try to split by common delimiters that might trail a URL
                                    url_candidate = col_str[start_idx:].replace('"', '').replace("'", "").split()[0]
                                    urls.append(url_candidate)
                                else:
                                    urls.append(col_str.replace('"', '').replace("'", ""))
            except Exception as e:
                print(f"Error reading CSV: {e}")
        else:
            with open(input_file, 'r', encoding='utf-8', errors='ignore') as f:
                urls = [line.strip() for line in f if line.strip()]
        
        cleaned_urls = []
        seen = set()
        for u in urls:
            su = str(u or "").strip().replace('"', '').replace("'", "")
            if not su:
                continue
            if su.startswith("www."):
                su = "https://" + su
            if "youtube.com/" not in su and "youtu.be/" not in su:
                continue
            su = su.split()[0]
            if su not in seen:
                seen.add(su)
                cleaned_urls.append(su)
        urls = cleaned_urls
        print(f"Successfully extracted {len(urls)} unique YouTube URLs from the file.")
        
        cids, handles, usernames = [], [], []
        for url in urls:
            if '/channel/' in url:
                cid = url.split('/channel/')[-1].split('/')[0].split('?')[0]
                cids.append(cid)
            elif '/@' in url:
                handle = '@' + url.split('/@')[-1].split('/')[0].split('?')[0]
                handles.append(handle)
            elif '/user/' in url:
                uname = url.split('/user/')[-1].split('/')[0].split('?')[0]
                usernames.append(uname)
        
        print(f"Processing {len(urls)} existing channels...")
        all_leads.extend(process_channels(youtube, channel_ids=cids, handles=handles, usernames=usernames, scan_videos_count=scan_videos_count, crawl_links=crawl_links, crawl_max_urls=crawl_max_urls))
        
    if not all_leads:
        print("No leads generated.")
        return

    # Save to CSV
    keys = all_leads[0].keys()
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(all_leads)
        
    print(f"\nSuccessfully saved {len(all_leads)} leads to {output_file}")
    for lead in all_leads[:5]:
        print(f"- {lead['Channel Name']} | Subs: {lead['Subscribers']} | Email: {lead['Emails Found']}")
    if len(all_leads) > 5: print("...")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Extract YouTube Channel Leads")
    parser.add_argument("--query", "-q", help="Search query for ICP")
    parser.add_argument("--input", "-i", help="Text file containing list of existing YouTube URLs (one per line)")
    parser.add_argument("--max_results", "-m", type=int, default=10, help="Max results for search")
    parser.add_argument("--output", "-o", default="leads.csv", help="Output CSV filename")
    parser.add_argument("--scan_videos", type=int, default=0, help="Scan recent videos per channel for emails (0 disables)")
    parser.add_argument("--crawl_links", action="store_true", help="Fetch external links from descriptions and scan for emails")
    parser.add_argument("--crawl_max_urls", type=int, default=3, help="Max external URLs to fetch per channel (when --crawl_links)")
    args = parser.parse_args()
    
    if not args.query and not args.input:
        parser.error("Must provide either --query or --input")
        
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("ERROR: Set YOUTUBE_API_KEY env variable.")
        exit(1)
        
    get_channel_leads(api_key, args.query, args.input, args.max_results, args.output, scan_videos_count=args.scan_videos, crawl_links=args.crawl_links, crawl_max_urls=args.crawl_max_urls)
