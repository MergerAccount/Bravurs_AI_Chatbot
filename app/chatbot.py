# app/chatbot.py
import logging
import re
import json
import threading
import random  # From develop
import textwrap  # From develop
from functools import lru_cache
from hashlib import sha256
from app.database import is_session_expired

from groq import Groq
from openai import OpenAI
from fuzzywuzzy import fuzz
from flask import session
from app.agentConnector import AgentConnector

from app.config import OPENAI_API_KEY, GROQ_API_KEY
from app.database import (
    get_session_messages, store_message,
    hybrid_search,
    embed_query
)
from app.web import search_web

# Initialize OpenAI client (for RAG response generation with GPT-4o Mini & embeddings via database.py)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Initialize Groq client (for fast intent classification & potentially IT Trends responses)
groq_client = Groq(api_key=GROQ_API_KEY)


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
UNKNOWN_INTENT_MESSAGES = {
    "en-US": [
        "I'm here to answer questions about Bravur and IT services. What would you like to know? 🤔",
        "I specialize in Bravur topics and IT trends. How can I assist you with those? 💡",
        "My expertise is in Bravur services and general IT matters. What can I help you explore? 🤔",
        "I'm best at discussing Bravur and technology topics. What interests you most? 💻",
        "Let’s keep it Bravur or IT trend-focused — what would you like to discuss? ⚡"
    ],
    "nl-NL": [
        "Ik ben hier om vragen over Bravur en IT-diensten te beantwoorden. Wat zou je willen weten? 🤔",
        "Ik ben gespecialiseerd in Bravur-onderwerpen en IT-trends. Hoe kan ik je daarmee helpen? 💡",
        "Mijn expertise ligt bij Bravur-diensten en algemene IT-zaken. Wat kan ik voor je uitzoeken? 🤔",
        "Ik ben het best in het bespreken van Bravur en technologische onderwerpen. Wat interesseert je het meest? 💻",
        "Laten we het Bravur- of IT-trendgericht houden — wat zou je willen bespreken? ⚡"
    ]
}

# Pool of contact support endings for unknown queries
UNKNOWN_SUPPORT_ENDINGS = {
    "en-US": [
        " By the way, if you need human support, our team is available on WhatsApp at +31 6 12345678 or email support@bravur.com - they're smarter than me! 😄",
        " If you'd prefer chatting with a real human (who probably knows more than me), reach out to +31 6 12345678 or support@bravur.com! 😊",
        " For anything beyond my expertise, our human support team at +31 6 12345678 or support@bravur.com can help. 🌟",
        " If I'm not hitting the mark, our fantastic human team at +31 6 12345678 or support@bravur.com is ready to save the day! 🦸‍♂️",
        " And if it's something I can't answer, our brilliant team at +31 6 12345678 or support@bravur.com has all the deep Bravur knowledge you need. 🧠"
    ],
    "nl-NL": [
        " Trouwens, als je menselijke ondersteuning nodig hebt, is ons team beschikbaar via WhatsApp op +31 6 12345678 of per e-mail op support@bravur.com - zij zijn slimmer dan ik! 😄",
        " Als je liever met een echt mens chat (die waarschijnlijk meer weet dan ik), neem dan contact op via +31 6 12345678 of support@bravur.com! 😊",
        " Voor alles buiten mijn expertise kan ons menselijke supportteam via +31 6 12345678 of support@bravur.com helpen. 🌟",
        " Als ik de plank missla, staat ons fantastische menselijke team via +31 6 12345678 of support@bravur.com klaar om de dag te redden! 🦸‍♂️",
        " En als het iets is dat ik niet kan beantwoorden, heeft ons briljante team via +31 6 12345678 of support@bravur.com alle diepgaande Bravur-kennis die je nodig hebt. 🧠"
    ]
}


# Session ID suffix for human support jokes
def get_session_id_suffix(session_id: str, language: str = "en-US") -> str:
    """Generate session ID mention for human support contact in the correct language."""
    if not session_id or session_id == "default":
        return ""

    if language == "nl-NL":
        return f" Vermeld alstublieft uw sessie-ID: {session_id} wanneer u contact opneemt."
    else:
        return f" Please mention your session ID: {session_id} when contacting them."


def get_random_unknown_message(session_id: str, language: str = "en-US") -> str:  # Added language parameter
    """
    Get a randomized unknown intent message in the specified language,
    ensuring variety within each session for that language.
    """
    # Determine the language code to use, defaulting to English if invalid
    lang_code = language if language in UNKNOWN_INTENT_MESSAGES else "en-US"
    logging.debug(f"get_random_unknown_message called with language: {language}, resolved to lang_code: {lang_code}")

    # Ensure session_id structure exists
    if session_id not in session_unknown_messages:
        session_unknown_messages[session_id] = {}

    # Ensure language-specific structure exists within the session
    if lang_code not in session_unknown_messages[session_id]:
        session_unknown_messages[session_id][lang_code] = {
            'unused_messages': UNKNOWN_INTENT_MESSAGES[lang_code].copy(),
            'unused_support_endings': UNKNOWN_SUPPORT_ENDINGS[lang_code].copy()
        }

    session_lang_data = session_unknown_messages[session_id][lang_code]

    # If we've used all messages for this language, reset its pool
    if not session_lang_data['unused_messages']:
        logging.debug(f"Resetting unused messages for session {session_id}, lang {lang_code}")
        session_lang_data['unused_messages'] = UNKNOWN_INTENT_MESSAGES[lang_code].copy()

    # If we've used all support endings for this language, reset its pool
    if not session_lang_data['unused_support_endings']:
        logging.debug(f"Resetting unused support endings for session {session_id}, lang {lang_code}")
        session_lang_data['unused_support_endings'] = UNKNOWN_SUPPORT_ENDINGS[lang_code].copy()

    # Randomly select from unused messages and jokes for the current language
    selected_message = random.choice(session_lang_data['unused_messages'])
    selected_support_ending = random.choice(session_lang_data['unused_support_endings'])  # Changed from selected_joke

    # Remove selected items from unused pools for the current language
    try:
        session_lang_data['unused_messages'].remove(selected_message)
    except ValueError:  # Should not happen if reset logic is correct, but good for safety
        logging.warning(
            f"Could not remove selected_message for session {session_id}, lang {lang_code}. Pool might have been reset.")
        session_lang_data['unused_messages'] = UNKNOWN_INTENT_MESSAGES[lang_code].copy()
        if selected_message in session_lang_data['unused_messages']:
            session_lang_data['unused_messages'].remove(selected_message)

    try:
        session_lang_data['unused_support_endings'].remove(selected_support_ending)
    except ValueError:
        logging.warning(
            f"Could not remove selected_support_ending for session {session_id}, lang {lang_code}. Pool might have been reset.")
        session_lang_data['unused_support_endings'] = UNKNOWN_SUPPORT_ENDINGS[lang_code].copy()  # Force reset
        if selected_support_ending in session_lang_data['unused_support_endings']:
            session_lang_data['unused_support_endings'].remove(selected_support_ending)

    # Add session ID suffix if session exists, using the correct language
    session_suffix = get_session_id_suffix(session_id, lang_code)

    final_message = selected_message + selected_support_ending + session_suffix
    logging.info(f"Generated unknown message for lang {lang_code}: '{final_message[:100]}...'")
    return final_message


def log_async(fn, *args):
    threading.Thread(target=fn, args=args).start()


def strip_html_paragraphs(text):
    return re.sub(r"^<p>(.*?)</p>$", r"\1", text.strip(), flags=re.DOTALL)


def estimate_tokens(text):
    return max(1, int(len(text.split()) * 0.75))


# --- get_recent_conversation: (includes latest_language_message logic) ---
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
        selected = [msg for msg in selected if latest_language_message["content"] not in msg.get("content", "")]
        selected.insert(0, latest_language_message)

    logging.debug(f"get_recent_conversation (session {session_id}, {len(selected)} msgs, ~{total_tokens} tokens)")
    return selected


# --- has_strong_contextual_cues ---
def has_strong_contextual_cues(user_input: str) -> bool:
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


# --- STAGE 1: INITIAL STATELESS INTENT CLASSIFIER (using Groq) ---
def initial_classify_intent(user_input: str, language: str = "en-US") -> str:
    if is_gratitude_expression(user_input):
        logging.info(f"Fast classification: Gratitude detected in '{user_input}'")
        return "Gratitude"

    mood = detect_mood(user_input)
    if mood == "happy" and len(user_input.split()) <= 4:
        logging.info(f"Fast classification: Positive Acknowledgment detected in '{user_input}'")
        return "Positive Acknowledgment"

    if mood == "angry" and len(user_input.split()) <= 10:
        logging.info(f"Fast classification: Frustration detected in '{user_input}'")
        return "Frustration"

    language_name = "Dutch" if language == "nl-NL" else "English"
    intent_categories_initial = ["Human Support Service Request", "IT Trends", "Company Info",
                                 "Previous Conversation Query", "Unknown", "Positive Acknowledgment", "Frustration"]
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
User Query: "Thanks!" -> Classified Intent: Gratitude
User Query: "Thank you for your support." -> Classified Intent: Gratitude
User Query: "Much appreciated." -> Classified Intent: Gratitude
User Query: "Is there a thank-you note template?" -> Classified Intent: Unknown

---
User Query (in {language_name}): "{user_input}"

Strictly respond with ONLY one category name from the list above.
Classified Intent:"""
    try:
        classification_model = "llama-3.3-70b-versatile"

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


# --- STAGE 2: CONTEXTUAL RESOLUTION / META QUESTION HANDLER:
def resolve_contextual_query(user_input: str, recent_convo: list, session_id: str, language: str = "en-US"):

    language_name = "Dutch" if language == "nl-NL" else "English"
    lower_user_input = user_input.lower()

    if any(fuzz.partial_ratio(lower_user_input, prompt) > 80 for prompt in MEMORY_PROMPTS_KEYWORDS):
        logging.info(f"CONTEXTUAL RESOLUTION: Handling explicit memory prompt: '{user_input}'")
        # Last Question
        if any(fuzz.partial_ratio(lower_user_input, p) > 80 for p in
               ["what was my last question", "my previous question", "what did I ask before",
                "tell me my last question"]):
            user_qs = [m['content'] for m in recent_convo if m['role'] == 'user']
            if len(user_qs) > 1:
                if language == "nl-NL":
                    return {"type": "direct_answer", "content": f"Je vorige vraag was: \"{user_qs[-2]}\""}
                else:
                    return {"type": "direct_answer", "content": f"Your last question was: \"{user_qs[-2]}\""}
                # For "couldn't find"
            if language == "nl-NL":
                return {"type": "direct_answer", "content": "Hmm, ik kon je vorige vraag niet vinden."}
            else:
                return {"type": "direct_answer", "content": "Hmm, I couldn't find your previous question."}
        # Last Answer
        if any(fuzz.partial_ratio(lower_user_input, p) > 80 for p in ["your last answer", "what you said before"]):
            for msg in reversed(recent_convo):
                if msg['role'] == 'assistant': return {"type": "direct_answer",
                                                       "content": f"My last reply was: \"{msg['content']}\""}
            return {"type": "direct_answer", "content": "I couldn't recall what I said last time."}
        # Summarize
        if any(fuzz.partial_ratio(lower_user_input, p) > 80 for p in ["summarize our talk", "recap this"]):
            summary_prompt_messages = [{"role": "system",
                                        "content": f"Give a short and friendly summary of this conversation about Bravur/IT in {language_name}."}] + recent_convo
            try:
                completion = groq_client.chat.completions.create(messages=summary_prompt_messages,
                                                                 model="llama-3.3-70b-versatile", temperature=0.5,
                                                                 max_tokens=200)
                summary = completion.choices[0].message.content.strip()
                return {"type": "direct_answer", "content": f"Here's a friendly summary of our chat: 😊\n{summary}"}
            except Exception as e:
                logging.error(f"Summarization error: {e}");
                return {"type": "refined_intent", "intent": "Unknown",
                        "query": user_input}
        logging.info(f"Memory prompt '{user_input}' not directly handled by simple checks, attempting LLM refinement.")

    # LLM for general contextual refinement
    intent_categories_refined = ["Company Info", "IT Trends", "Human Support Service Request", "Unknown"]
    history_str_parts = [f"{msg['role']}: {msg['content']}" for msg in
                         recent_convo]
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


# --- Helper functions for tone/formatting ---
def detect_mood(user_input: str) -> str:
    angry_keywords = ["stupid", "hate", "idiot", "angry", "mad", "annoyed", "wtf", "useless", "terrible", "awful", "disappointed"]
    happy_keywords = ["love", "great", "awesome", "thanks", "cool", "nice", "amazing", "perfect", "excellent"]
    input_lower = user_input.lower()
    if any(word in input_lower for word in angry_keywords): return "angry"
    if any(word in input_lower for word in happy_keywords): return "happy"
    return "neutral"

def is_gratitude_expression(user_input: str) -> bool:
    text = user_input.lower().strip()

    # Block if it's clearly a question about gratitude
    if text.endswith("?") or any(
            phrase in text for phrase in [
                "how to say", "considered too casual", "thank you note",
                "thank-you email", "example of", "is thank", "best way to say"
            ]
    ):
        return False

    # Fuzzy match common gratitude intent templates
    gratitude_examples = [
        "thank you", "thanks", "thanks a lot", "much appreciated",
        "i appreciate it", "really appreciate your help",
        "i'm grateful", "thank u"
    ]

    for example in gratitude_examples:
        if fuzz.partial_ratio(text, example) > 85:
            return True

    return False

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
    if session_id and is_session_expired(session_id):
        yield "⏳ Your session has expired after 3 days. Please start a new session to continue chatting with me. 😊"
        return

    language_name = "Dutch" if language == "nl-NL" else "English"
    logging.info(
        f"--- START HANDLER: Query='{user_input}', Session={session_id}, Lang={language} ({language_name}) ---")

    # Make sure initial_classify_intent and resolve_contextual_query are passed the 'language'
    detected_intent = initial_classify_intent(user_input, language)  # Pass language
    user_mood = detect_mood(user_input)
    logging.info(f"User mood detected as: {user_mood}")

    # --- Human Support (Internationalize this response too) ---
    if detected_intent == "Human Support Service Request":
        logging.info(f"Handling as: Human Support (Initial)")
        if language == "nl-NL":
            reply = "Natuurlijk! Je kunt ons menselijke supportteam bereiken via WhatsApp op +31 6 12345678 of per e-mail op support@bravur.com."
            if session_id: reply += f" Vermeld alstublieft uw sessie-ID: {session_id} wanneer u contact opneemt. Hoe kan ik je ondertussen helpen? 😊"
        else:
            reply = ("You can reach our human support team on WhatsApp at +31 6 12345678 "
                     "or by email at support@bravur.com.")
            if session_id: reply += f" When contacting support, please mention your session ID: {session_id}. How can I help in the meantime? 😊"
        yield reply
        return

    # --- Contextual Check / Refinement ---
    if detected_intent == "Previous Conversation Query" or \
            (detected_intent == "Unknown" and has_strong_contextual_cues(user_input)):
        logging.info(
            f"Triggering Contextual Resolution (Initial: {detected_intent}, Cues: {has_strong_contextual_cues(user_input)}) for: '{user_input}'")
        recent_convo_for_context = get_recent_conversation(session_id)
        if recent_convo_for_context or any(
                fuzz.partial_ratio(user_input.lower(), p) > 80 for p in MEMORY_PROMPTS_KEYWORDS):
            # Pass language to the context resolver
            context_result = resolve_contextual_query(user_input, recent_convo_for_context, session_id, language)
            # ... (rest of context_result handling) ...
            logging.info(f"Context resolution result: {context_result}")
            if context_result["type"] == "direct_answer":
                logging.info(f"Handling as: Direct Answer from Context: '{context_result['content'][:100]}...'")
                yield clean_and_clip_reply(context_result["content"], max_sentences=3, max_chars=350);
                return
            elif context_result["type"] == "refined_intent":
                detected_intent = context_result["intent"]
        else:
            logging.info(f"Contextual cues, but no history. Treating as Unknown.")
            detected_intent = "Unknown"
    # Runtime memory of past gratitude replies
    recent_gratitude_replies = []

    if detected_intent == "Gratitude":
        logging.info(f"Handling as: Gratitude in {language_name}")

        # --- Language-Specific Prompts and Fallbacks for Gratitude ---
        if language == "nl-NL":
            gratitude_system_prompt_content = (
                "Je bent een vriendelijke en expressieve AI-assistent. Een gebruiker heeft je zojuist bedankt.\n\n"
                "Antwoord hartelijk en natuurlijk in het Nederlands in 1-2 zinnen. Herhaal NIET elke keer hetzelfde antwoord.\n"
                "Gebruik verschillende uitdrukkingen zoals:\n"
                "- Absoluut! Laat het me weten als ik nog iets kan betekenen.\n"
                "- Altijd! 😊\n"
                "- Graag gedaan. Ik ben er voor meer vragen als je die hebt.\n"
                "- Fijn om te helpen! Vraag gerust meer.\n"
                "- Met alle plezier. Heb je nog meer vragen?\n\n"
                "Varieer je taalgebruik en toon om menselijk over te komen, niet robotachtig."
            )
            gratitude_fallback_responses = [
                "Graag gedaan! Laat het me weten als ik nog iets kan betekenen. 😊",
                "Geen dank! Altijd hier om te helpen.",
                "Altijd! Ik ben er als er meer vragen opkomen."
            ]
        else:  # Default to English
            gratitude_system_prompt_content = (
                "You are a friendly and expressive AI assistant. A user has just said thank you.\n\n"
                "Reply warmly and naturally in English in 1–2 sentences. Do NOT repeat the same reply every time.\n"
                "Use different expressions like:\n"
                "- Absolutely! Let me know if I can help with anything else.\n"
                "- Anytime! 😊\n"
                "- You got it. I'm here for more questions if you have any.\n"
                "- Happy to help! Feel free to ask more.\n"
                "- Always a pleasure. Got more questions?\n\n"
                "Vary your language and tone to feel human, not robotic. Avoid repeating the same response in this conversation."
            )
            gratitude_fallback_responses = [
                "Sure thing! Let me know if I can help with anything else. 😊",
                "You're welcome! Always here to help.",
                "Anytime! I'm here if more questions come up."
            ]

        gratitude_prompt_messages = [
            {"role": "system", "content": gratitude_system_prompt_content},
            {"role": "user", "content": user_input}
        ]

        # Session-based tracking for gratitude replies per language
        session_key = f"{session_id or 'default'}_{language}"  # Use 'default' if session_id is None
        if session_key not in session_unknown_messages:
            session_unknown_messages[session_key] = {'recent_gratitude_replies': []}
        elif 'recent_gratitude_replies' not in session_unknown_messages[session_key]:
            session_unknown_messages[session_key]['recent_gratitude_replies'] = []

        recent_gratitude_replies_for_lang = session_unknown_messages[session_key]['recent_gratitude_replies']

        try:
            reply = None
            MAX_TRIES = 5  # Try a few times to get a unique response

            for _ in range(MAX_TRIES):
                completion = groq_client.chat.completions.create(
                    messages=gratitude_prompt_messages,
                    model="llama-3.3-70b-versatile",  # Smaller, faster model is fine for this
                    temperature=random.uniform(0.75, 0.95),  # Encourage more variety
                    max_tokens=60
                )
                candidate = completion.choices[0].message.content.strip()

                # Simple check for variety
                if candidate and candidate not in recent_gratitude_replies_for_lang:
                    reply = candidate
                    recent_gratitude_replies_for_lang.append(reply)
                    if len(recent_gratitude_replies_for_lang) > 10:  # Keep memory of last 10
                        recent_gratitude_replies_for_lang.pop(0)
                    break

            if not reply:  # Fallback if LLM struggles or repeats too much
                reply = random.choice(gratitude_fallback_responses)

            logging.info(f"Gratitude response in {language_name}: {reply}")
            yield reply
            return

        except Exception as e:
            logging.error(f"LLM Gratitude Generation Error: {e}")
            yield random.choice(gratitude_fallback_responses)  # Fallback on error
            return

    if detected_intent == "Positive Acknowledgment":
        logging.info(f"Handling as: Positive Acknowledgment in {language_name}")
        if language == "nl-NL":
            reply = "Fijn dat je dat goed vond! 😊 Laat het me weten als je meer vragen hebt."
        else: # Default to English
            reply = "Glad you liked that! 😊 Let me know if you have more questions."
        yield reply
        return

    if detected_intent == "Frustration":
        logging.info(f"Handling as: Frustration in {language_name}")
        if language == "nl-NL":
            reply = ("Het spijt me dat dat niet hielp. 😔 Ik ben hier om je te helpen — kun je me meer vertellen "
                     "zodat ik het antwoord kan verbeteren of je kan doorverbinden met support?")
        else: # Default to English
            reply = ("I'm sorry that wasn't helpful. 😔 I'm here to assist you — could you tell me more "
                     "so I can improve the answer or connect you with support?")
        yield reply
        return

    logging.info(f"Proceeding with final intent: '{detected_intent}' for query: '{user_input}'")

    if detected_intent == "Unknown":
        logging.info(f"Handling as: Unknown (Final)")
        # Using randomized unknown messages with jokes
        random_message = get_random_unknown_message(session_id or "default", language)
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
        logging.info(f"Handling as: IT Trends (SerperAPI) for query: '{user_input}'")
        yield "Searching the web for the latest IT trends... 🌐\n"

        site_constraints_list = []
        user_input_lower = user_input.lower()
        if "mckinsey" in user_input_lower:
            site_constraints_list.append("site:mckinsey.com")
        if "gartner" in user_input_lower:
            site_constraints_list.append("site:gartner.com")

        site_constraint_query_str = " OR ".join(site_constraints_list) if site_constraints_list else None

        search_data = search_web(user_input, site_constraint=site_constraint_query_str)

        search_snippets = []
        if search_data.get("error"):
            logging.warning(f"SerperAPI search returned an error: {search_data['error']}")
        elif "organic" in search_data and search_data["organic"]:
            results = search_data["organic"][:5]  # Process top 5 relevant results
            for r_item in results:
                title = r_item.get('title', 'N/A')
                link = r_item.get('link', 'N/A')
                snippet_text = r_item.get('snippet', 'N/A')
                if title and link and snippet_text:  # Ensure essential parts are present
                    search_snippets.append(f"Title: {title}\nLink: {link}\nSnippet: {snippet_text}")
        else:
            logging.info(f"No organic results from SerperAPI search for '{user_input}'.")

        if search_snippets:
            search_context_str = "\n\n---\n\n".join(search_snippets)
            it_trends_sys_prompt = (
                f"You are a helpful AI assistant for Bravur. {tone_instruction} "
                f"The user asked about IT trends: '{user_input}'. "
                f"Below are web search results. Summarize the key information and insights related to the query. "
                f"If results from McKinsey or Gartner are present and relevant, prioritize them. "
                f"Provide a concise answer (target 3-5 sentences, but can be longer if summarizing multiple rich sources). Respond in {language_name}. "
                f"Cite relevant source links (e.g., [Source: URL]) if you use specific information from them. Avoid just listing links. "
                f"Add one relevant emoji. 🔍\n\n"
                f"Web Search Results:\n{search_context_str}"
            )
        else:  # No useful search results or search failed
            # Give feedback about search failure before general knowledge answer
            yield "I couldn't find specific details from a web search for that IT trend. I'll provide a general overview based on my knowledge.\n"
            it_trends_sys_prompt = (
                f"You are a knowledgeable AI assistant for Bravur. {tone_instruction} "
                f"A web search for '{user_input}' did not return specific results. "
                f"Please provide a general overview (max 4-5 sentences) on this IT trend based on your existing knowledge. "
                f"If you have general knowledge about reports from sources like McKinsey or Gartner on this topic, you can mention them. "
                f"Respond in {language_name}. Add one relevant emoji to make the reply engaging. 💡"
            )

        messages_for_llm = [{"role": "system", "content": it_trends_sys_prompt}] + \
                           recent_convo_for_response + \
                           [{"role": "user", "content": user_input}]

        try:
            logging.info(
                f"Using Groq Llama 3 70B for IT Trend (Serper/Fallback) response generation. System prompt starts with: {it_trends_sys_prompt[:200]}...")
            stream = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages_for_llm,
                max_tokens=450,
                temperature=0.5,
                stream=True
            )
            for chunk_obj in stream:
                if chunk_obj.choices[0].delta.content:
                    final_response_chunks.append(chunk_obj.choices[0].delta.content)
                    yield chunk_obj.choices[0].delta.content
        except Exception as e:
            logging.error(f"LLM Error (IT Trends with Serper/Fallback): {e}")
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
                entry_id, title, content, _ = item
                title_str = f"Title: {title}\n" if title else ""
                summary_content = ' '.join(content.split()[:50]) + "..."
                semantic_context_parts.append(f"Row ID: {entry_id}\n{title_str}Summary: {summary_content}")
            semantic_context_str = "\n\n---\n\n".join(semantic_context_parts)

        rag_system_prompt = (
            f"You are a helpful and conversational AI assistant for Bravur, an IT consultancy. Respond in {language_name}. {tone_instruction}"
            f"Answer the user's query based on conversation history and the 'Provided Bravur Summaries' below. "
            f"Your response should be friendly, clear, and NOT EXCEED 4-5 SENTENCES. "
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
        if language == "nl-NL":
            yield f"Ik weet niet zeker hoe ik daarmee kan helpen. Ik kan Bravur of algemene IT-onderwerpen in het {language_name} bespreken."
        else:
            yield f"I'm a bit unsure how to help with that. I can discuss Bravur or general IT topics in {language_name}."

    # After stream is complete for IT Trends or Company Info/RAG
    if final_response_chunks:
        full_bot_reply = "".join(final_response_chunks)

        logging.info(f"Final assembled response before potential clipping: '{full_bot_reply[:300]}...'")
    return

agent_connector = AgentConnector()
agent_connector.register_agent("Bravur_Information_Agent", company_info_handler_streaming)
