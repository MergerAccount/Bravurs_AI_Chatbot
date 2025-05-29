import logging
import re
import json
import threading
import os
import psycopg2
from functools import lru_cache
from hashlib import sha256
from openai import OpenAI
from fuzzywuzzy import fuzz
from urllib.parse import urlparse

from datetime import datetime
import dateutil.parser

from app.config import OPENAI_API_KEY, DB_CONFIG
from app.database import (
    get_session_messages, store_message,
    hybrid_search, semantic_search, embed_query
)
from app.agentConnector import AgentConnector
from app.web import search_web
from app.prompt_parser import (
    extract_timeframe,
    is_trend_request,
    needs_fresh_trends
)

client = OpenAI(api_key=OPENAI_API_KEY)
agent_connector = AgentConnector()
embedding_cache = {}
session_state_flags = {}


@lru_cache(maxsize=1)
def load_prompt_txt(file_name):
    with open(os.path.join("app", "prompts", file_name), "r", encoding="utf-8") as f:
        return f.read()

@lru_cache(maxsize=1)
def load_prompts(file_name):
    with open(os.path.join("app", "prompts", file_name), "r") as f:
        return json.load(f)

def get_prompts():
    return {
        "gpt_prompts": load_prompts("gpt_prompts.json"),
        "static_replies": load_prompts("static_replies.json"),
        "intent_detection": load_prompts("intent_detection.json")
    }

external_prompt_template = load_prompt_txt("external_source_prompts.txt")

@lru_cache(maxsize=256)
def gpt_cached_response(model, messages_json):
    messages = json.loads(messages_json)
    response = client.chat.completions.create(model=model, messages=messages)
    return response.choices[0].message.content

def call_gpt(prompt):
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.strip()

def log_async(fn, *args):
    threading.Thread(target=fn, args=args).start()

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

def classify_intent(user_input):
    prompts = get_prompts()
    memory_prompts = prompts["intent_detection"]["memory_prompts"]
    if any(fuzz.partial_ratio(user_input.lower(), prompt) > 80 for prompt in memory_prompts):
        return "Memory"

    keywords = user_input.lower()

    if any(word in keywords for word in ["bravur", "company", "mission", "services"]):
        return "Company Info"
    if any(word in keywords for word in ["support", "contact", "help"]):
        return "Human Support"
    if is_trend_request(user_input):
        return "IT Services"

    if any(month in keywords for month in [
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
        "2023", "2024", "2025", "report", "forecast", "insight"
    ]):
        return "External Search"

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

def handle_it_services(user_input, session_id=None):
    prompts = get_prompts()
    recent_convo = get_recent_conversation(session_id)
    gpt_prompt = [
        {"role": "system", "content": prompts["gpt_prompts"]["it_services"]},
        *recent_convo,
        {"role": "user", "content": user_input}
    ]
    reply = gpt_cached_response("gpt-4o-mini", json.dumps(gpt_prompt, sort_keys=True)).strip()
    reply = strip_html_paragraphs(reply)
    if session_id:
        log_async(store_message, session_id, user_input, "user")
        log_async(store_message, session_id, reply, "bot")
    return reply

def handle_meta_questions(user_input, session_id):
    if not session_id:
        return "I don't have any previous conversation to refer to."
    messages = get_session_messages(session_id)
    if not messages:
        return "I don't remember anything yet."
    messages.reverse()
    prompts = get_prompts()
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
        formatted = []
        for _, content, _, msg_type in messages:
            if msg_type == "user":
                formatted.append({"role": "user", "content": content})
            elif msg_type == "bot":
                formatted.append({"role": "assistant", "content": content})
        summary_prompt = [{"role": "system", "content": prompts["gpt_prompts"]["summary"]}] + formatted
        return gpt_cached_response("gpt-4o-mini", tuple(summary_prompt)).strip()
    return "I'm not sure what you're referring to. Could you clarify?"

def query_article_cache(start, end):
    import psycopg2
    from app.config import DB_CONFIG

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("""
        SELECT title, snippet, link, publication_date
        FROM external_articles
        WHERE publication_date BETWEEN %s AND %s
        ORDER BY publication_date DESC
        LIMIT 3;
    """, (start.date(), end.date()))
    results = cur.fetchall()
    cur.close()
    conn.close()

    formatted = []
    for title, snippet, link, pub_date in results:
        formatted.append({
            "title": title,
            "snippet": snippet,
            "link": link,
            "parsed_date": pub_date,
            "is_stale": False
        })
    return formatted


    def is_affirmative_reply(text):
        affirmatives = ["yes", "sure", "show me", "okay", "go ahead", "alright"]
        return any(fuzz.partial_ratio(text.lower(), a) > 80 for a in affirmatives)

    def is_date_in_timeframe(dt, timeframe):
        return timeframe["start"] <= dt <= timeframe["end"]

    def extract_date(snippet):
        try:
            date_patterns = re.findall(
                r'\b(?:\d{1,2}\s)?(?:January|February|March|April|May|June|July|August|September|October|November|December)\s\d{4}|\d{4}-\d{2}-\d{2}',
                snippet, re.IGNORECASE
            )
            for dp in date_patterns:
                return dateutil.parser.parse(dp, fuzzy=True)
        except Exception:
            return None

    def is_relevant(text):
        keywords = ["ai", "cloud", "digital", "cyber", "data", "tech", "iot", "blockchain", "ml", "infrastructure"]
        return any(k in text.lower() for k in keywords)

    # Handle follow-up reply to "Do you want to see old articles?"
    if session_id in session_state_flags:
        state = session_state_flags[session_id]
        if state.get("offered_old_trends") and is_affirmative_reply(user_input):
            results = state.get("stale_results", [])
            del session_state_flags[session_id]
        else:
            yield "Got it. I won’t show outdated results."
            del session_state_flags[session_id]
            return
    else:
        timeframe = extract_timeframe(user_input)

        # ✅ Try local cache first
        results = query_article_cache(timeframe["start"], timeframe["end"])

        if results:
            logging.info("[Cache] Using cached articles from DB.")
        else:
            logging.info("[Cache] No results in cache. Falling back to web search.")
            results = []
            trusted_domains = [
                "mckinsey.com", "gartner.com", "forrester.com",
                "techcrunch.com", "zdnet.com", "wired.com",
                "csoonline.com", "cio.com", "informationweek.com"
            ]
            domain_sets = [
                ["mckinsey.com", "gartner.com", "forrester.com"],
                ["techcrunch.com", "zdnet.com", "wired.com", "csoonline.com", "cio.com", "informationweek.com"]
            ]
            fallback_used = False
            collected = []

            for domains in domain_sets:
                domain_query = " OR ".join(f"site:{d}" for d in domains)
                full_query = f"{user_input} {domain_query}"
                search_data = search_web(full_query)
                logging.info(f"[Serper] Search query: {full_query}")
                logging.info(f"[Serper] Search result keys: {list(search_data.keys())}")

                def is_it_domain(link):
                    domain = urlparse(link).netloc
                    return any(d in domain for d in domains)

                if "organic" in search_data and search_data["organic"]:
                    raw_results = search_data["organic"]
                    for r in raw_results:
                        title = r.get("title", "")
                        snippet = r.get("snippet", "")
                        link = r.get("link", "")

                        if (
                                len(title) > 30 and len(snippet) > 50 and "http" in link and
                                is_it_domain(link) and is_relevant(title + " " + snippet)
                        ):
                            dt = extract_date(snippet)
                            is_stale = True
                            if dt:
                                is_stale = not is_date_in_timeframe(dt, timeframe)
                            collected.append({
                                "title": title,
                                "snippet": snippet,
                                "link": link,
                                "parsed_date": dt,
                                "is_stale": is_stale
                            })

                    if collected:
                        break
                    else:
                        fallback_used = True

            if not collected:
                yield "I couldn't find any IT-related articles from trusted sources."
                return

            results = sorted(collected, key=lambda r: r.get("parsed_date") or datetime.min, reverse=True)[:3]

            # Ask user for confirmation if all are stale
            if all(r["is_stale"] for r in results):
                if session_id:
                    session_state_flags[session_id] = {
                        "offered_old_trends": True,
                        "stale_results": results
                    }
                yield "I found articles, but all are older than your requested timeframe. Would you like to see them anyway?"
                return

            if all(r.get("parsed_date") and (datetime.now() - r["parsed_date"]).days > 60 for r in results):
                yield "⚠️ The most recent articles I found are over 2 months old. Let me know if you'd like a more specific topic or source."

    for r in results:
        logging.info(f"[Selected Result] {r['title']} → {r['link']}")

    context = "\n\n".join(
        f"{r['title']}\n{r['snippet']}\n{r['link']}\n"
        + (f"Published: {r['parsed_date'].strftime('%Y-%m-%d')}" if r['parsed_date'] else "Publication date unknown")
        for r in results
    )

    prompt = external_prompt_template.format(context=context) + (
            "\n\n(Note for the assistant:\n"
            "- Cite publication dates when available.\n"
            "- Prioritize the most recent IT trend insights.\n"
            "- Label older content if necessary.\n)"
            f'\n\n(Original user query: \"{user_input}\"'
            + (", using fallback search)" if 'fallback_used' in locals() and fallback_used else ")")
    )

    logging.info(f"External GPT Prompt:\n{prompt[:1000]}")
    if session_id:
        log_async(store_message, session_id, user_input, "user")

    stream = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        stream=True
    )

    full_reply = ""
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            full_reply += delta
            yield delta

    if session_id:
        log_async(store_message, session_id, full_reply, "bot")
def handle_external_query_streaming(user_input, session_id=None):
    import dateutil.parser
    from app.config import DB_CONFIG
    import psycopg2

    timeframe = extract_timeframe(user_input)
    start, end = start, timeframe["end"]

    domain_sets = [
        ["mckinsey.com", "gartner.com", "forrester.com"],
        ["techcrunch.com", "zdnet.com", "wired.com", "csoonline.com", "cio.com", "informationweek.com"]
    ]
    fallback_used = False
    collected = []

    for domains in domain_sets:
        domain_query = " OR ".join(f"site:{d}" for d in domains)
        full_query = f"{user_input} {domain_query}"
        search_data = search_web(full_query)
        logging.info(f"[Serper] Search query: {full_query}")
        logging.info(f"[Serper] Search result keys: {list(search_data.keys())}")

        def is_it_domain(link):
            domain = urlparse(link).netloc
            return any(d in domain for d in domains)

        if "organic" in search_data and search_data["organic"]:
            raw_results = search_data["organic"]
            for r in raw_results:
                title = r.get("title", "")
                snippet = r.get("snippet", "")
                link = r.get("link", "")
                if (
                        len(title) > 30 and len(snippet) > 50 and "http" in link and
                        is_it_domain(link)
                ):
                    try:
                        date_match = re.search(r'\b\d{4}-\d{2}-\d{2}\b', snippet)
                        dt = dateutil.parser.parse(date_match.group()) if date_match else None
                    except:
                        dt = None
                    is_stale = not dt or dt < start or dt > end
                    collected.append({
                        "title": title,
                        "snippet": snippet,
                        "link": link,
                        "parsed_date": dt,
                        "is_stale": is_stale
                    })
            if collected:
                break
            else:
                fallback_used = True

    # If still empty, fallback to DB
    if not collected:
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()
            cur.execute("""
                SELECT title, snippet, link, publication_date
                FROM external_articles
                WHERE publication_date BETWEEN %s AND %s
                ORDER BY publication_date DESC
                LIMIT 3;
            """, (start.date(), end.date()))
            db_results = cur.fetchall()
            cur.close()
            conn.close()

            for title, snippet, link, pub_date in db_results:
                collected.append({
                    "title": title,
                    "snippet": snippet,
                    "link": link,
                    "parsed_date": pub_date,
                    "is_stale": False
                })
        except Exception as e:
            logging.error(f"[DB fallback error] {e}")

    if not collected:
        yield "I couldn't find any IT-related articles from trusted sources."
        return

    results = sorted(collected, key=lambda r: r.get("parsed_date") or datetime.min, reverse=True)[:3]

    if all(r["is_stale"] for r in results):
        if session_id:
            session_state_flags[session_id] = {
                "offered_old_trends": True,
                "stale_results": results
            }
        yield "I found articles, but all are older than your requested timeframe. Would you like to see them anyway?"
        return

    context = "\n\n".join(
        f"{r['title']}\n{r['snippet']}\n{r['link']}\n" +
        (f"Published: {r['parsed_date'].strftime('%Y-%m-%d')}" if r['parsed_date'] else "Publication date unknown")
        for r in results
    )

    prompt = external_prompt_template.format(context=context) + (
            "\n\n(Note for the assistant:\n"
            "- Cite publication dates when available.\n"
            "- Prioritize the most recent IT trend insights.\n"
            "- Label older content if necessary.\n)"
            f'\n\n(Original user query: "{user_input}"' +
            (", using fallback search)" if fallback_used else ")")
    )

    logging.info(f"External GPT Prompt:\n{prompt[:1000]}")
    if session_id:
        log_async(store_message, session_id, user_input, "user")

    stream = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        stream=True
    )

    full_reply = ""
    try:
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                full_reply += delta
                yield delta
    except Exception as e:
        logging.error(f"Streaming error: {e}")
        yield "\n[Error generating response]"

    if session_id and full_reply.strip():
        log_async(store_message, session_id, full_reply.strip(), "bot")

def company_info_handler_streaming(user_input, session_id=None):
    prompts = get_prompts()
    detected_intent = classify_intent(user_input)

    # 🔍 Handle trend/fresh intent by forcing external query with web-first
    if "trend" in user_input.lower() and needs_fresh_trends(user_input):
        yield from handle_external_query_streaming(user_input, session_id)
        return

    # 🧠 Handle known intents with fallback
    if detected_intent == "External Search" or any(x in user_input.lower() for x in ["mckinsey", "gartner"]):
        yield from handle_external_query_streaming(user_input, session_id)
        return

    if detected_intent == "Human Support":
        reply = prompts["static_replies"]["human_support"]
        if session_id:
            reply += f" When contacting support, please mention your session ID: {session_id}"
            log_async(store_message, session_id, user_input, "user")
            log_async(store_message, session_id, reply, "bot")
        yield reply
        return

    if detected_intent == "IT Services":
        if needs_fresh_trends(user_input):
            yield from handle_external_query_streaming(user_input, session_id)
            return
        else:
            reply = handle_it_services(user_input, session_id)
            yield reply
            return

    if detected_intent == "Memory":
        reply = handle_meta_questions(user_input, session_id)
        yield reply
        return

    if "trend" in user_input.lower():
        yield from handle_external_query_streaming(user_input, session_id)
        return

    # 🧠 Semantic & Hybrid search fallback
    search_results = hybrid_search(user_input, top_k=5)
    if not search_results:
        embedding = embed_query_cached(user_input)
        if embedding:
            search_results = semantic_search(embedding, top_k=5)

    if not search_results:
        yield "I couldn't find anything relevant in Bravur's data. Try rephrasing your question."
        return

    semantic_context = "\n\n".join([
        f"Row ID: {row_id}\nTitle: {title}\nContent: {content}"
        for row_id, title, content, _ in search_results
    ])

    system_prompt = prompts["gpt_prompts"]["system"].format(context=semantic_context)
    gpt_prompt = [{"role": "system", "content": system_prompt}] + get_recent_conversation(session_id) + [{"role": "user", "content": user_input}]

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

        if session_id and full_reply.strip():
            log_async(store_message, session_id, user_input, "user")
            log_async(store_message, session_id, full_reply.strip(), "bot")

    except Exception as e:
        logging.error(f"Streaming error: {e}")
        yield "\n[Error generating response]"

def is_last_question_request(user_input):
    prompts = get_prompts()
    return any(
        fuzz.partial_ratio(user_input.lower(), prompt) > 80
        for prompt in prompts["intent_detection"]["memory_prompts"]
    )


agent_connector.register_agent("Bravur_Information_Agent", company_info_handler_streaming)
