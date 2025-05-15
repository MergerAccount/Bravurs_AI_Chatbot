import logging
import re
import json
import threading
import datetime
from functools import lru_cache
from hashlib import sha256
from openai import OpenAI
from fuzzywuzzy import fuzz

from app.config import OPENAI_API_KEY
from app.database import (
    get_session_messages, store_message,
    hybrid_search, semantic_search, embed_query,
    get_latest_consulting_trends
)
from app.agentConnector import AgentConnector
from dateutil import parser as date_parser

client = OpenAI(api_key=OPENAI_API_KEY)
agent_connector = AgentConnector()

embedding_cache = {}

# Common prompts to recall past questions
memory_prompts = [
    "what was my last question",
    "what was my previous question",
    "can you remind me my last question",
    "what did I ask before",
    "what was my earlier question",
    "show me my previous question",
    "tell me my last question",
    "repeat my last question",
    "what did I say last"
]

def log_async(fn, *args):
    threading.Thread(target=fn, args=args).start()

def is_last_question_request(user_input):
    return any(fuzz.partial_ratio(user_input.lower(), prompt) > 80 for prompt in memory_prompts)

def strip_html_paragraphs(text):
    return re.sub(r"^<p>(.*?)</p>$", r"\1", text.strip(), flags=re.DOTALL)

def estimate_tokens(text):
    return max(1, int(len(text.split()) * 0.75))

def get_recent_conversation(session_id, max_tokens=400):
    if not session_id:
        return []

    messages = get_session_messages(session_id)
    formatted = []

    for _, content, _, msg_type in messages:
        if msg_type == "user":
            formatted.append({"role": "user", "content": content})
        elif msg_type == "bot":
            formatted.append({"role": "assistant", "content": content})
        elif msg_type == "system":
            formatted.append({"role": "system", "content": content})

    total_tokens = 0
    selected = []

    for msg in reversed(formatted):
        tokens = estimate_tokens(msg["content"])
        if total_tokens + tokens > max_tokens:
            break
        selected.insert(0, msg)
        total_tokens += tokens

    return selected

def classify_intent(user_input: str, session_id: str = None) -> str:
    text = user_input.lower()
    print("[DEBUG] classify_intent text:", text)

    mckinsey_keywords = ["mckinsey", "consulting", "insight", "report", "trend", "update", "news", "article"]
    time_keywords = ["day", "week", "month", "recent", "latest", "past", "summary", "few", "today", "yesterday"]
    month_names = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]

    # Enhanced date pattern to include month-only
    date_pattern = r"\b(\d{1,2}\s*(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s*(\d{4})?)|((jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s*(\d{4}))|(\d{4})|\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b"

    # Check for McKinsey trend requests
    if any(mk in text for mk in mckinsey_keywords):
        if any(tk in text for tk in time_keywords) or re.search(r"\d+\s*(day|week|month|days|weeks)", text) or re.search(date_pattern, text):
            print("[DEBUG] matched McKinsey Trend Request (enhanced)")
            return "McKinsey Trend Request"

    # Check for month-only or date-related queries in McKinsey context
    if re.search(date_pattern, text):
        if session_id:
            recent_messages = get_session_messages(session_id)[-5:]
            if any("mckinsey" in msg[1].lower() or "trend" in msg[1].lower() for msg in recent_messages):
                print("[DEBUG] matched McKinsey Trend Request (follow-up date)")
                return "McKinsey Trend Request"
        # Treat month-only queries as McKinsey trends if no other intent matches
        if any(month in text for month in month_names):
            print("[DEBUG] matched McKinsey Trend Request (month-only)")
            return "McKinsey Trend Request"

    # Check for specific topics or article titles in McKinsey context
    if session_id:
        recent_messages = get_session_messages(session_id)[-5:]
        if any("mckinsey" in msg[1].lower() or "trend" in msg[1].lower() for msg in recent_messages):
            if any(topic in text for topic in ["governance", "risk", "compliance", "best practices", "technology", "strategy"]):
                print("[DEBUG] matched McKinsey Trend Request (topic follow-up)")
                return "McKinsey Trend Request"

    if any(word in text for word in ["contact", "human", "support", "agent", "real person"]):
        return "Human Support Service Request"

    if any(word in text for word in ["cloud", "ai", "software", "tech", "cybersecurity", "trend", "machine learning", "python", "network"]):
        return "IT Services & Trends"

    if any(word in text for word in ["company", "bravur", "mission", "vision", "history", "location", "services", "employees", "profile"]):
        return "Company Info"

    return "Unknown"

def embed_query_cached(query):
    key = sha256(query.encode()).hexdigest()
    if key in embedding_cache:
        return embedding_cache[key]

    def do_embed():
        embedding = embed_query(query)
        if embedding:
            embedding_cache[key] = embedding

    threading.Thread(target=do_embed).start()
    return None

def handle_meta_questions(user_input, session_id):
    if not session_id:
        return "I don't have any previous conversation to refer to."

    messages = get_session_messages(session_id)
    if not messages:
        return "I don't remember anything yet."

    messages.reverse()
    if is_last_question_request(user_input):
        skip_current = True
        for _, content, _, msg_type in messages:
            if msg_type == "user":
                if skip_current:
                    skip_current = False
                    continue
                return f"Your last question was: \"{content}\""
        return "I couldn't find your last question."

    elif "last answer" in user_input.lower():
        for _, content, _, msg_type in messages:
            if msg_type == "bot":
                return f"My last answer was: \"{content}\""
        return "I couldn't find my last answer."

    elif "summarize" in user_input.lower():
        all_msgs = get_session_messages(session_id)
        formatted = []
        for _, content, _, msg_type in all_msgs:
            if msg_type == "user":
                formatted.append({"role": "user", "content": content})
            elif msg_type == "bot":
                formatted.append({"role": "assistant", "content": content})

        summary_prompt = [{"role": "system", "content": "Summarize the following conversation briefly:"}] + formatted
        return gpt_cached_response("gpt-4o-mini", tuple(summary_prompt)).strip()

    return "I'm not sure what you're referring to. Could you clarify?"

def format_semantic_context(results):
    return "\n\n".join([
        f"Row ID: {row_id}\nTitle: {title}\nContent: {content}"
        for row_id, title, content, _ in results
    ])

def company_info_handler(user_input, session_id=None):
    if is_last_question_request(user_input) or "last answer" in user_input.lower() or "summarize" in user_input.lower():
        return handle_meta_questions(user_input, session_id)

    detected_intent = classify_intent(user_input, session_id)
    logging.info(f"[DEBUG] Detected intent: {detected_intent}")

    if detected_intent == "McKinsey Trend Request":
        reply = handle_mckinsey_trends(user_input)
        if session_id:
            log_async(store_message, session_id, user_input, "user")
            log_async(store_message, session_id, reply, "bot")
        return reply

    if detected_intent == "Human Support Service Request":
        reply = (
            "For human support, contact us on WhatsApp at +31 6 12345678 or email support@bravur.com."
        )
        if session_id:
            reply += f" When contacting support, please mention your session ID: {session_id}"
            log_async(store_message, session_id, user_input, "user")
            log_async(store_message, session_id, reply, "bot")
        return reply

    recent_convo = get_recent_conversation(session_id)

    search_results = hybrid_search(user_input, top_k=5)
    if not search_results:
        embedding = embed_query_cached(user_input)
        if embedding:
            search_results = semantic_search(embedding, top_k=5)

    if not search_results:
        return "I couldn't find anything relevant in Bravur's data. Try rephrasing your question."

    semantic_context = format_semantic_context(search_results)

    system_prompt = (
        f"You are a helpful assistant for Bravur. "
        f"Answer the user based on this information. Cite Row IDs used:\n\n{semantic_context}"
        f"You are allowed to search up Gartner information"
    )

    gpt_prompt = [{"role": "system", "content": system_prompt}] + recent_convo + [{"role": "user", "content": user_input}]
    reply = gpt_cached_response("gpt-4o-mini", tuple(gpt_prompt)).strip()
    reply = strip_html_paragraphs(reply)

    if session_id:
        log_async(store_message, session_id, user_input, "user")
        log_async(store_message, session_id, reply, "bot")

    return reply

def company_info_handler_streaming(user_input, session_id=None):
    detected_intent = classify_intent(user_input, session_id)
    logging.info(f"[DEBUG] Detected intent (streaming): {detected_intent}")

    if detected_intent == "McKinsey Trend Request":
        try:
            reply = handle_mckinsey_trends(user_input)
            if session_id:
                log_async(store_message, session_id, user_input, "user")
                log_async(store_message, session_id, reply, "bot")
            yield reply
            return
        except Exception as e:
            logging.error(f"Error in McKinsey trends streaming: {e}")
            reply = "Sorry, an error occurred while fetching McKinsey trends. Please try again."
            if session_id:
                log_async(store_message, session_id, user_input, "user")
                log_async(store_message, session_id, reply, "bot")
            yield reply
            return

    if detected_intent == "Human Support Service Request":
        reply = (
            "For human support, contact us on WhatsApp at +31 6 12345678 or email support@bravur.com."
        )
        if session_id:
            reply += f" When contacting support, please mention your session ID: {session_id}"
            log_async(store_message, session_id, user_input, "user")
            log_async(store_message, session_id, reply, "bot")
        yield reply
        return

    recent_convo = get_recent_conversation(session_id)

    search_results = hybrid_search(user_input, top_k=5)
    if not search_results:
        embedding = embed_query_cached(user_input)
        if embedding:
            search_results = semantic_search(embedding, top_k=5)

    semantic_context = format_semantic_context(search_results)

    system_prompt = (
        f"You are a helpful assistant for Bravur. "
        f"Answer the user based on this information. Cite Row IDs used:\n\n{semantic_context}"
    )

    gpt_prompt = [{"role": "system", "content": system_prompt}] + recent_convo + [{"role": "user", "content": user_input}]

    try:
        stream = client.chat.completions.create(
            model="gpt-4o",
            messages=gpt_prompt,
            stream=True
        )

        full_reply = ""
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                full_reply += delta
                yield delta

        if full_reply.strip() and session_id:
            log_async(store_message, session_id, user_input, "user")
            log_async(store_message, session_id, full_reply.strip(), "bot")

    except Exception as e:
        logging.error(f"Streaming error: {e}")
        reply = "Sorry, an error occurred while processing your request. Please try again."
        if session_id:
            log_async(store_message, session_id, user_input, "user")
            log_async(store_message, session_id, reply, "bot")
        yield reply

@lru_cache(maxsize=256)
def gpt_cached_response(model, messages_as_tuple):
    messages = json.loads(json.dumps(messages_as_tuple))
    response = client.chat.completions.create(
        model=model,
        messages=messages
    )
    return response.choices[0].message.content

def extract_days(user_input):
    match = re.search(r"(\d+)\s*(day|week)", user_input.lower())
    if match:
        number = int(match.group(1))
        unit = match.group(2)
        return number * 7 if unit == "week" else number
    return None

def handle_mckinsey_trends(user_input=None):
    import datetime
    import logging

    filters = extract_query_filters(user_input or "")
    date_exact = filters.get("date_exact")
    since_days = filters.get("since_days")
    from_date = filters.get("from_date")
    to_date = filters.get("to_date")
    month_year = filters.get("month_year")
    year_only = filters.get("year_only")
    keywords = filters.get("keywords")
    limit = filters.get("limit", 10)

    logging.info(
        f"Filters: date_exact={date_exact}, since_days={since_days}, from_date={from_date}, "
        f"to_date={to_date}, month_year={month_year}, year_only={year_only}, limit={limit}, keywords={keywords}"
    )

    # If no date filters, check for topic-specific keywords
    if not any([date_exact, since_days, from_date, to_date, month_year, year_only]) and not keywords:
        # Extract topic keywords for queries like "tell me more about governance, risk, and compliance"
        topic_keywords = [
            word for word in user_input.lower().split()
            if word not in {"tell", "more", "about", "a", "new", "lens", "on", "best", "practices"} and len(word) > 3
        ]
        if topic_keywords:
            keywords = topic_keywords
            logging.info(f"Added topic keywords: {keywords}")

    entries = get_latest_consulting_trends(
        source="McKinsey",
        limit=limit,
        since_days=since_days,
        date_exact=date_exact if not (from_date and to_date or month_year or year_only) else None,
        keywords=keywords,
        from_date=from_date,
        to_date=to_date,
        month_year=month_year,
        year_only=year_only
    )

    if not entries:
        logging.info("No trends found.")
        if date_exact and not (from_date and to_date or month_year or year_only):
            return f"Sorry, no McKinsey articles found for {date_exact.strftime('%B %d, %Y')}."
        elif month_year:
            return f"Sorry, no McKinsey articles found for {month_year.strftime('%B %Y')}."
        elif year_only:
            return f"Sorry, no McKinsey articles found for {year_only}."
        elif from_date and to_date:
            return f"Sorry, no McKinsey articles found between {from_date.strftime('%B %d, %Y')} and {to_date.strftime('%B %d, %Y')}."
        elif since_days:
            return f"Sorry, no McKinsey articles found from the last {since_days} days."
        elif keywords:
            return f"Sorry, no McKinsey articles found matching the topic: {', '.join(keywords)}."
        return "Sorry, no McKinsey trends found matching your query."

    # Validate entries against date filters
    filtered_entries = []
    for entry in entries:
        published_date = entry[3]
        if month_year:
            if not (published_date.year == month_year.year and published_date.month == month_year.month):
                continue
        elif year_only:
            if published_date.year != year_only:
                continue
        elif from_date and to_date:
            if not (from_date <= published_date <= to_date):
                continue
        elif date_exact:
            if published_date != date_exact:
                continue
        filtered_entries.append(entry)

    if not filtered_entries:
        logging.info("No entries matched the date filter after validation.")
        if date_exact and not (from_date and to_date or month_year or year_only):
            return f"Sorry, no McKinsey articles found for {date_exact.strftime('%B %d, %Y')}."
        elif month_year:
            return f"Sorry, no McKinsey articles found for {month_year.strftime('%B %Y')}."
        elif year_only:
            return f"Sorry, no McKinsey articles found for {year_only}."
        elif from_date and to_date:
            return f"Sorry, no McKinsey articles found between {from_date.strftime('%B %d, %Y')} and {to_date.strftime('%B %d, %Y')}."
        elif since_days:
            return f"Sorry, no McKinsey articles found from the last {since_days} days."
        elif keywords:
            return f"Sorry, no McKinsey articles found matching the topic: {', '.join(keywords)}."
        return "Sorry, no McKinsey trends found matching your date criteria."

    # Fallback: If no results, try a broader range (e.g., 7 days around date_exact or month)
    if not filtered_entries:
        logging.info("Attempting fallback search for nearby trends")
        fallback_days = 7
        if date_exact:
            fallback_from = (date_exact - datetime.timedelta(days=fallback_days)).date()
            fallback_to = (date_exact + datetime.timedelta(days=fallback_days)).date()
            fallback_label = date_exact.strftime('%B %d, %Y')
        elif month_year:
            fallback_from = month_year
            fallback_to = (month_year.replace(day=1) + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1)
            fallback_label = month_year.strftime('%B %Y')
        else:
            # Default fallback for topic-based or no-date queries
            fallback_from = (datetime.datetime.now() - datetime.timedelta(days=fallback_days)).date()
            fallback_to = (datetime.datetime.now() + datetime.timedelta(days=fallback_days)).date()
            fallback_label = "recent trends"

        fallback_entries = get_latest_consulting_trends(
            source="McKinsey",
            limit=limit,
            from_date=fallback_from,
            to_date=fallback_to,
            keywords=keywords
        )

        if fallback_entries:
            lines = [f"<strong>McKinsey Trends (Nearby Dates)</strong><br><br>"]
            lines.append(
                f"No exact matches found for {fallback_label}. "
                f"Showing trends from {fallback_from.strftime('%B %d, %Y')} to {fallback_to.strftime('%B %d, %Y')}:<br><br>"
            )
            for idx, (title, summary, url, published_date) in enumerate(fallback_entries, 1):
                summary_clean = summary.strip().replace("\n", " ").replace("\\n", " ")
                lines.append(
                    f"{idx}. <strong>{title}</strong><br>"
                    f"{summary_clean[:300]}...<br>"
                    f"<em>Published: {published_date.strftime('%Y-%m-%d')}</em><br>"
                    f"<a href=\"{url}\" target=\"_blank\" style=\"color:#1a0dab\">Read more</a><br><br>"
                )
            return "\n".join(lines)

    lines = [f"<strong>McKinsey Trends</strong><br><br>"]
    for idx, (title, summary, url, published_date) in enumerate(filtered_entries, 1):
        summary_clean = summary.strip().replace("\n", " ").replace("\\n", " ")
        lines.append(
            f"{idx}. <strong>{title}</strong><br>"
            f"{summary_clean[:300]}...<br>"
            f"<em>Published: {published_date.strftime('%Y-%m-%d')}</em><br>"
            f"<a href=\"{url}\" target=\"_blank\" style=\"color:#1a0dab\">Read more</a><br><br>"
        )

    return "\n".join(lines)

def extract_query_filters(user_input):
    import datetime
    from dateutil import parser as date_parser
    import re
    import logging

    now = datetime.datetime.now()
    current_year = now.year
    week_start = now - datetime.timedelta(days=now.weekday())
    week_end = week_start + datetime.timedelta(days=6)
    last_week_start = week_start - datetime.timedelta(days=7)
    last_week_end = last_week_start + datetime.timedelta(days=6)

    filters = {
        "date_exact": None,
        "since_days": None,
        "from_date": None,
        "to_date": None,
        "month_year": None,
        "year_only": None,
        "keywords": [],
        "limit": 10
    }

    cleaned_input = re.sub(r"[^\w\s/-]", "", user_input.lower())

    # 1. Handle "this week"
    if "this week" in cleaned_input:
        filters["from_date"] = week_start.date()
        filters["to_date"] = week_end.date()
        logging.info(f"Parsed 'this week' as {filters['from_date']} to {filters['to_date']}")

    # 2. Handle "last week"
    if "last week" in cleaned_input and not filters["from_date"]:
        filters["from_date"] = last_week_start.date()
        filters["to_date"] = last_week_end.date()
        logging.info(f"Parsed 'last week' as {filters['from_date']} to {filters['to_date']}")

    # 3. Date range: "from 1 May to 12 May"
    range_match = re.search(
        r"(?:from|between)\s+(\d{1,2})\s*([a-z]+)\s*(?:\s+(\d{2,4}))?\s+(?:to|-)\s+(\d{1,2})\s*([a-z]+)\s*(?:\s+(\d{2,4}))?",
        cleaned_input
    )
    if range_match:
        try:
            from_str = f"{range_match.group(1)} {range_match.group(2)} {range_match.group(3) or current_year}"
            to_str = f"{range_match.group(4)} {range_match.group(5)} {range_match.group(6) or current_year}"
            from_date = date_parser.parse(from_str, fuzzy=True).date()
            to_date = date_parser.parse(to_str, fuzzy=True).date()
            if from_date > to_date:
                from_date, to_date = to_date, from_date
                logging.info(f"Swapped date range: {from_date} to {to_date}")
            filters["from_date"] = from_date
            filters["to_date"] = to_date
            logging.info(f"Parsed date range: {filters['from_date']} to {filters['to_date']}")
        except Exception as e:
            logging.warning(f"Date range parsing failed: {e}")

    # 4. Specific date: "6 May 2025"
    if not filters["from_date"] and not filters["to_date"]:
        single_date_match = re.search(
            r"\b(\d{1,2})\s*(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s*(\d{4})?\b",
            cleaned_input
        )
        if single_date_match:
            try:
                day = single_date_match.group(1)
                month_str = single_date_match.group(2)
                year = single_date_match.group(3) or current_year
                date_str = f"{day} {month_str} {year}"
                parsed_date = date_parser.parse(date_str, fuzzy=True).date()
                filters["date_exact"] = parsed_date
                logging.info(f"Parsed specific date: {parsed_date}")
            except Exception as e:
                logging.warning(f"Single date parsing failed: {e}")

    # 5. Month and year: "May 2025"
    if not filters["from_date"] and not filters["to_date"] and not filters["date_exact"]:
        month_year_match = re.search(
            r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s*(\d{4})\b",
            cleaned_input
        )
        if month_year_match:
            try:
                month_str = month_year_match.group(1)
                year = month_year_match.group(2)
                month_date = date_parser.parse(f"1 {month_str} {year}", fuzzy=True).date()
                filters["month_year"] = month_date
                logging.info(f"Parsed month/year: {filters['month_year']}")
            except Exception as e:
                logging.warning(f"Month/year parsing failed: {e}")

    # 6. Month only: "April"
    if not filters["from_date"] and not filters["to_date"] and not filters["date_exact"] and not filters["month_year"]:
        month_only_match = re.search(
            r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
            cleaned_input
        )
        if month_only_match:
            try:
                month_str = month_only_match.group(1)
                # Assume current year if after current month, else previous year
                month_date = date_parser.parse(f"1 {month_str} {current_year}", fuzzy=True).date()
                if month_date > now.date():
                    month_date = month_date.replace(year=current_year - 1)
                filters["month_year"] = month_date
                logging.info(f"Parsed month only: {filters['month_year']}")
            except Exception as e:
                logging.warning(f"Month only parsing failed: {e}")

    # 7. Year only: "2025"
    if not filters["from_date"] and not filters["to_date"] and not filters["date_exact"] and not filters["month_year"]:
        year_match = re.search(r"\b(\d{4})\b", cleaned_input)
        if year_match and int(year_match.group(1)) in range(2000, current_year + 10):
            filters["year_only"] = int(year_match.group(1))
            logging.info(f"Parsed year: {filters['year_only']}")

    # 8. Relative ranges: "last 7 days"
    rel_match = re.search(r"\b(last|past)\s*(\d+)\s*(day|week|month|days|weeks|months)\b", cleaned_input)
    if rel_match and not filters["from_date"] and not filters["date_exact"] and not filters["month_year"]:
        try:
            number = int(rel_match.group(2))
            unit = rel_match.group(3)
            if "week" in unit:
                filters["since_days"] = number * 7
            elif "month" in unit:
                filters["since_days"] = number * 30
            else:
                filters["since_days"] = number
            logging.info(f"Parsed relative range: {filters['since_days']} days")
        except Exception as e:
            logging.warning(f"Relative range parsing failed: {e}")

    # 9. Fallback for "recent" or "latest"
    if ("recent" in cleaned_input or "latest" in cleaned_input) and not any(
            [filters["from_date"], filters["date_exact"], filters["month_year"], filters["year_only"]]
    ):
        filters["since_days"] = filters["since_days"] or 7
        logging.info(f"Applied fallback for recent/latest: {filters['since_days']} days")

    # 10. Flexible limit detection
    limit_match = re.search(r"\b(?:show|give|list|get|display)\s*(\d{1,2})\s*(trend|article|result)s\b", cleaned_input)
    if limit_match:
        try:
            filters["limit"] = int(limit_match.group(1))
            logging.info(f"Parsed limit: {filters['limit']}")
        except Exception as e:
            logging.warning(f"Limit parsing failed: {e}")

    # 11. Filter keywords
    stopwords = {
        "what", "is", "are", "the", "of", "on", "from", "in", "and", "to", "me", "please", "this", "week", "last",
        "mckinsey", "trends", "latest", "recent", "show", "any", "new", "between", "get", "give", "articles",
        "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december",
        "published", "publish", "tell", "more", "about"
    }
    filters["keywords"] = [
        word for word in cleaned_input.split()
        if word not in stopwords and len(word) > 3 and word.isalpha()
    ]
    logging.info(f"Parsed keywords: {filters['keywords']}")

    return filters

agent_connector.register_agent("Bravur_Information_Agent", company_info_handler)