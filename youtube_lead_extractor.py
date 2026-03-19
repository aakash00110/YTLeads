import os
import re
import csv
import argparse
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Regular expression for finding email addresses
EMAIL_REGEX = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'

def extract_emails(text):
    """Finds all emails in a given string and returns a unique list."""
    if not text:
        return []
    emails = re.findall(EMAIL_REGEX, text)
    return list(set(emails))

def process_channels(youtube, channel_ids=None, handles=None, usernames=None):
    leads = []
    try:
        items = []
        if channel_ids:
            for i in range(0, len(channel_ids), 50):
                batch = channel_ids[i:i+50]
                resp = youtube.channels().list(id=','.join(batch), part='snippet,statistics').execute()
                items.extend(resp.get('items', []))
        
        if handles:
            for handle in handles:
                resp = youtube.channels().list(forHandle=handle, part='snippet,statistics').execute()
                items.extend(resp.get('items', []))
                
        if usernames:
            for un in usernames:
                resp = youtube.channels().list(forUsername=un, part='snippet,statistics').execute()
                items.extend(resp.get('items', []))

        for channel in items:
            title = channel['snippet'].get('title', 'Unknown')
            desc = channel['snippet'].get('description', '')
            cid = channel['id']
            curl = channel['snippet'].get('customUrl', '')
            url = f"https://www.youtube.com/{curl}" if curl else f"https://www.youtube.com/channel/{cid}"
            
            subs = channel['statistics'].get('subscriberCount', '0')
            views = channel['statistics'].get('viewCount', '0')
            
            found = extract_emails(desc)
            
            leads.append({
                'Channel Name': title,
                'URL': url,
                'Subscribers': subs,
                'Total Views': views,
                'Emails Found': ", ".join(found) if found else "Not Found",
                'Description Snippet': desc[:100].replace('\n', ' ') + '...' if desc else ''
            })
    except HttpError as e:
        print(f"API Error: {e}")
    return leads

def get_channel_leads(api_key, query=None, input_file=None, max_results=10, output_file="leads.csv"):
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
            all_leads.extend(process_channels(youtube, channel_ids=cids))
            
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
        all_leads.extend(process_channels(youtube, channel_ids=cids, handles=handles, usernames=usernames))
        
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
    args = parser.parse_args()
    
    if not args.query and not args.input:
        parser.error("Must provide either --query or --input")
        
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("ERROR: Set YOUTUBE_API_KEY env variable.")
        exit(1)
        
    get_channel_leads(api_key, args.query, args.input, args.max_results, args.output)
