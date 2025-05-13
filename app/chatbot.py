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

    # Check if it's a McKinsey trend request
    if "mckinsey" in text and any(word in text for word in ["trend", "article", "insight", "report", "news", "day", "week"]):
        print("[DEBUG] matched McKinsey Trend Request (initial)")
        return "McKinsey Trend Request"

    # Check for follow-up McKinsey trend request with date context
    import re
    date_pattern = r"\b(\d{1,2})\s*(?:-?\s*)?(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b"
    if re.search(date_pattern, text) and session_id:
        from app.database import get_session_messages
        recent_messages = get_session_messages(session_id)  # Fetch all messages
        recent_messages = recent_messages[-5:] if recent_messages else []  # Manually limit to last 5
        if any("mckinsey trends" in msg[1].lower() for msg in recent_messages):
            print("[DEBUG] matched McKinsey Trend Request (follow-up)")
            return "McKinsey Trend Request"

    # Other intents remain unchanged
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
        return gpt_cached_response("gpt-4o-mini", summary_prompt).strip()

    return "I'm not sure what you're referring to. Could you clarify?"

def format_semantic_context(results):  # extract duplicated logic
    return "\n\n".join([
        f"Row ID: {row_id}\nTitle: {title}\nContent: {content}"
        for row_id, title, content, _ in results
    ])

def company_info_handler(user_input, session_id=None):
    if is_last_question_request(user_input) or "last answer" in user_input.lower() or "summarize" in user_input.lower():
        return handle_meta_questions(user_input, session_id)

    detected_intent = classify_intent(user_input)
    print("[DEBUG] Detected intent:", detected_intent)

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

    if detected_intent == "Unknown":
        return "I'm here to answer questions about Bravur and IT services. How can I help?"

    if detected_intent == "IT Services & Trends":
        it_prompt = [
                        {"role": "system", "content": (
                            "You are a knowledgeable assistant providing insights on IT services and trends. "
                            "Avoid repeating unless asked. Be clear and helpful."
                        )}
                    ] + recent_convo + [{"role": "user", "content": user_input}]

        reply = gpt_cached_response("gpt-4o-mini", it_prompt).strip()
        reply = strip_html_paragraphs(reply)

        if session_id:
            log_async(store_message, session_id, user_input, "user")
            log_async(store_message, session_id, reply, "bot")
        return reply

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
    )

    gpt_prompt = [{"role": "system", "content": system_prompt}] + recent_convo + [{"role": "user", "content": user_input}]
    reply = gpt_cached_response("gpt-4o-mini", gpt_prompt).strip()
    reply = strip_html_paragraphs(reply)

    if session_id:
        log_async(store_message, session_id, user_input, "user")
        log_async(store_message, session_id, reply, "bot")

    return reply

def company_info_handler_streaming(user_input, session_id=None):
    detected_intent = classify_intent(user_input, session_id)  # Pass session_id
    print("[DEBUG] Detected intent (streaming):", detected_intent)

    if detected_intent == "McKinsey Trend Request":
        reply = handle_mckinsey_trends(user_input)
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

        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    except Exception as e:
        logging.error(f"Streaming error: {e}")
        yield "\n[Error generating response]"

agent_connector.register_agent("Bravur_Information_Agent", company_info_handler)

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
    filters = extract_query_filters(user_input or "")
    days = extract_days(user_input or "")
    date_exact = filters.get("date_exact")
    keywords = None if date_exact else filters.get("keywords")

    # Log the filters for debugging
    logging.info(f"Filters extracted: date_exact={date_exact}, days={days}, keywords={keywords}")

    entries = get_latest_consulting_trends(
        source="McKinsey",
        limit=5,
        since_days=days,
        date_exact=date_exact,
        keywords=keywords
    )

    if not entries:
        logging.info(f"No trends found for date_exact={date_exact}")
        return f"Sorry, I couldn't find any McKinsey trends matching your query."

    lines = [f"<strong>McKinsey Trends</strong><br><br>"]
    for idx, (title, summary, url, published_date) in enumerate(entries, 1):
        summary_clean = summary.strip().replace("\n", " ").replace("\\n", " ")
        lines.append(
            f"{idx}. <strong>{title}</strong><br>"
            f"{summary_clean[:300]}...<br>"
            f"<em>Published: {published_date}</em><br>"
            f"<a href=\"{url}\" target=\"_blank\" style=\"color:#1a0dab\">Read more</a><br><br>"
        )
    return "\n".join(lines)

def extract_query_filters(user_input):
    filters = {
        "date_exact": None,
        "keywords": []
    }

    # Enhanced regex to match flexible date formats (e.g., "4 may", "29 april 2025")
    date_match = re.search(r"\b(\d{1,2})\s*(?:-?\s*)?(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s*(?:\s*(\d{2,4}))?\b", user_input, re.IGNORECASE)
    if date_match:
        try:
            day = date_match.group(1)
            month = date_match.group(2).lower()[:3]  # Take first 3 letters for consistency
            year = date_match.group(3) if date_match.group(3) else datetime.datetime.now().year
            date_str = f"{day} {month} {year}"
            parsed = date_parser.parse(date_str, fuzzy=True, dayfirst=True)
            filters["date_exact"] = parsed.date()
            logging.info(f"Parsed date from input '{user_input}': {filters['date_exact']}")
        except Exception as e:
            logging.warning(f"Date parsing failed for input '{user_input}': {e}")

    # Extract keywords (remove stop words)
    cleaned_input = re.sub(r"[^\w\s]", "", user_input.lower())
    tokens = cleaned_input.split()
    filters["keywords"] = [word for word in tokens if word not in {"what", "is", "are", "the", "of", "on", "from", "in", "and", "mckinsey", "trend", "show", "me", "please"}]

    return filters