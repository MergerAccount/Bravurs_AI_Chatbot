from flask import Blueprint, request, jsonify, Response, stream_with_context, render_template
from app.controllers.chat_controller import handle_chat
from app.controllers.feedback_controller import handle_feedback_submission
from app.controllers.history_controller import handle_history_fetch
from app.database import create_chat_session
from flask import Blueprint, request, jsonify, render_template, session
from app.controllers.consent_controller import handle_accept_consent, handle_withdraw_consent, check_consent_status


# === API ROUTES under /api/v1 ===
routes = Blueprint("routes", __name__, url_prefix="/api/v1")

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

    if not text:
        return jsonify({"error": "No text provided"}), 400

    audio_path = text_to_speech(text)
    if not audio_path:
        return jsonify({"error": "TTS failed"}), 500

    def generate():
        with open(audio_path, "rb") as f:
            yield from f

    return Response(generate(), mimetype="audio/wav")


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
