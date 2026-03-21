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

def _normalize_text_for_email_search(text):
    if not text:
        return ""
    t = text
    t = re.sub(r'\s*(?:\(|\[)?\s*at\s*(?:\)|\])?\s*', '@', t, flags=re.IGNORECASE)
    t = re.sub(r'\s*(?:\(|\[)?\s*dot\s*(?:\)|\])?\s*', '.', t, flags=re.IGNORECASE)
    t = re.sub(r'\s*@\s*', '@', t)
    t = re.sub(r'\s*\.\s*', '.', t)
    t = t.replace('mailto:', '')
    return t

def extract_emails(text):
    t = _normalize_text_for_email_search(text or "")
    emails = re.findall(EMAIL_REGEX, t)
    return sorted(set(e.strip().strip('.,;:()[]{}<>') for e in emails if e))

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
        if channel_ids:
            for i in range(0, len(channel_ids), 50):
                batch = channel_ids[i:i+50]
                resp = youtube.channels().list(id=",".join(batch), part="snippet,statistics,contentDetails").execute()
                items.extend(resp.get("items", []))

        if handles:
            for handle in handles:
                resp = youtube.channels().list(forHandle=handle, part="snippet,statistics,contentDetails").execute()
                items.extend(resp.get("items", []))

        if usernames:
            for un in usernames:
                resp = youtube.channels().list(forUsername=un, part="snippet,statistics,contentDetails").execute()
                items.extend(resp.get("items", []))

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

            leads.append({
                "Channel Name": title,
                "URL": url,
                "Subscribers": subs,
                "Total Views": views,
                "Emails Found": ", ".join(sorted(emails)) if emails else "Not Found",
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
        
        # Remove duplicates
        urls = list(set(urls))
        print(f"Successfully extracted {len(urls)} unique YouTube URLs from the file.")
        
        cids, handles, usernames = [], [], []
        for url in urls:
            if '/channel/' in url:
                cids.append(url.split('/channel/')[-1].split('/')[0])
            elif '/@' in url:
                handles.append('@' + url.split('/@')[-1].split('/')[0])
            elif '/user/' in url:
                usernames.append(url.split('/user/')[-1].split('/')[0])
        
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
