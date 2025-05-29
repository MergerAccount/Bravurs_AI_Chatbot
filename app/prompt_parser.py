import dateparser
from datetime import datetime, timedelta
import re

def extract_timeframe(prompt):
    now = datetime.now()
    prompt_lower = prompt.lower()

    if "last week" in prompt_lower:
        return now - timedelta(days=7), now
    elif "this week" in prompt_lower:
        start = now - timedelta(days=now.weekday())
        return start, now
    elif "last month" in prompt_lower:
        start = now.replace(day=1) - timedelta(days=1)
        return start.replace(day=1), start
    elif "this month" in prompt_lower:
        return now.replace(day=1), now
    elif "latest" in prompt_lower or "recent" in prompt_lower:
        return now - timedelta(days=7), now

    parsed = dateparser.parse(prompt, settings={"RELATIVE_BASE": now})
    if parsed:
        return parsed, now

    return None, None

def is_trend_request(prompt):
    """
    detect if user is asking for trends.
    use basic keyword check plus presence of a timeframe or intent word.
    """
    text = prompt.lower()
    has_trend_word = "trend" in text
    has_timeframe_word = any(w in text for w in ["last", "week", "month", "recent", "this", "today", "update"])
    return has_trend_word and has_timeframe_word

def needs_fresh_trends(prompt):
    start, end = extract_timeframe(prompt)
    if not start or not end:
        return False
    now = datetime.now()
    if "last week" in prompt.lower():
        return (now - start).days <= 7  # Strict 7-day window for "last week"
    return (now - start).days <= 45