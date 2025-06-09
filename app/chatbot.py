# app/chatbot.py
import logging
import re
import json
import threading
import random  # From develop
import textwrap  # From develop
from functools import lru_cache
from hashlib import sha256

from groq import Groq
from openai import OpenAI
from fuzzywuzzy import fuzz

from app.agentConnector import AgentConnector

from app.config import OPENAI_API_KEY, GROQ_API_KEY
from app.database import (
    get_session_messages, store_message,
    hybrid_search,
    embed_query
)

# Initialize OpenAI client (for RAG response generation with GPT-4o Mini & embeddings via database.py)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Initialize Groq client (for fast intent classification & potentially IT Trends responses)
groq_client = Groq(api_key=GROQ_API_KEY)

# embedding_cache = {} # Not actively used in the current flow, can be removed if so

# --- Constants & Helpers ---
MEMORY_PROMPTS_KEYWORDS = [
    "what was my last question", "my previous question", "remind me my last question",
    "what did I ask before", "my earlier question", "show my previous question",
    "tell me my last question", "repeat my last question", "what did I say last",
    "your last answer", "what you said before", "summarize our talk", "recap this"
]

CONTEXTUAL_CUES_KEYWORDS = [
    "that", "it", "this", "those", "them", "previous", "last", "earlier", "again", "more about",
    "what about", "tell me more", "can you elaborate", "and about", "so about", "then about"
]

# Session-based message tracking for variety
session_unknown_messages = {}

# Pool of randomized unknown intent messages
UNKNOWN_INTENT_MESSAGES = [
    "I'm here to answer questions about Bravur and IT services. What would you like to know? 🤔",
    "I specialize in Bravur topics and IT trends. How can I assist you with those? 💡",
    "My expertise is in Bravur services and general IT matters. What can I help you explore? 🤔",
    "I'm best at discussing Bravur and technology topics. What interests you most? 💻",
    "Let’s keep it Bravur or IT trend-focused — what would you like to discuss? ⚡"
]

# Pool of joke endings for unknown queries
UNKNOWN_JOKE_ENDINGS = [
    " By the way, if you need human support, our team is available on WhatsApp at +31 6 12345678 or email support@bravur.com - they're way smarter than me! 😄",
    " If you'd prefer chatting with a real human (who probably knows more than me), reach out to +31 6 12345678 or support@bravur.com! 😊",
    " For anything beyond my expertise, our human support team at +31 6 12345678 or support@bravur.com can help. 🌟",
    " If I'm not hitting the mark, our fantastic human team at +31 6 12345678 or support@bravur.com is ready to save the day! 🦸‍♂️",
    " And if it's something I can't answer, our brilliant team at +31 6 12345678 or support@bravur.com has all the deep Bravur knowledge you need. 🧠"
]


# Session ID suffix for human support jokes
def get_session_id_suffix(session_id: str) -> str:
    """Generate session ID mention for human support contact"""
    if session_id and session_id != "default":
        return f" Please mention your session ID: {session_id} when contacting them."
    return ""


def get_random_unknown_message(session_id: str) -> str:
    """
    Get a randomized unknown intent message, ensuring variety within each session.
    Won't repeat messages until all have been used in the session.
    """
    if session_id not in session_unknown_messages:
        session_unknown_messages[session_id] = {
            'unused_messages': UNKNOWN_INTENT_MESSAGES.copy(),
            'unused_jokes': UNKNOWN_JOKE_ENDINGS.copy()
        }

    session_data = session_unknown_messages[session_id]

    # If we've used all messages, reset the pool
    if not session_data['unused_messages']:
        session_data['unused_messages'] = UNKNOWN_INTENT_MESSAGES.copy()

    if not session_data['unused_jokes']:
        session_data['unused_jokes'] = UNKNOWN_JOKE_ENDINGS.copy()

    # Randomly select from unused messages and jokes
    selected_message = random.choice(session_data['unused_messages'])
    selected_joke = random.choice(session_data['unused_jokes'])

    # Remove selected items from unused pools
    session_data['unused_messages'].remove(selected_message)
    session_data['unused_jokes'].remove(selected_joke)

    # Add session ID suffix if session exists
    session_suffix = get_session_id_suffix(session_id)

    return selected_message + selected_joke + session_suffix


def log_async(fn, *args):
    threading.Thread(target=fn, args=args).start()


def strip_html_paragraphs(text):
    return re.sub(r"^<p>(.*?)</p>$", r"\1", text.strip(), flags=re.DOTALL)


def estimate_tokens(text):
    return max(1, int(len(text.split()) * 0.75))


# --- get_recent_conversation: Taken from 'develop' branch (includes latest_language_message logic) ---
def get_recent_conversation(session_id, max_tokens=400):
    latest_language_message = None  # From develop
    if not session_id: return []

    messages = get_session_messages(session_id)
    formatted = []
    for _, content, _, msg_type in messages:
        if msg_type == "user":
            formatted.append({"role": "user", "content": content})
        elif msg_type == "bot":
            formatted.append({"role": "assistant", "content": content})
        elif msg_type == "system":
            formatted.append({"role": "system", "content": content})
            # Check if this system message is the language change one from develop
            if "[SYSTEM] Language changed" in content:
                latest_language_message = {"role": "system", "content": content}

    total_tokens = 0
    selected = []
    for msg in reversed(formatted):
        tokens = estimate_tokens(msg["content"])
        if total_tokens + tokens > max_tokens: break
        selected.insert(0, msg)
        total_tokens += tokens

    # Inject language message if it exists and isn't already the first system message
    if latest_language_message:
        # Remove any existing instances first to avoid duplication if it was already in selected
        selected = [msg for msg in selected if latest_language_message["content"] not in msg.get("content", "")]
        # Check if the first message is already a system message (e.g. main system prompt)
        # If so, insert after it. Otherwise, insert at the beginning.
        # For now, simple prepend for history, main system prompt is added separately.
        selected.insert(0, latest_language_message)

    logging.debug(f"get_recent_conversation (session {session_id}, {len(selected)} msgs, ~{total_tokens} tokens)")
    return selected


# --- has_strong_contextual_cues: From your feature branch ---
def has_strong_contextual_cues(user_input: str) -> bool:
    # ... (Your existing refined logic for this function) ...
    text_lower = user_input.lower()
    if any(fuzz.partial_ratio(text_lower, prompt) > 85 for prompt in MEMORY_PROMPTS_KEYWORDS):
        logging.debug(f"Strong Contextual Cue: Matched explicit memory prompt in '{user_input}'")
        return True
    if any(phrase in text_lower for phrase in
           ["more about that", "about that point", "the first one", "the second one", "the third one", "what about it",
            "and that"]):
        logging.debug(f"Strong Contextual Cue: Matched phrase in '{user_input}'")
        return True
    words = text_lower.split()
    if len(words) <= 3 and any(
            pronoun in words for pronoun in ["that", "it", "this", "those", "them"]) and not text_lower.startswith(
        ("what is", "what are")):
        logging.debug(f"Strong Contextual Cue: Short query with pronoun in '{user_input}'")
        return True
    logging.debug(f"No strong contextual cues detected in '{user_input}' by has_strong_contextual_cues")
    return False


# --- STAGE 1: INITIAL STATELESS INTENT CLASSIFIER: From your feature branch (using Groq) ---
def initial_classify_intent(user_input: str, language: str = "en-US") -> str:
    # ... (Your existing initial_classify_intent using Groq Llama3 8B or 70B, with refined prompt) ...
    # Make sure to use your latest refined prompt for this.
    language_name = "Dutch" if language == "nl-NL" else "English"
    intent_categories_initial = ["Human Support Service Request", "IT Trends", "Company Info",
                                 "Previous Conversation Query", "Unknown"]
    prompt_content = f"""
You are an extremely fast and efficient intent classifier for an AI support chatbot for "Bravur", an IT consultancy.
The chatbot's purpose is to assist users in {language_name} with questions about "Bravur", general "IT Trends",
or to handle "Human Support" requests. It also tries to understand "Previous Conversation Query" if the user refers to earlier parts of THIS chat.

Analyze the user's query below and make a *quick initial classification*:
- Company Info: Query is clearly and directly about Bravur or its specific offerings.
- IT Trends: Query is about general IT topics, technology concepts (cloud, AI, cybersecurity) relevant to an IT consultancy. Not for general knowledge.
- Human Support Service Request: User explicitly wants human help.
- Previous Conversation Query: If the query *strongly suggests* it's a follow-up to the ongoing conversation (e.g., uses "that", "it", "tell me more about X you said", "what was your last answer?", "summarize this chat").
- Unknown: ALL OTHER queries. This includes general knowledge facts (e.g., "height of Burj Khalifa"), off-topic questions, simple greetings without a follow-up intent. If in doubt, choose Unknown.

Examples:
User Query: "What services does Bravur offer?" -> Classified Intent: Company Info
User Query: "Explain blockchain technology." -> Classified Intent: IT Trends
User Query: "I need to talk to someone." -> Classified Intent: Human Support Service Request
User Query: "Tell me more about that." -> Classified Intent: Previous Conversation Query
User Query: "What was my last question?" -> Classified Intent: Previous Conversation Query
User Query: "Hi there!" -> Classified Intent: Unknown
User Query: "What is the capital of Australia?" -> Classified Intent: Unknown
---
User Query (in {language_name}): "{user_input}"

Strictly respond with ONLY one category name from the list above.
Classified Intent:"""  # Using llama-3.3-70b-versatile as per your last version
    try:
        classification_model = "llama-3.3-70b-versatile"  # Or llama3-8b-8192 if preferred for speed
        # ... (rest of your initial_classify_intent implementation) ...
        logging.info(f"INITIAL CLASSIFICATION for: '{user_input}' using model {classification_model}")
        chat_completion = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt_content}],
            model=classification_model, temperature=0.0, max_tokens=30
        )
        llm_response = chat_completion.choices[0].message.content.strip().replace("'", "").replace('"', '')
        logging.info(f"INITIAL LLM raw response: '{llm_response}'")
        if llm_response in intent_categories_initial:
            logging.info(f"INITIAL classified intent as: '{llm_response}'")
            return llm_response
        logging.warning(f"INITIAL LLM returned unexpected category: '{llm_response}'. Defaulting to Unknown.")
        return "Unknown"
    except Exception as e:
        logging.error(f"Error during initial LLM intent classification: {e}")
        return "Unknown"


# --- STAGE 2: CONTEXTUAL RESOLUTION / META QUESTION HANDLER: From your feature branch, with develop's friendly responses ---
def resolve_contextual_query(user_input: str, recent_convo: list, session_id: str, language: str = "en-US"):
    # ... (Your existing resolve_contextual_query using Groq Llama3 8B or 70B) ...
    # MODIFICATION: Use friendlier canned responses from 'develop' if direct_answer
    language_name = "Dutch" if language == "nl-NL" else "English"
    lower_user_input = user_input.lower()

    if any(fuzz.partial_ratio(lower_user_input, prompt) > 80 for prompt in MEMORY_PROMPTS_KEYWORDS):
        logging.info(f"CONTEXTUAL RESOLUTION: Handling explicit memory prompt: '{user_input}'")
        # Last Question
        if any(fuzz.partial_ratio(lower_user_input, p) > 80 for p in
               ["what was my last question", "my previous question", "what did I ask before",
                "tell me my last question"]):
            user_qs = [m['content'] for m in recent_convo if m['role'] == 'user']
            if len(user_qs) > 1: return {"type": "direct_answer",
                                         "content": f"Your last question was: \"{user_qs[-2]}\""}  # Using your logic
            return {"type": "direct_answer",
                    "content": "Hmm, I couldn't find your previous question."}  # develop's friendly tone
        # Last Answer
        if any(fuzz.partial_ratio(lower_user_input, p) > 80 for p in ["your last answer", "what you said before"]):
            for msg in reversed(recent_convo):
                if msg['role'] == 'assistant': return {"type": "direct_answer",
                                                       "content": f"My last reply was: \"{msg['content']}\""}  # develop's tone
            return {"type": "direct_answer", "content": "I couldn't recall what I said last time."}  # develop's tone
        # Summarize
        if any(fuzz.partial_ratio(lower_user_input, p) > 80 for p in ["summarize our talk", "recap this"]):
            summary_prompt_messages = [{"role": "system",
                                        "content": f"Give a short and friendly summary of this conversation about Bravur/IT in {language_name}."}] + recent_convo
            try:
                completion = groq_client.chat.completions.create(messages=summary_prompt_messages,
                                                                 model="llama-3.3-70b-versatile", temperature=0.5,
                                                                 max_tokens=200)
                summary = completion.choices[0].message.content.strip()
                # Potentially use clean_and_clip_reply here from develop
                return {"type": "direct_answer", "content": f"Here's a friendly summary of our chat: 😊\n{summary}"}
            except Exception as e:
                logging.error(f"Summarization error: {e}");
                return {"type": "refined_intent", "intent": "Unknown",
                        "query": user_input}
        logging.info(f"Memory prompt '{user_input}' not directly handled by simple checks, attempting LLM refinement.")

    # LLM for general contextual refinement (your prompt for this was good)
    intent_categories_refined = ["Company Info", "IT Trends", "Human Support Service Request", "Unknown"]
    history_str_parts = [f"{msg['role']}: {msg['content']}" for msg in
                         recent_convo]  # ... (your existing refinement_prompt)
    formatted_history = "\n".join(history_str_parts) if history_str_parts else "No conversation history available."
    refinement_prompt = f"""
You are an AI assistant analyzing a user's query in the context of an ongoing conversation with a support chatbot for "Bravur" (an IT consultancy).
The chatbot discusses "Company Info" (about Bravur) and "IT Trends" (general IT).

Conversation History:
{formatted_history}

User's Current Query (in {language_name}): "{user_input}"

Your Task: Based on the Conversation History and the User's Current Query, decide if the query is a clear follow-up that now falls into "Company Info", "IT Trends", or if it's genuinely "Unknown/Off-Topic".
- If the Current Query (e.g., "tell me more about that") clearly refers to a Bravur-specific topic from the History, classify as "Company Info".
- If the Current Query clearly refers to a general IT Trend from the History, classify as "IT Trends".
- If the Current Query, even with history, is about general knowledge, chit-chat, or is still too vague to relate to Bravur/IT, classify as "Unknown".
- If the Current Query or context suggests the user now needs human help, classify as "Human Support Service Request".

Strictly respond with ONLY one category name: Company Info, IT Trends, Human Support Service Request, Unknown.
Refined Intent:"""
    try:
        # ... (your existing LLM call for refinement using groq_client and llama-3.3-70b-versatile) ...
        model = "llama-3.3-70b-versatile"
        logging.info(f"CONTEXTUAL REFINEMENT (LLM Pass) for: '{user_input}' using model {model}")
        completion = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": refinement_prompt}], model=model, temperature=0.0, max_tokens=30)
        llm_response = completion.choices[0].message.content.strip().replace("'", "").replace('"', '')
        logging.info(f"CONTEXTUAL REFINEMENT LLM raw response: '{llm_response}'")
        if llm_response in intent_categories_refined:
            logging.info(f"CONTEXTUAL REFINEMENT successfully refined intent to: '{llm_response}'")
            return {"type": "refined_intent", "intent": llm_response, "query": user_input}
        logging.warning(
            f"CONTEXTUAL REFINEMENT LLM returned unexpected category: '{llm_response}'. Defaulting to Unknown.")
        return {"type": "refined_intent", "intent": "Unknown", "query": user_input}
    except Exception as e:
        logging.error(f"Error during contextual LLM refinement for '{user_input}': {e}")
        return {"type": "refined_intent", "intent": "Unknown", "query": user_input}


# --- Helper functions from 'develop' for tone/formatting ---
def detect_mood(user_input: str) -> str:
    angry_keywords = ["stupid", "hate", "idiot", "angry", "mad", "annoyed", "wtf", "useless", "terrible", "awful"]
    happy_keywords = ["love", "great", "awesome", "thanks", "cool", "nice", "amazing", "perfect", "excellent"]
    input_lower = user_input.lower()
    if any(word in input_lower for word in angry_keywords): return "angry"
    if any(word in input_lower for word in happy_keywords): return "happy"
    return "neutral"


def clean_and_clip_reply(reply, max_sentences=3, max_chars=300):  # Increased limits slightly
    # Remove duplicate consecutive phrases/lines robustly
    lines = re.split(r'(?<=[.!?])\s+', reply.strip())  # Split by sentence enders
    unique_lines = []
    if lines:
        unique_lines.append(lines[0])  # Always add the first line
        for i in range(1, len(lines)):
            # Add line if it's not empty and different from the previous unique line
            if lines[i].strip() and lines[i].strip().lower() != unique_lines[-1].strip().lower():
                unique_lines.append(lines[i].strip())

    clipped_by_sentence = " ".join(unique_lines[:max_sentences])

    # Final character clip if still too long
    if len(clipped_by_sentence) > max_chars:
        # Try to clip at a sentence boundary if possible within char limit
        last_sentence_end = clipped_by_sentence.rfind('.', 0, max_chars)
        if last_sentence_end != -1:
            final_clipped = clipped_by_sentence[:last_sentence_end + 1]
        else:  # If no sentence end, just hard clip
            final_clipped = textwrap.shorten(clipped_by_sentence, width=max_chars, placeholder="...")
    else:
        final_clipped = clipped_by_sentence

    return final_clipped.strip() if final_clipped else "I'm not sure how to respond to that, but I'm here to help with Bravur topics!"


# === MAIN STREAMING HANDLER: Your structure, with develop's tone/formatting integrated ===
def company_info_handler_streaming(user_input: str, session_id: str = None, language: str = "en-US"):
    language_name = "Dutch" if language == "nl-NL" else "English"
    logging.info(f"--- START HANDLER: Query='{user_input}', Session={session_id}, Lang={language} ---")

    detected_intent = initial_classify_intent(user_input, language)
    user_mood = detect_mood(user_input)  # From develop
    logging.info(f"User mood detected as: {user_mood}")

    if detected_intent == "Human Support Service Request":
        logging.info(f"Handling as: Human Support (Initial)")
        # Using develop's friendlier canned response
        reply = ("Of course! You can reach our human support team on WhatsApp at +31 6 12345678 "
                 "or by email at support@bravur.com.")
        if session_id: reply += f" When contacting support, please mention your session ID: {session_id}. How can I help in the meantime? 😊"
        yield reply;
        return

    if detected_intent == "Previous Conversation Query" or \
            (detected_intent == "Unknown" and has_strong_contextual_cues(user_input)):
        logging.info(
            f"Triggering Contextual Resolution (Initial: {detected_intent}, Cues: {has_strong_contextual_cues(user_input)}) for: '{user_input}'")
        recent_convo_for_context = get_recent_conversation(session_id)
        if recent_convo_for_context or any(
                fuzz.partial_ratio(user_input.lower(), p) > 80 for p in MEMORY_PROMPTS_KEYWORDS):
            context_result = resolve_contextual_query(user_input, recent_convo_for_context, session_id, language)
            logging.info(f"Context resolution result: {context_result}")
            if context_result["type"] == "direct_answer":
                logging.info(f"Handling as: Direct Answer from Context: '{context_result['content'][:100]}...'")
                # Apply develop's clipping to direct answers too for consistency
                yield clean_and_clip_reply(context_result["content"], max_sentences=3, max_chars=350);
                return  # Slightly more generous for direct answers
            elif context_result["type"] == "refined_intent":
                detected_intent = context_result["intent"]
        else:
            logging.info(f"Contextual cues, but no history. Treating as Unknown.")
            detected_intent = "Unknown"

    logging.info(f"Proceeding with final intent: '{detected_intent}' for query: '{user_input}'")

    if detected_intent == "Unknown":
        logging.info(f"Handling as: Unknown (Final)")
        # Using randomized unknown messages with jokes
        random_message = get_random_unknown_message(session_id or "default")
        yield random_message
        return

    recent_convo_for_response = get_recent_conversation(session_id)

    # --- Determine Tone Instruction (from develop) ---
    tone_instruction = "Maintain a helpful, professional, and friendly tone. "
    if user_mood == "angry":
        tone_instruction = "The user seems frustrated. Respond empathetically, very calmly, and acknowledge their frustration without being patronizing. Try to gently de-escalate. "
    elif user_mood == "happy":
        tone_instruction = "The user seems cheerful! Respond with an equally friendly, natural, and enthusiastic tone. "

    # --- Final Response Generation ---
    final_response_chunks = []
    if detected_intent == "IT Trends":
        logging.info(f"Handling as: IT Trends (Final)")
        sys_prompt = (f"You are a knowledgeable AI assistant for Bravur. {tone_instruction}"
                      f"Provide concise (max 2-3 short sentences) and clear insights on IT services and general technology trends. "
                      f"Respond in {language_name}. Add one relevant emoji to make the reply engaging. 💡")
        messages = [{"role": "system", "content": sys_prompt}] + recent_convo_for_response + [
            {"role": "user", "content": user_input}]
        try:
            # Using Groq Llama 3 70B for better quality IT Trend answers
            stream = groq_client.chat.completions.create(model="llama-3.3-70b-versatile", messages=messages,
                                                         max_tokens=300, temperature=0.6, stream=True)
            for chunk in stream:
                if chunk.choices[0].delta.content: final_response_chunks.append(chunk.choices[0].delta.content); yield \
                    chunk.choices[0].delta.content
        except Exception as e:
            logging.error(f"LLM Error (IT Trends): {e}");
            yield "[Error generating IT trends response]"

    elif detected_intent == "Company Info":  # Also catches refined "Previous Conversation Query" that became Company Info
        logging.info(f"Handling as: RAG Path for Intent='{detected_intent}'")
        query_embedding = embed_query(user_input)  # From database.py (OpenAI)
        search_results = []
        if query_embedding: search_results = hybrid_search(user_input, top_k=3)  # From database.py

        if not search_results:
            logging.info(
                f"RAG: No DB results for Company Info query: '{user_input}'. Answering from history if possible.")
            # Let the LLM try to answer from history, RAG prompt will guide it
            semantic_context_str = "No specific Bravur documents were found to be highly relevant for this query."
        else:
            semantic_context_parts = []
            for item in search_results:
                entry_id, title, content, _ = item  # Assuming (id, title, content, similarity)
                title_str = f"Title: {title}\n" if title else ""
                # Using a summary of content for the prompt as per develop's RAG approach, but keeping Row ID
                summary_content = ' '.join(content.split()[:50]) + "..."  # Summary like develop
                semantic_context_parts.append(f"Row ID: {entry_id}\n{title_str}Summary: {summary_content}")
            semantic_context_str = "\n\n---\n\n".join(semantic_context_parts)

        rag_system_prompt = (
            f"You are a helpful and conversational AI assistant for Bravur, an IT consultancy. Respond in {language_name}. {tone_instruction}"
            f"Answer the user's query based on conversation history and the 'Provided Bravur Summaries' below. "
            f"Your response should be friendly, clear, and NOT EXCEED 2-3 SHORT SENTENCES. "
            f"If using information from the summaries, CITE THE 'Row ID' like (Row ID: X). "
            f"If the answer is not in the summaries or history, say you don't have that specific detail from Bravur's documentation. "
            f"Add one relevant emoji per answer to make it engaging. ✨\n\n"
            f"Provided Bravur Summaries:\n{semantic_context_str}"
        )
        messages = [{"role": "system", "content": rag_system_prompt}] + recent_convo_for_response + [
            {"role": "user", "content": user_input}]
        try:
            # Using OpenAI GPT-4o Mini for final RAG response as requested
            stream = openai_client.chat.completions.create(model="gpt-4o-mini", messages=messages, max_tokens=300,
                                                           temperature=0.5, stream=True)
            for chunk in stream:
                if chunk.choices[0].delta.content: final_response_chunks.append(chunk.choices[0].delta.content); yield \
                    chunk.choices[0].delta.content
        except Exception as e:
            logging.error(f"LLM Error (RAG): {e}");
            yield "[Error generating RAG response]"
    else:  # Fallback if intent is somehow not covered
        logging.warning(f"Fell through main intent handling for '{detected_intent}'. Query: '{user_input}'")
        yield f"I'm a bit unsure how to help with that. I can discuss Bravur or general IT topics in {language_name}.";
        return

    # After stream is complete for IT Trends or Company Info/RAG
    if final_response_chunks:
        full_bot_reply = "".join(final_response_chunks)
        # Apply develop's clean_and_clip_reply to the *final assembled string* if needed,
        # though the prompt already asks for brevity. Yielding already happened.
        # This clipping here would only affect what's logged/stored, not what user saw.
        # For UX, brevity should be in the prompt.
        # For DB storage, maybe store the slightly longer version if clipping is aggressive.
        # For now, let's assume the LLM respects the brevity prompt.
        logging.info(f"Final assembled response before potential clipping: '{full_bot_reply[:300]}...'")
    return


agent_connector = AgentConnector()  # Ensure this is defined/imported correctly
agent_connector.register_agent("Bravur_Information_Agent", company_info_handler_streaming)
# The gpt_cached_response from your old code is not used in this streaming setup