import os
import base64
from flask import (
    Blueprint, request, jsonify, Response,
    stream_with_context, render_template, send_file, after_this_request, session
)
from app.controllers.chat_controller import handle_chat
from app.controllers.feedback_controller import handle_feedback_submission
from app.controllers.history_controller import handle_history_fetch
from app.controllers.consent_controller import handle_accept_consent, handle_withdraw_consent, check_consent_status
from app.speech import speech_to_speech, save_audio_file
from app.database import create_chat_session, store_message
from app.rate_limiter import (
    check_session_rate_limit, check_ip_rate_limit,
    get_session_rate_status, mark_captcha_solved,
    get_fingerprint_rate_status, mark_captcha_solved_fingerprint
)

routes = Blueprint("routes", __name__, url_prefix="/api/v1")

def get_client_ip():
    x_forwarded_for = request.headers.get('X-Forwarded-For')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.remote_addr

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
    try:
        session_id = create_chat_session()
        if session_id:
            return jsonify({
                "success": True,
                "session_id": session_id,
                "message": "Session created successfully"
            }), 200
        return jsonify({
            "success": False,
            "error": "Failed to create session"
        }), 500
    except Exception as e:
        import logging
        logging.error(f"Error in session creation endpoint: {e}")
        return jsonify({
            "success": False,
            "error": "Internal server error"
        }), 500

# === CONSENT ROUTES ===
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

# === CAPTCHA RATE LIMIT ROUTES ===
@routes.route("/ratelimit/check", methods=["POST"])
def ratelimit_check():
    # Accept fingerprint or session_id in JSON or form
    fingerprint = None
    session_id = None
    if request.content_type and 'application/json' in request.content_type:
        data = request.get_json()
        fingerprint = data.get("fingerprint")
        session_id = data.get("session_id")
    else:
        fingerprint = request.form.get("fingerprint")
        session_id = request.form.get("session_id")
    if not fingerprint:
        fingerprint = request.headers.get("X-Client-Fingerprint")
    try:
        if fingerprint:
            data = get_fingerprint_rate_status(fingerprint)
        elif session_id:
            data = get_session_rate_status(session_id)
        else:
            return jsonify(success=False, error="Missing fingerprint or session_id"), 400
        return jsonify(data)
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500

@routes.route("/ratelimit/captcha-solved", methods=["POST"])
def captcha_solved():
    fingerprint = None
    session_id = None
    if request.content_type and 'application/json' in request.content_type:
        data = request.get_json()
        fingerprint = data.get("fingerprint")
        session_id = data.get("session_id")
    else:
        fingerprint = request.form.get("fingerprint")
        session_id = request.form.get("session_id")
    if not fingerprint:
        fingerprint = request.headers.get("X-Client-Fingerprint")
    try:
        if fingerprint:
            new_limit = mark_captcha_solved_fingerprint(fingerprint)
        elif session_id:
            new_limit = mark_captcha_solved(session_id)
        else:
            return jsonify(success=False, error="Missing fingerprint or session_id"), 400
        return jsonify(success=True, new_limit=new_limit)
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500

# === LANGUAGE ROUTE ===
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

# === SPEECH ROUTES ===
@routes.route("/tts", methods=["POST"])
def text_to_speech_api():
    from app.speech import text_to_speech
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
    from app.speech import speech_to_text
    data = request.get_json() or {}
    language = data.get("language")
    result = speech_to_text(language)
    return jsonify(result)

@routes.route("/sts", methods=["POST"])
def handle_speech_to_speech():
    try:
        language = request.form.get('language')
        session_id = request.form.get('session_id')
        result = speech_to_speech(language=language, session_id=session_id)
        if not result:
            return jsonify({
                "error": "Speech processing failed",
                "message": "No speech detected. Please try again."
            }), 400
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
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# === HEALTH CHECK ===
@routes.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "service": "Bravur Chatbot API"})

# === CORS HEADERS FOR WORDPRESS ===
@routes.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# === FRONTEND TESTING ROUTE ===
frontend = Blueprint("frontend", __name__)

@frontend.route("/", methods=["GET"])
def serve_home():
    user_ip = get_client_ip()
    print(f"Frontend Home Page - User IP: {user_ip}")
    session_id = create_chat_session()
    return render_template("index.html", session_id=session_id)
