# app/chatbot.py
import logging
import re
import json
import threading
from functools import lru_cache  # Keep for potential future caching
from hashlib import sha256  # Keep for potential future caching

from groq import Groq
from openai import OpenAI  # Still needed if database.py uses it for embeddings
from fuzzywuzzy import fuzz

from app.agentConnector import AgentConnector
from app.config import OPENAI_API_KEY, GROQ_API_KEY
from app.database import (
    get_session_messages, store_message,
    hybrid_search,  # This uses embed_query from database.py
    embed_query  # This is the OpenAI embedding function
)

# Initialize OpenAI client (specifically for database.py if it needs it for embeddings)
# If database.py initializes its own client, this might be redundant here.
# For clarity, let's assume database.py handles its own OpenAI client instance.
openai_client_for_embeddings = OpenAI(api_key=OPENAI_API_KEY)

# Initialize Groq client (for intent classification & LLM response generation)
groq_client = Groq(api_key=GROQ_API_KEY)

# --- Constants & Helpers ---
MEMORY_PROMPTS_KEYWORDS = [  # For explicit memory questions that bypass initial intent classification
    "what was my last question", "my previous question", "remind me my last question",
    "what did I ask before", "my earlier question", "show my previous question",
    "tell me my last question", "repeat my last question", "what did I say last",
    "your last answer", "what you said before", "summarize our talk", "recap this"
]

CONTEXTUAL_CUES_KEYWORDS = [  # General indicators of a follow-up
    "that", "it", "this", "those", "them", "previous", "last", "earlier", "again", "more about",
    "what about", "tell me more", "can you elaborate", "and about", "so about", "then about"
]


def log_async(fn, *args):  # Keep if you use it for store_message
    threading.Thread(target=fn, args=args).start()


def strip_html_paragraphs(text):  # Keep if your LLM might output HTML
    return re.sub(r"^<p>(.*?)</p>$", r"\1", text.strip(), flags=re.DOTALL)


def estimate_tokens(text):  # Keep for get_recent_conversation
    return max(1, int(len(text.split()) * 0.75))


def get_recent_conversation(session_id, max_tokens=400):  # Keep as is
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
    total_tokens = 0;
    selected = []
    for msg in reversed(formatted):
        tokens = estimate_tokens(msg["content"])
        if total_tokens + tokens > max_tokens: break
        selected.insert(0, msg);
        total_tokens += tokens
    logging.debug(f"get_recent_conversation (session {session_id}, {len(selected)} msgs, ~{total_tokens} tokens)")
    return selected


def has_strong_contextual_cues(user_input: str) -> bool:
    text_lower = user_input.lower()
    # Check for explicit memory prompts first
    if any(fuzz.partial_ratio(text_lower, prompt) > 85 for prompt in MEMORY_PROMPTS_KEYWORDS):
        logging.debug(f"Strong Contextual Cue: Matched explicit memory prompt in '{user_input}'")
        return True  # These are definitely contextual
    # Check for phrases that almost always imply context
    if any(phrase in text_lower for phrase in
           ["more about that", "about that point", "the first one", "the second one", "the third one", "what about it",
            "and that"]):
        logging.debug(f"Strong Contextual Cue: Matched phrase in '{user_input}'")
        return True
    # Short queries with just a pronoun are highly contextual
    words = text_lower.split()
    if len(words) <= 3 and any(pronoun in words for pronoun in ["that", "it", "this", "those", "them"]):
        logging.debug(f"Strong Contextual Cue: Short query with pronoun in '{user_input}'")
        return True
    logging.debug(f"No strong contextual cues detected in '{user_input}' by has_strong_contextual_cues")
    return False


# === STAGE 1: INITIAL STATELESS INTENT CLASSIFIER ===
def initial_classify_intent(user_input: str, language: str = "en-US") -> str:
    language_name = "Dutch" if language == "nl-NL" else "English"
    intent_categories_initial = [
        "Human Support Service Request", "IT Trends", "Company Info",
        "Previous Conversation Query",  # NEW: Add this as a possibility for the first pass
        "Unknown"
    ]
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
        logging.warning(
            f"INITIAL LLM returned unexpected category: '{llm_response}'. Defaulting to Unknown for safety.")
        return "Unknown"
    except Exception as e:
        logging.error(f"Error during initial LLM intent classification: {e}")
        return "Unknown"


# === STAGE 2: CONTEXTUAL RESOLUTION / META QUESTION HANDLER ===
def resolve_contextual_query(user_input: str, recent_convo: list, session_id: str, language: str = "en-US"):
    """
    Specifically for "Previous Conversation Query" or "Unknown" + contextual cues.
    Tries to answer meta-questions directly or re-classify based on history for Bravur/IT topics.
    Returns a dictionary: {"type": "direct_answer", "content": "..."} OR
                         {"type": "refined_intent", "intent": "...", "query": "..."}
    """
    language_name = "Dutch" if language == "nl-NL" else "English"
    lower_user_input = user_input.lower()

    # 1. Handle explicit MEMORY_PROMPTS_KEYWORDS directly (more reliable than LLM for these)
    if any(fuzz.partial_ratio(lower_user_input, prompt) > 80 for prompt in MEMORY_PROMPTS_KEYWORDS):
        logging.info(f"CONTEXTUAL RESOLUTION: Handling explicit memory prompt: '{user_input}'")
        if any(fuzz.partial_ratio(lower_user_input, p) > 80 for p in
               ["what was my last question", "my previous question", "remind me my last question",
                "what did I ask before", "my earlier question", "show my previous question", "tell me my last question",
                "repeat my last question", "what did I say last"]):
            user_messages_content = [msg['content'] for msg in recent_convo if msg['role'] == 'user']
            if len(user_messages_content) > 1: return {"type": "direct_answer",
                                                       "content": f"Your last question was: \"{user_messages_content[-2]}\""}
            return {"type": "direct_answer", "content": "I couldn't find your last question in this session."}
        if any(fuzz.partial_ratio(lower_user_input, p) > 80 for p in ["your last answer", "what you said before"]):
            for msg in reversed(recent_convo):
                if msg['role'] == 'assistant': return {"type": "direct_answer",
                                                       "content": f"My last answer was: \"{msg['content']}\""}
            return {"type": "direct_answer", "content": "I couldn't find my last answer."}
        if any(fuzz.partial_ratio(lower_user_input, p) > 80 for p in ["summarize our talk", "recap this"]):
            summary_prompt = [{"role": "system",
                               "content": f"Summarize this conversation about Bravur/IT topics concisely in {language_name}."}] + recent_convo
            try:
                completion = groq_client.chat.completions.create(messages=summary_prompt, model="llama-3.3-70b-versatile",
                                                                 temperature=0.5, max_tokens=200)
                summary = completion.choices[0].message.content.strip()
                return {"type": "direct_answer", "content": f"Here's a summary:\n{summary}"}
            except Exception as e:
                logging.error(f"Summarization error: {e}"); return {"type": "refined_intent", "intent": "Unknown",
                                                                    "query": user_input}
        # If it was a memory prompt but not caught, default to trying to refine intent
        logging.info(f"Memory prompt '{user_input}' not directly handled, attempting LLM refinement.")

    # 2. If not a direct memory_prompt, use LLM to refine intent based on context
    #    This LLM's job is to see if the vague query + history points to Company Info, IT Trends, or is still Unknown.
    intent_categories_refined = ["Company Info", "IT Trends", "Human Support Service Request",
                                 "Unknown"]  # No "Previous Conversation Query" here, it should resolve to one of these or Unknown

    history_str_parts = [f"{msg['role']}: {msg['content']}" for msg in recent_convo]
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
            messages=[{"role": "user", "content": refinement_prompt}], model=model, temperature=0.0, max_tokens=30
        )
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


# === MAIN STREAMING HANDLER ===
def company_info_handler_streaming(user_input: str, session_id: str = None, language: str = "en-US"):
    language_name = "Dutch" if language == "nl-NL" else "English"
    logging.info(f"--- STARTING HANDLER for query: '{user_input}', session: {session_id}, lang: {language} ---")

    # 1. Initial Fast Intent Classification
    detected_intent = initial_classify_intent(user_input, language)

    # 2. Handle "Human Support Service Request" immediately if detected by initial classifier
    if detected_intent == "Human Support Service Request":
        logging.info(f"Handling as: Human Support Service Request (from Initial Classification)")
        reply = "For human support, contact us on WhatsApp at +31 6 12345678 or email support@bravur.com."
        if session_id: reply += f" When contacting support, please mention your session ID: {session_id}"
        yield reply;
        return

    # 3. If initial intent is "Previous Conversation Query" OR ("Unknown" AND has strong contextual cues)
    #    then attempt contextual resolution.
    if detected_intent == "Previous Conversation Query" or \
            (detected_intent == "Unknown" and has_strong_contextual_cues(user_input)):
        logging.info(
            f"Triggering Contextual Resolution (Initial: {detected_intent}, Cues: {has_strong_contextual_cues(user_input)}) for: '{user_input}'")
        recent_convo_for_context = get_recent_conversation(session_id)

        # Proceed only if there's history to check against for contextual queries,
        # or if it was explicitly a memory prompt (which handles no history case).
        if recent_convo_for_context or any(
                fuzz.partial_ratio(user_input.lower(), prompt) > 80 for prompt in MEMORY_PROMPTS_KEYWORDS):
            context_resolution_result = resolve_contextual_query(user_input, recent_convo_for_context, session_id,
                                                                 language)
            logging.info(f"Context resolution result: {context_resolution_result}")

            if context_resolution_result["type"] == "direct_answer":
                logging.info(f"Handling as: Direct Answer from Context Resolution")
                yield context_resolution_result["content"];
                return
            elif context_resolution_result["type"] == "refined_intent":
                detected_intent = context_resolution_result["intent"]  # Update intent based on contextual understanding
                # user_input = context_resolution_result["query"] # Could use a rephrased query here if LLM provides one
        else:  # No history and not an explicit memory prompt, but initial intent was 'Previous Conversation Query' or 'Unknown' with cues
            logging.info(
                f"Contextual cues present or intent was 'Previous Conversation Query', but no history to resolve against. Treating as Unknown.")
            detected_intent = "Unknown"  # Force to Unknown if no history for contextual resolution

    logging.info(f"Proceeding with final intent: '{detected_intent}' for query: '{user_input}'")

    # 4. Final Processing Based on (Potentially Refined) Intent
    if detected_intent == "Unknown":
        logging.info(f"Handling as: Unknown (Final Decision)")
        yield f"I'm here to answer questions about Bravur and IT services in {language_name}. How can I help with those topics?"
        return

    # --- Main Response Generation Logic (IT Trends or Company Info/RAG) ---
    recent_convo_for_response = get_recent_conversation(session_id)

    if detected_intent == "IT Trends":
        logging.info(f"Handling as: IT Trends (Final Decision)")
        sys_prompt_content = f"You are a knowledgeable AI assistant. Provide concise insights on IT services and general technology trends. Respond in {language_name}."
        messages_for_llm = [{"role": "system", "content": sys_prompt_content}] + recent_convo_for_response + [
            {"role": "user", "content": user_input}]
        response_model = "llama-3.3-70b-versatile"  # Groq fast model
        try:
            stream = groq_client.chat.completions.create(
                model=response_model, messages=messages_for_llm, max_tokens=1500, temperature=0.7, stream=True
            )
            full_response_chunk = ""
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    delta = chunk.choices[0].delta.content;
                    full_response_chunk += delta;
                    yield delta
            logging.info(f"IT Trends LLM Full Response: {full_response_chunk[:300]}...")
        except Exception as e:
            logging.error(f"Groq streaming error for IT Trends: {e}")
            yield "\n[Error generating IT trends response]"
        return

    # Default to Company Info / RAG Path
    if detected_intent == "Company Info" or detected_intent == "Previous Conversation Query":
        logging.info(f"HANDLING: RAG Path for Intent='{detected_intent}'")

        # Embed user query (using OpenAI as per database.py's embed_query function)
        query_embedding_vector = embed_query(user_input)
        search_results = []

        if query_embedding_vector:
            # hybrid_search should query your 'bravur_data' table
            # and return results like [(entry_id, title, content, similarity_score), ...]
            search_results = hybrid_search(user_input, top_k=3)
            logging.info(f"RAG: Hybrid search against 'bravur_data' found {len(search_results)} results.")
        else:
            logging.warning("RAG: Could not generate query embedding for RAG search.")

        # If RAG finds no documents for a query that was classified (initially or refined)
        # as "Company Info", then give a specific message.
        # For "Previous Conversation Query", we might still want to proceed with just history.
        if not search_results and detected_intent == "Company Info":
            logging.info(f"RAG: No DB results for Company Info query: '{user_input}'")
            yield f"I couldn't find specific information about '{user_input}' in Bravur's knowledge base. Can I help with another Bravur topic?"
            return

        # --- CONSTRUCT SEMANTIC CONTEXT WITH CLEAR "Row ID" ---
        semantic_context_parts = []
        if search_results:
            for item in search_results:
                # Assuming hybrid_search returns at least (entry_id, title, content, ...)
                # Your screenshot shows `bravur_data` has `entry_id`, `title`, `content`.
                entry_id = item[0]
                title = item[1] if len(item) > 1 and item[1] else "N/A"  # Handle if title is None or not returned
                content_chunk = item[2] if len(item) > 2 else ""  # Handle if content is not returned

                # Format for the LLM, explicitly using "Row ID"
                semantic_context_parts.append(f"Row ID: {entry_id}\nTitle: {title}\nContent: {content_chunk}")

            semantic_context_str = "\n\n---\n\n".join(semantic_context_parts)
            logging.debug(f"RAG: Semantic Context for LLM (first 300 chars): {semantic_context_str[:300]}...")
        else:
            semantic_context_str = "No specific Bravur documents were found to be highly relevant for this query."
            logging.info(
                "RAG: No specific documents found from search. Will rely on conversation history if applicable.")

        # --- REFINED RAG SYSTEM PROMPT ---
        rag_system_prompt_content = (
            f"You are a helpful AI assistant for Bravur, an IT consultancy. Respond in {language_name}. "
            f"Your primary goal is to answer the user's query based on the 'Conversation History' and the 'Provided Context From Bravur Database' below. "
            f"When you use information from the 'Provided Context From Bravur Database' to formulate your answer, you MUST CITE THE 'Row ID' for each piece of information used, like this: (Row ID: [ID]). "
            f"If multiple pieces of context are used, cite all relevant Row IDs. "
            f"If the 'Provided Context From Bravur Database' is 'No specific Bravur documents...' or does not contain the answer, rely on the 'Conversation History' if it's relevant. "
            f"If the answer cannot be found in either the history or the 'Provided Context From Bravur Database', clearly state that you don't have that specific detail from Bravur's knowledge base. "
            f"Do not use any external knowledge. Be conversational and helpful.\n\n"
            f"Provided Context From Bravur Database:\n{semantic_context_str}"
        )

        messages_for_llm = [{"role": "system", "content": rag_system_prompt_content}] + recent_convo_for_response + [
            {"role": "user", "content": user_input}]

        final_rag_model = "gpt-4o-mini"  # Using OpenAI as requested for final RAG response
        logging.info(f"RAG: Generating response with OpenAI model {final_rag_model}")

        try:
            # Ensure you are using the correct OpenAI client instance
            # Your global `openai_client_for_embeddings` is initialized. Let's use that,
            # or ensure `client` at the top of the file is the OpenAI client if that's intended.
            # Based on your current setup, `openai_client_for_embeddings` is the correct one.
            stream = openai_client_for_embeddings.chat.completions.create(
                model=final_rag_model,
                messages=messages_for_llm,
                max_tokens=1500,
                temperature=0.5,  # Slightly lower temp for more factual RAG
                stream=True
            )

            full_response_chunk = ""
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    delta = chunk.choices[0].delta.content
                    full_response_chunk += delta
                    yield delta
            logging.info(f"RESPONSE (RAG - {final_rag_model}): '{full_response_chunk[:300]}...'")
        except Exception as e:
            logging.error(f"LLM Error (RAG with {final_rag_model}): {e}")
            yield "[Error generating RAG response]"
        return

    # Final safety fallback
    logging.warning(f"Fell through all intent handling for intent '{detected_intent}'. Query: '{user_input}'")
    yield f"I'm a bit unsure how to help with that. I can discuss Bravur or general IT topics in {language_name}."


if 'agent_connector' not in globals():  # Simple check if it's already defined (e.g. if imported)
    agent_connector = AgentConnector()  # Should be defined only once
agent_connector.register_agent("Bravur_Information_Agent", company_info_handler_streaming)