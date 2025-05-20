import os
import requests
import logging

SERPER_API_KEY = os.getenv("SERPER_API_KEY")

if not SERPER_API_KEY:
    logging.warning("SERPER_API_KEY not set. Please define it in your environment.")

def search_web(query):
    url = "https://google.serper.dev/search"
    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "q": query
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logging.error(f"Search API error: {e}")
        return {"error": str(e)}
