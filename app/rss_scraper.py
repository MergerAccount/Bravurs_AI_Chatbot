import feedparser
import psycopg2
import os
from datetime import datetime
from urllib.parse import urlparse
from dotenv import load_dotenv

#  Load .env values
load_dotenv()

DB_CONFIG = {
    'dbname': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'host': os.getenv('DB_HOST'),
    'port': os.getenv('DB_PORT')
}

FEED_URLS = [
    "https://www.zdnet.com/news/rss.xml"
]

def store_article(title, snippet, link, pub_date_str, domain):
    print(f"➡ Attempting to insert: {title[:50]} | Date: {pub_date_str}")
    try:
        pub_date = datetime.strptime(pub_date_str, "%Y-%m-%d").date()
    except Exception as e:
        print(f" Invalid date format '{pub_date_str}': {e}")
        return

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO external_articles (title, snippet, link, publication_date, domain)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (link) DO NOTHING;
        """, (title, snippet, link, pub_date, domain))
        conn.commit()
        cur.close()
        conn.close()
        print(" Inserted successfully.\n")
    except Exception as e:
        print(f" DB insert error: {e}")

def run_scraper():
    print("🚀 Starting RSS scraping...")
    for url in FEED_URLS:
        print(f" Fetching feed: {url}")
        feed = feedparser.parse(url)

        print(" Feed keys:", list(feed.keys()))
        print(" HTTP status:", feed.get("status", "unknown"))
        print(" Bozo (parser error?):", feed.bozo)
        if feed.bozo:
            print(" Parser exception:", getattr(feed, "bozo_exception", None))

        if not feed.entries:
            print(f" No entries found in: {url}")
            continue

        for entry in feed.entries:
            title = entry.get("title", "No Title")
            link = entry.get("link", "")
            summary = entry.get("summary", "")
            published = entry.get("published", "")

            if not published:
                print(f"️ No published date for: {title}")
                continue

            try:
                pub_date = datetime.strptime(published[:16], "%a, %d %b %Y").strftime("%Y-%m-%d")
            except Exception as e:
                print(f" Failed to parse published date '{published}': {e}")
                continue

            domain = urlparse(link).netloc
            store_article(title, summary, link, pub_date, domain)

    print(" Scraping complete.")

if __name__ == "__main__":
    run_scraper()
