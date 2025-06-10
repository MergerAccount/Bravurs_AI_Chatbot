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

# === API ROUTES under /api/v1 ===
routes = Blueprint("routes", __name__, url_prefix="/api/v1")

@routes.route("/chat", methods=["POST"])
def chat():
    """Modified to handle WordPress requests"""

    user_input = request.json.get("input", "")
    if len(user_input) >= 1000 or len(user_input.split()) >= 150:
        return jsonify({"error": "Input too long. Max 150 words or 1000 characters."}), 400

    return handle_chat()

@routes.route("/feedback", methods=["POST"])
def submit_feedback():
    return handle_feedback_submission()

@routes.route("/history", methods=["GET"])
def get_history():
    return handle_history_fetch()


@routes.route("/session/create", methods=["POST"])
def create_session():
    """Create a new chat session for WordPress frontend"""
    try:
        session_id = create_chat_session()

        if session_id:
            response_data = {
                "success": True,
                "session_id": session_id,
                "message": "Session created successfully"
            }
            print(f"DEBUG: Returning response: {response_data}")
            return jsonify(response_data), 200
        else:
            print("DEBUG: Failed to create session")
            return jsonify({
                "success": False,
                "error": "Failed to create session"
            }), 500

    except Exception as e:
        print(f"DEBUG: Exception in session creation: {e}")
        import logging
        logging.error(f"Error in session creation endpoint: {e}")
        return jsonify({
            "success": False,
            "error": "Internal server error"
        }), 500

# === CONSENT ROUTES ===
@routes.route('/consent/accept', methods=['POST'])
def accept_consent():
    """Handle consent acceptance from WordPress"""
    return handle_accept_consent()

@routes.route('/consent/withdraw', methods=['POST'])
def withdraw_consent():
    """Handle consent withdrawal from WordPress"""
    return handle_withdraw_consent()

@routes.route('/consent/check/<session_id>', methods=['GET'])
def check_consent(session_id):
    """Check consent status for a session"""
    result = check_consent_status(session_id)
    return jsonify(result)

# === LANGUAGE ROUTE ===
@routes.route("/language_change", methods=["POST"])
def language_change():
    """Handle language change from WordPress frontend"""
    session_id = request.form.get("session_id")
    language = request.form.get("language")
    from_language = request.form.get("from_language")
    to_language = request.form.get("to_language")

    if session_id:
        # Store a system message indicating language change
        language_message = f"[SYSTEM] Language changed from {from_language} to {to_language}. All responses should now be in {'Dutch' if to_language == 'nl-NL' else 'English'}."
        store_message(session_id, language_message, "system")
        return jsonify({"status": "success"})

    return jsonify({"status": "error", "message": "No session ID provided"}), 400

# === SPEECH ROUTES ===
@routes.route("/tts", methods=["POST"])
def text_to_speech_api():
    """Text-to-speech endpoint"""
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
    """Speech-to-text endpoint for WordPress voice input"""
    from app.speech import speech_to_text

    data = request.get_json() or {}
    language = data.get("language")

    result = speech_to_text(language)
    return jsonify(result)

@routes.route("/sts", methods=["POST"])
def handle_speech_to_speech():
    """Speech-to-speech endpoint"""
    try:
        # Get language and session ID from form data
        language = request.form.get('language')
        session_id = request.form.get('session_id')

        print(f"Received STS request with language: {language}, session_id: {session_id}")

        # Use the updated speech_to_speech function with both parameters
        result = speech_to_speech(language=language, session_id=session_id)

        if not result:
            print("No valid speech input detected or processing failed")
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
        print(f"Error in speech-to-speech: {str(e)}")
        return jsonify({"error": str(e)}), 500

# === HEALTH CHECK ===
@routes.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "service": "Bravur Chatbot API"})

# === CORS HEADERS FOR WORDPRESS ===
@routes.after_request
def after_request(response):
    """Add CORS headers for WordPress integration"""
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# === FRONTEND ROUTES (Keep for testing) ===
frontend = Blueprint("frontend", __name__)

@frontend.route("/", methods=["GET"])
def serve_home():
    """Keep this for direct testing of your Python app"""
    session_id = create_chat_session()
    return render_template("index.html", session_id=session_id)
