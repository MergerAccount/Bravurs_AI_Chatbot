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
from app.utils import get_client_ip

# API ROUTES under /api/v1
routes = Blueprint("routes", __name__, url_prefix="/api/v1")

@routes.route("/chat", methods=["POST"])
def chat():
    """Handle chat requests with input validation"""
    if request.content_type and 'application/json' in request.content_type:
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
    user_ip = get_client_ip() # get the user's IP address
    # print IP to console for verification - can remove later
    print(f"API Session Creation - User IP: {user_ip}")
    session_id = create_chat_session()
    if session_id:
        return jsonify({"session_id": session_id})
    return jsonify({"error": "Failed to create session"}), 500
    """Create a new chat session for WordPress frontend"""
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
    language = request.form.get("language")
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


# @routes.route("/stt", methods=["POST"])
# def speech_to_text_api():
#     """Speech-to-text endpoint for WordPress voice input"""
#     import tempfile
#     import os
#
#     try:
#         # Debug logging
#         print(f"STT request received")
#         print(f"Content-Type: {request.content_type}")
#         print(f"Form data: {dict(request.form)}")
#         print(f"Files: {list(request.files.keys())}")
#
#         # Get language from form data
#         language = request.form.get('language', 'nl-NL')
#         session_id = request.form.get('session_id')
#
#         print(f"STT - Language: {language}, Session ID: {session_id}")
#
#         # Check if we have an audio file
#         if 'audio' not in request.files:
#             print("No audio file in request")
#             return jsonify({
#                 "status": "error",
#                 "message": "No audio file provided"
#             }), 400
#
#         audio_file = request.files['audio']
#         if audio_file.filename == '':
#             print("Empty audio filename")
#             return jsonify({
#                 "status": "error",
#                 "message": "No audio file selected"
#             }), 400
#
#         print(f"Audio file received: {audio_file.filename}")
#
#         # Save the uploaded audio file temporarily
#         # Azure Speech SDK supports various formats, but let's try to keep original format
#         file_extension = '.webm'  # Default, but try to detect from filename
#         if '.' in audio_file.filename:
#             file_extension = '.' + audio_file.filename.rsplit('.', 1)[1].lower()
#
#         with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
#             audio_file.save(temp_file.name)
#             temp_audio_path = temp_file.name
#
#         print(f"Audio saved to: {temp_audio_path}")
#
#         # Import the speech_to_text function
#         from app.speech import speech_to_text
#
#         # Call speech_to_text with the audio file path
#         result = speech_to_text(language=language, audio_file_path=temp_audio_path)
#
#         print(f"STT result: {result}")
#
#         # Clean up temporary file
#         try:
#             os.remove(temp_audio_path)
#             print(f"Cleaned up temp file: {temp_audio_path}")
#         except Exception as e:
#             print(f"Error removing temp file: {e}")
#
#         # Return the result in the format WordPress expects
#         if result and result.get("status") == "success" and result.get("text"):
#             return jsonify({
#                 "status": "success",
#                 "text": result["text"],
#                 "language": result.get("language", language),
#                 "message": "Speech recognized successfully"
#             })
#         else:
#             error_message = result.get("message",
#                                        "Speech recognition failed") if result else "Speech recognition failed"
#             return jsonify({
#                 "status": "error",
#                 "message": error_message
#             }), 400
#
#     except Exception as e:
#         print(f"Error in STT endpoint: {str(e)}")
#         import traceback
#         traceback.print_exc()
#         return jsonify({
#             "status": "error",
#             "message": f"Internal server error: {str(e)}"
#         }), 500

@routes.route("/sts", methods=["POST"])
def handle_speech_to_speech():
    """Speech-to-speech endpoint"""
    try:
        # get language and session ID from form data
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

# === FRONTEND TESTING ROUTE ===
frontend = Blueprint("frontend", __name__)

@frontend.route("/", methods=["GET"])
def serve_home():
    user_ip = get_client_ip() # get the user's IP address
    # print IP to console for verification
    print(f"Frontend Home Page - User IP: {user_ip}")
    session_id = create_chat_session() # Removed user_ip from here
    """Keep this for direct testing of your Python app"""
    session_id = create_chat_session()
    return render_template("index.html", session_id=session_id)