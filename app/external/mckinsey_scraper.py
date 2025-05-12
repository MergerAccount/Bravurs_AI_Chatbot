import requests
from bs4 import BeautifulSoup
import psycopg2
from urllib.parse import urljoin
import os
from dotenv import load_dotenv
from datetime import datetime

# NEW CODE tag: Load environment variables
load_dotenv()

# NEW CODE tag: PostgreSQL config
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT"),
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD")
}

RSS_HTML_PAGE = "https://www.mckinsey.com/insights/rss"

# NEW CODE tag: Create database connection
def get_connection():
    return psycopg2.connect(**DB_CONFIG)
