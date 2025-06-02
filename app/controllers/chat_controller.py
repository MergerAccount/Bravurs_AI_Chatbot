from flask import request, jsonify, Response, stream_with_context
import logging
from app.chatbot import company_info_handler_streaming
from app.database import create_chat_session, store_message
from app.rate_limiter import check_session_rate_limit


# Handle user chat POST request and stream GPT response
def handle_chat():
    user_input = request.form["user_input"]
    session_id = request.form.get("session_id")
    language = request.form.get("language", "nl-NL")

    # Create session if none provided
    if session_id == "None" or not session_id:
        session_id = create_chat_session()
        if not session_id:
            return jsonify({
                "response": "Sorry, I'm having trouble with your session. Please try again.",
                "session_id": None
            })

    # Convert session_id to integer
    try:
        session_id = int(session_id)
    except (ValueError, TypeError):
        session_id = create_chat_session()
        if not session_id:
            return jsonify({
                "response": "Sorry, I'm having trouble with your session. Please try again.",
                "session_id": None
            })

    # Apply session-based rate limit
    allowed_session, session_retry_after = check_session_rate_limit(session_id)
    if not allowed_session:
        return jsonify({"error": f"Too many requests for this session. Please try again in {session_retry_after} seconds."}), 429, {'Retry-After': str(session_retry_after)}

    #  validate input (message Length)
    MAX_INPUT_CHARS = 1000 # Example: Limit user input to 1000 characters
    if len(user_input) > MAX_INPUT_CHARS:
        logging.warning(f"User input too long for session {session_id}.")
        return jsonify({"error": f"Your message is too long. Please keep it under {MAX_INPUT_CHARS} characters."}), 400

    # Store user message before processing
    store_message(session_id, user_input, "user")

    # Stream GPT reply and capture for DB
    def generate():
        full_reply = ""
        try:
            for chunk in company_info_handler_streaming(user_input, session_id, language):
                full_reply += chunk
                yield chunk
        finally:
            if full_reply.strip():
                store_message(session_id, full_reply.strip(), "bot")

    return Response(stream_with_context(generate()), mimetype="text/plain")