import requests
from bs4 import BeautifulSoup
import psycopg2
from urllib.parse import urljoin
import os
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()

# PostgreSQL config
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT"),
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD")
}

RSS_HTML_PAGE = "https://www.mckinsey.com/insights/rss"

# Create database connection
def get_connection():
    return psycopg2.connect(**DB_CONFIG)

# Insert McKinsey articles into consulting_trends table
def insert_article(source, title, summary, url, published_date):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO consulting_trends (source, title, summary, url, published_date, date_fetched)
        VALUES (%s, %s, %s, %s, %s, NOW())
        ON CONFLICT (url) DO UPDATE
        SET
            title = EXCLUDED.title,
            summary = EXCLUDED.summary,
            published_date = EXCLUDED.published_date,
            date_fetched = NOW();
        """, (source, title.strip(), summary.strip(), url.strip(), published_date))
        conn.commit()
        cursor.close()
        conn.close()
        print(f"Inserted/Updated: {title} (published {published_date})")
    except Exception as e:
        print(f"Insert failed: {e}")

# Scrape McKinsey RSS-like feed
def scrape_rss_like_feed():
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    response = requests.get(RSS_HTML_PAGE, headers=headers)
    if response.status_code != 200:
        print(f"Failed to fetch RSS-like page: {response.status_code}")
        return

    soup = BeautifulSoup(response.content, "xml")
    items = soup.find_all("item")
    count = 0

    if not items:
        print("No <item> elements found in the XML.")
        return

    for item in items:
        title_tag = item.find("title")
        summary_tag = item.find("description")
        link_tag = item.find("link")
        pub_date_tag = item.find("pubDate")

        title = title_tag.get_text(strip=True) if title_tag else None
        summary = summary_tag.get_text(strip=True) if summary_tag else "No summary available."
        url = link_tag.get_text(strip=True) if link_tag else None

        # Parse pubDate with correct format
        published_date = None
        if pub_date_tag:
            try:
                published_date = datetime.strptime(pub_date_tag.text.strip(), "%a, %d %b %Y").date()
            except Exception as e:
                print(f"Date parsing error: {e}")

        if title and url:
            insert_article("McKinsey", title, summary, url, published_date)
            count += 1

    print(f"Inserted {count} articles.")

if __name__ == "__main__":
    scrape_rss_like_feed()