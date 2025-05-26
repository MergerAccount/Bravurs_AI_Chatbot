import os
from flask import Blueprint, request, send_file, jsonify, Response, render_template
from app.controllers.chat_controller import handle_chat
from app.controllers.feedback_controller import handle_feedback_submission
from app.controllers.history_controller import handle_history_fetch
from app.database import create_chat_session, store_message
from app.controllers.consent_controller import handle_accept_consent, handle_withdraw_consent, check_consent_status
from app.speech import speech_to_speech, text_to_speech, speech_to_text
import base64

# Initialize Blueprint once
routes = Blueprint("routes", __name__, url_prefix="/api/v1")

@routes.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# Chat and Feedback Routes
@routes.route("/chat", methods=["POST"])
def chat():
    return handle_chat()

@routes.route("/feedback", methods=["POST"])
def submit_feedback():
    return handle_feedback_submission()

@routes.route("/history", methods=["GET"])
def get_history():
    return handle_history_fetch()

@routes.route("/session/create", methods=["POST"])
def create_session():
    session_id = create_chat_session()
    if session_id:
        return jsonify({"session_id": session_id})
    return jsonify({"error": "Failed to create session"}), 500

@routes.route("/tts", methods=["POST"])
def text_to_speech_api():
    data = request.get_json()
    text = data.get("text", "")
    language = data.get("language", "en-US")
    if not text:
        return jsonify({"error": "No text provided"}), 400
    audio_path = text_to_speech(text, language)
    if not audio_path:
        return jsonify({"error": "TTS failed"}), 500
    def generate():
        with open(audio_path, "rb") as f:
            yield from f
    return Response(generate(), mimetype="audio/wav")

@routes.route("/stt", methods=["POST"])
def speech_to_text_api():
    data = request.get_json() or {}
    language = data.get("language")
    result = speech_to_text(language)
    return jsonify(result)

@routes.route("/sts", methods=["POST"])
def handle_speech_to_speech():
    language = request.json.get("language") if request.is_json else None
    result = speech_to_speech(language=language)
    if not result:
        return jsonify({"error": "Speech processing failed"}), 500
    with open(result["audio_path"], "rb") as f:
        audio_base64 = base64.b64encode(f.read()).decode("utf-8")
    try:
        os.remove(result["audio_path"])
    except Exception as e:
        print(f"Error removing temp file: {e}")
    return jsonify({
        "user_text": result["original_text"],
        "bot_text": result["response_text"],
        "audio_base64": audio_base64
    })

# Consent Routes
@routes.route('/consent/accept', methods=['POST'])
def accept_consent():
    return handle_accept_consent()

@routes.route('/consent/withdraw', methods=['POST'])
def withdraw_consent():
    return handle_withdraw_consent()

@routes.route('/consent/check/<session_id>', methods=['GET'])
def check_consent(session_id):
    result = check_consent_status(session_id)
    return jsonify(result)

# Language Change
@routes.route("/language_change", methods=["POST"])
def language_change():
    session_id = request.form.get("session_id")
    from_language = request.form.get("from_language")
    to_language = request.form.get("to_language")
    if session_id:
        language_message = f"[SYSTEM] Language changed from {from_language} to {to_language}. All responses should now be in {'Dutch' if to_language == 'nl-NL' else 'English'}."
        store_message(session_id, language_message, "system")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "No session ID provided"}), 400

##Widget routes##

@routes.route("/widget", methods=["GET"])
def chatbot_widget():
    try:
        session_id = create_chat_session()
        print(f"Rendering template with session_id: {session_id}")
        return render_template("chatbot_widget.html", session_id=session_id)  # Simplified
    except Exception as e:
        print(f"Template error: {str(e)}")
        return f"Error loading widget template: {str(e)}", 500

@routes.route("/widget/css", methods=["GET"])
def chatbot_css():
    """Serve chatbot CSS"""
    try:
        css_path = os.path.join(os.getcwd(), "static", "css", "styles.css")
        return send_file(css_path, mimetype="text/css")
    except Exception as e:
        return f"Error loading CSS: {str(e)}", 500

@routes.route("/widget/js/script", methods=["GET"])
def chatbot_script_js():
    """Serve script.js"""
    try:
        script_path = os.path.join(os.getcwd(), "static", "js", "script.js")
        if os.path.exists(script_path):
            return send_file(script_path, mimetype="application/javascript")
        return "// Error: script.js not found", 404
    except Exception as e:
        return f"// Error loading script.js: {str(e)}", 500

@routes.route("/widget/js/consent", methods=["GET"])
def chatbot_consent_js():
    """Serve consent.js"""
    try:
        consent_path = os.path.join(os.getcwd(), "static", "js", "consent.js")
        if os.path.exists(consent_path):
            return send_file(consent_path, mimetype="application/javascript")
        return "// Error: consent.js not found", 404
    except Exception as e:
        return f"// Error loading consent.js: {str(e)}", 500

# Frontend Route
frontend = Blueprint("frontend", __name__)

@frontend.route("/", methods=["GET"])
def serve_home():
    session_id = create_chat_session()
    return render_template("chatbot_widget.html", session_id=session_id)