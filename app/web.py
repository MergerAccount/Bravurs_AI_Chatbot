import os
import requests
import logging

SERPER_API_KEY = os.getenv("SERPER_API_KEY")

if not SERPER_API_KEY:
    logging.warning("SERPER_API_KEY not set. Please define it in your environment.")

def search_web(query):
    """
    Performs a web search using Serper.dev.
    If the query includes 'mckinsey' or 'gartner', limit results to those domains.
    Otherwise, search broadly.
    """
    url = "https://google.serper.dev/search"
    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json"
    }

    if "mckinsey" in query.lower() or "gartner" in query.lower():
        scoped_query = f"{query} site:mckinsey.com OR site:gartner.com"
    else:
        scoped_query = query

    payload = {
        "q": scoped_query
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        search_result = response.json()
        logging.info(f"[Serper] Search query: {scoped_query}")
        logging.info(f"[Serper] Search result keys: {list(search_result.keys())}")
        return search_result
    except requests.RequestException as e:
        logging.error(f"[Serper Error] Search API request failed: {e}")
        return {"error": str(e)}
