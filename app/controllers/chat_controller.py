# app/controllers/chat_controller.py

from flask import request, jsonify, Response, stream_with_context
import logging
from app.chatbot import company_info_handler_streaming
from app.database import create_chat_session, store_message
from app.rate_limiter import check_session_rate_limit

from app.database import is_session_active

from app.database import create_chat_session, store_message, is_session_active
from app.rate_limiter import check_session_rate_limit, get_session_rate_status, r as redis_client  # Updated import

def handle_chat():
    """
    Handle chat requests from both existing frontend (form data)
    and WordPress (form data via AJAX proxy)
    """

    print(f"=== CHAT REQUEST DEBUG ===")
    print(f"Content-Type: {request.content_type}")
    print(f"Method: {request.method}")
    print(f"Form data: {dict(request.form)}")
    try:
        print(f"JSON data: {request.get_json(silent=True)}")
    except Exception as e:
        print(f"JSON parse error: {e}")
    print(f"Headers: {dict(request.headers)}")

    if request.content_type and 'application/json' in request.content_type:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        user_input = data.get("message") or data.get("user_input")
        session_id = data.get("session_id")
        language = data.get("language", "nl-NL")
        request_type = "json"
    else:
        user_input = request.form.get("user_input")
        session_id = request.form.get("session_id")
        language = request.form.get("language", "nl-NL")
        user_agent = request.headers.get('User-Agent', '')
        referrer = request.headers.get('Referer', '')
        request_type = "wordpress" if 'WordPress' in user_agent or 'bravurwp.local' in referrer else "form"

    if not user_input:
        error_response = "Message is required" if request_type == "wordpress" else "User input is required"
        return jsonify({"error": error_response}), 400

    if session_id == "None" or not session_id or session_id == "null":
        session_id = create_chat_session()
        if not session_id:
            error_msg = "Sorry, I'm having trouble with your session. Please try again."
            return jsonify({"error": error_msg}), 500

    try:
        session_id = int(session_id)
    except (ValueError, TypeError):
        session_id = create_chat_session()
        if not session_id:
            return jsonify({"error": "Sorry, I'm having trouble with your session. Please try again."}), 500

    # Properly positioned after successful conversion
    if not is_session_active(session_id):
        error_msg = "This session is no longer active. Please start a new conversation."
        logging.warning(f"Attempted to use inactive session: {session_id}")
        return jsonify({
            "error": error_msg,
            "session_expired": True,
            "new_session_required": True
        }), 403

    # Apply session-based rate limit with CAPTCHA logic
    allowed_session, session_retry_after, captcha_required = check_session_rate_limit(session_id)

    # Use the existing Redis connection for logging
    try:
        count = redis_client.get(f"rate_limit:session:{session_id}") or 0
        print(f"🔢 Session {session_id} has made {count} requests so far.")
    except Exception as e:
        print(f"⚠️ Failed to fetch rate count from Redis: {e}")

    if not allowed_session:
        return jsonify({
            "error": f"Too many requests for this session. Please try again in {session_retry_after} seconds."
        }), 429, {'Retry-After': str(session_retry_after)}

    if captcha_required:
        status = get_session_rate_status(session_id)
        return jsonify({
            "error": "CAPTCHA required before continuing",
            "captcha_required": True,
            "count": status['count'],
            "limit": status['limit']
        }), 403

    MAX_INPUT_CHARS = 1000
    if len(user_input) > MAX_INPUT_CHARS:
        logging.warning(f"User input too long for session {session_id}.")
        return jsonify({
            "error": f"Your message is too long. Please keep it under {MAX_INPUT_CHARS} characters."
        }), 400

    store_message(session_id, user_input, "user")

    if request_type in ["wordpress", "json"]:
        return handle_wordpress_chat(user_input, session_id, language)

    return handle_streaming_chat(user_input, session_id, language)


def handle_wordpress_chat(user_input, session_id, language):
    """
    Handle WordPress chat requests with complete JSON response
    """
    try:
        print(f"Processing WordPress chat for session {session_id}")
        full_reply = ""
        for chunk in company_info_handler_streaming(user_input, session_id, language):
            full_reply += chunk
        if full_reply.strip():
            store_message(session_id, full_reply.strip(), "bot")
        print(f"WordPress chat response: {full_reply[:100]}...")
        return jsonify({
            "response": full_reply.strip() or "Sorry, I couldn't generate a response.",
            "session_id": session_id,
            "language": language,
            "status": "success"
        })
    except Exception as e:
        logging.error(f"Error in WordPress chat: {e}")
        print(f"WordPress chat error: {e}")
        return jsonify({"error": "Internal server error"}), 500


def handle_streaming_chat(user_input, session_id, language):
    """
    Handle existing frontend streaming chat requests
    """
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