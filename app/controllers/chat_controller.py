from flask import request, jsonify, Response, stream_with_context
import logging
from app.chatbot import company_info_handler_streaming
from app.chatbot_documents import document_rag_handler_streaming
from app.database import create_chat_session, store_message
from app.database import is_session_active


def handle_chat():
    if request.content_type and 'application/json' in request.content_type:
        data = request.get_json()
        user_input = data.get("message") or data.get("user_input")
        session_id = data.get("session_id")
        language = data.get("language", "en-US")
    else:
        user_input = request.form.get("user_input")
        session_id = request.form.get("session_id")
        language = request.form.get("language", "en-US")

    if not user_input:
        return jsonify({"error": "User input is required"}), 400

    if session_id in ["None", "null", None]:
        session_id = create_chat_session()
        if not session_id:
            return jsonify({"error": "Failed to create session"}), 500

    try:
        session_id = int(session_id)
    except:
        session_id = create_chat_session()

    if not is_session_active(session_id):
        return jsonify({
            "error": "Session expired",
            "new_session_required": True
        }), 403

    store_message(session_id, user_input, "user")

    if request.content_type and 'application/json' in request.content_type:
        return handle_wordpress_chat(user_input, session_id, language)
    else:
        return handle_streaming_chat(user_input, session_id, language)

def handle_wordpress_chat(user_input, session_id, language):
    try:
        full_reply = ""
        for chunk in document_rag_handler_streaming(user_input, session_id, language):
            full_reply += chunk
        if full_reply.strip():
            store_message(session_id, full_reply.strip(), "bot")
        return jsonify({
            "response": full_reply.strip(),
            "session_id": session_id,
            "language": language,
            "status": "success"
        })
    except Exception as e:
        logging.error(f"Error in WordPress chat: {e}")
        return jsonify({"error": "Internal server error"}), 500

def handle_streaming_chat(user_input, session_id, language):
    def generate():
        full_reply = ""
        try:
            for chunk in document_rag_handler_streaming(user_input, session_id, language):
                full_reply += chunk
                yield chunk
        finally:
            if full_reply.strip():
                store_message(session_id, full_reply.strip(), "bot")
    return Response(stream_with_context(generate()), mimetype="text/plain")