# app/web.py
import os
import requests
import logging

SERPER_API_KEY = os.getenv("SERPER_API_KEY")

if not SERPER_API_KEY:
    logging.warning("SERPER_API_KEY not set. SerperAPI searches will fail.")


def search_web(query: str, site_constraint: str = None):
    """
    Performs a web search using Serper API.
    Optionally adds site constraints to the query (e.g., "site:mckinsey.com OR site:gartner.com").
    """
    if not SERPER_API_KEY:
        logging.error("SERPER_API_KEY is not configured. Cannot perform web search.")
        # Return a structure consistent with successful calls but indicating no results due to config error
        return {"error": "Serper API key not configured.", "organic": []}

    url = "https://google.serper.dev/search"
    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json"
    }

    actual_search_query = query
    if site_constraint:
        actual_search_query = f"{query} {site_constraint}"

    # Request more results to get a broader context, will pick top 5 relevant ones later
    payload = {"q": actual_search_query, "num": 7}
    logging.info(f"SerperAPI search query: {actual_search_query}")

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()  # Raise an exception for HTTP errors
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"SerperAPI request failed: {e}")
        return {"error": str(e), "organic": []}  # Ensure "organic" key for consistent error handling
    except Exception as e:
        logging.error(f"Error processing SerperAPI response: {e}")
        return {"error": str(e), "organic": []}