import logging
import re
import json
import threading
import os
from functools import lru_cache
from hashlib import sha256
from openai import OpenAI
from fuzzywuzzy import fuzz

from app.config import OPENAI_API_KEY
from app.database import (
    get_session_messages, store_message,
    hybrid_search, semantic_search, embed_query
)
from app.agentConnector import AgentConnector
from app.web import search_web  # ✅ Correct path

client = OpenAI(api_key=OPENAI_API_KEY)
agent_connector = AgentConnector()
embedding_cache = {}

# ✅ Prompt loading utilities
@lru_cache(maxsize=1)
def load_prompts(file_name):
    try:
        with open(os.path.join("app", "prompts", file_name), "r") as f:
            return json.load(f)
    except FileNotFoundError:
        logging.error(f"Prompt file {file_name} not found")
        raise
    except json.JSONDecodeError:
        logging.error(f"Invalid JSON in {file_name}")
        raise

# ✅ Load prompts
external_source_prompts = load_prompts("external_source_prompts.json")
gpt_prompts = load_prompts("gpt_prompts.json")
static_replies = load_prompts("static_replies.json")
intent_detection = load_prompts("intent_detection.json")

def get_prompts():
    return {
        "gpt_prompts": gpt_prompts,
        "static_replies": static_replies,
        "intent_detection": intent_detection
    }

def is_last_question_request(user_input):
    prompts = get_prompts()
    return any(fuzz.partial_ratio(user_input.lower(), prompt) > 80 for prompt in prompts["intent_detection"]["memory_prompts"])

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
    memory_prompts = intent_detection["memory_prompts"]
    if any(prompt in user_input.lower() for prompt in memory_prompts):
        return "Memory"
    keywords = user_input.lower()
    if any(word in keywords for word in ["bravur", "company", "mission", "services"]):
        return "Company Info"
    if any(word in keywords for word in ["support", "contact", "help"]):
        return "Human Support"
    if any(word in keywords for word in ["trend", "ai", "cybersecurity", "automation"]):
        return "IT Services"
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": f"Classify: {user_input} as 'Company Info', 'IT Services', 'Human Support', or 'Memory'"}]
    )
    intent = response.choices[0].message.content
    logging.info(f"Intent for '{user_input}': {intent}")
    return intent

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
    recent_convo = get_recent_conversation(session_id)
    gpt_prompt = [
        {"role": "system", "content": gpt_prompts["it_services"]},
        *recent_convo,
        {"role": "user", "content": user_input}
    ]
    reply = gpt_cached_response("gpt-4o-mini", tuple(gpt_prompt)).strip()
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
        summary_prompt = [{"role": "system", "content": gpt_prompts["summary"]}] + formatted
        return gpt_cached_response("gpt-4o-mini", tuple(summary_prompt)).strip()
    return "I'm not sure what you're referring to. Could you clarify?"

@lru_cache(maxsize=256)
def gpt_cached_response(model, messages_as_tuple):
    messages = json.loads(json.dumps(messages_as_tuple))
    response = client.chat.completions.create(model=model, messages=messages)
    return response.choices[0].message.content

def call_gpt(prompt):
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.strip()

def handle_external_query_streaming(user_input, session_id=None):
    try:
        search_data = search_web(user_input)
        if "organic" in search_data:
            results = search_data["organic"][:3]
            context = "\n\n".join(f"{r['title']}\n{r['snippet']}\n{r['link']}" for r in results)
        else:
            context = "No relevant results found."
        prompt = external_source_prompts["search"].format(context=context)
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
    except Exception as e:
        logging.error(f"Streaming external query failed: {e}")
        yield "\n[Error generating response]"

def company_info_handler_streaming(user_input, session_id=None):
    detected_intent = classify_intent(user_input)
    if any(x in user_input.lower() for x in ["mckinsey", "gartner"]):
        yield from handle_external_query_streaming(user_input, session_id)
        return
    if detected_intent == "Human Support":
        reply = static_replies["human_support"]
        if session_id:
            reply += f" When contacting support, please mention your session ID: {session_id}"
            log_async(store_message, session_id, user_input, "user")
            log_async(store_message, session_id, reply, "bot")
        yield reply
        return
    if detected_intent == "IT Services":
        reply = handle_it_services(user_input, session_id)
        yield reply
        return
    if detected_intent == "Memory":
        reply = handle_meta_questions(user_input, session_id)
        yield reply
        return
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
    system_prompt = gpt_prompts["system"].format(context=semantic_context)
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
        if session_id:
            log_async(store_message, session_id, user_input, "user")
            log_async(store_message, session_id, full_reply, "bot")
    except Exception as e:
        logging.error(f"Streaming error: {e}")
        yield "\n[Error generating response]"

agent_connector.register_agent("Bravur_Information_Agent", company_info_handler_streaming)
