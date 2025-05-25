import os
from flask import Blueprint, request, send_file, after_this_request, jsonify, Response, stream_with_context, render_template
from app.controllers.chat_controller import handle_chat
from app.controllers.feedback_controller import handle_feedback_submission
from app.controllers.history_controller import handle_history_fetch
from app.database import create_chat_session, store_message
from flask import Blueprint, request, jsonify, render_template, session
from app.controllers.consent_controller import handle_accept_consent, handle_withdraw_consent, check_consent_status
from app.speech import speech_to_speech, save_audio_file
import base64
from flask import Flask, Blueprint, request, send_file, after_this_request, jsonify, Response, stream_with_context, render_template


# === API ROUTES under /api/v1 ===
routes = Blueprint("routes", __name__, url_prefix="/api/v1")

@routes.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response


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
    language = request.json.get("language") if request.is_json else None
    result = speech_to_speech(language=language)  # no audio_file, mic only
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


frontend = Blueprint("frontend", __name__)

@frontend.route("/", methods=["GET"])
def serve_home():
    session_id = create_chat_session()
    return render_template("index.html", session_id=session_id)

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


@routes.route("/language_change", methods=["POST"])
def language_change():
    session_id = request.form.get("session_id")
    from_language = request.form.get("from_language")
    to_language = request.form.get("to_language")

    if session_id:
        # Store a system message indicating language change
        language_message = f"[SYSTEM] Language changed from {from_language} to {to_language}. All responses should now be in {'Dutch' if to_language == 'nl-NL' else 'English'}."
        store_message(session_id, language_message, "system")
        return jsonify({"status": "success"})

    return jsonify({"status": "error", "message": "No session ID provided"}), 400