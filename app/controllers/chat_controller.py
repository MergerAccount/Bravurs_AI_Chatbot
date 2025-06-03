from flask import request, jsonify, Response, stream_with_context
import logging
from app.chatbot import company_info_handler_streaming
from app.database import create_chat_session, store_message


def handle_chat():
    """
    Handle chat requests from both existing frontend (form data)
    and WordPress (form data via AJAX proxy)
    """

    # Debug logging
    print(f"=== CHAT REQUEST DEBUG ===")
    print(f"Content-Type: {request.content_type}")
    print(f"Method: {request.method}")
    print(f"Form data: {dict(request.form)}")
    print(f"JSON data: {request.get_json()}")
    print(f"Headers: {dict(request.headers)}")

    # Determine request type and extract data accordingly
    if request.content_type and 'application/json' in request.content_type:
        # Direct JSON request (rare)
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        user_input = data.get("message") or data.get("user_input")
        session_id = data.get("session_id")
        language = data.get("language", "nl-NL")
        request_type = "json"
    else:
        # Form data request (both existing frontend and WordPress)
        user_input = request.form.get("user_input")
        session_id = request.form.get("session_id")
        language = request.form.get("language", "nl-NL")

        # Check if this is from WordPress AJAX proxy
        user_agent = request.headers.get('User-Agent', '')
        referrer = request.headers.get('Referer', '')

        # WordPress requests will have WordPress in user agent or come from WordPress site
        if 'WordPress' in user_agent or 'bravurwp.local' in referrer:
            request_type = "wordpress"
        else:
            request_type = "form"

    print(f"Detected request type: {request_type}")
    print(f"User input: {user_input}")
    print(f"Session ID: {session_id}")
    print(f"Language: {language}")

    if not user_input:
        error_response = "Message is required" if request_type == "wordpress" else "User input is required"
        if request_type in ["wordpress", "json"]:
            return jsonify({"error": error_response}), 400
        else:
            return jsonify({"response": error_response, "session_id": None})

    # Create session if none provided
    if session_id == "None" or not session_id:
        session_id = create_chat_session()
        if not session_id:
            error_msg = "Sorry, I'm having trouble with your session. Please try again."
            if request_type in ["wordpress", "json"]:
                return jsonify({"error": error_msg}), 500
            else:
                return jsonify({"response": error_msg, "session_id": None})

    # Convert session_id to integer
    try:
        session_id = int(session_id)
    except (ValueError, TypeError):
        session_id = create_chat_session()
        if not session_id:
            error_msg = "Sorry, I'm having trouble with your session. Please try again."
            if request_type in ["wordpress", "json"]:
                return jsonify({"error": error_msg}), 500
            else:
                return jsonify({"response": error_msg, "session_id": None})

    # Store user message before processing
    store_message(session_id, user_input, "user")

    # Handle WordPress requests (non-streaming JSON response)
    if request_type in ["wordpress", "json"]:
        return handle_wordpress_chat(user_input, session_id, language)

    # Handle existing frontend requests (streaming response)
    return handle_streaming_chat(user_input, session_id, language)


def handle_wordpress_chat(user_input, session_id, language):
    """
    Handle WordPress chat requests with complete JSON response
    (WordPress frontend expects a complete response, not streaming)
    """
    try:
        print(f"Processing WordPress chat for session {session_id}")
        full_reply = ""

        # Collect the complete response from streaming function
        for chunk in company_info_handler_streaming(user_input, session_id, language):
            full_reply += chunk

        # Store the complete response
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