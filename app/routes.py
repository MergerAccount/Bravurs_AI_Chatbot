# Add these updates to your existing routes.py file

import os
from flask import Blueprint, request, send_file, after_this_request, jsonify, Response, stream_with_context, \
    render_template
from app.controllers.chat_controller import handle_chat
from app.controllers.feedback_controller import handle_feedback_submission
from app.controllers.history_controller import handle_history_fetch
from app.database import create_chat_session, store_message, get_session_messages
from flask import Blueprint, request, jsonify, render_template, session
from app.controllers.consent_controller import handle_accept_consent, handle_withdraw_consent, check_consent_status
from app.speech import speech_to_speech, save_audio_file, validate_session_continuity, update_session_voice_usage
import base64
import uuid

# === API ROUTES under /api/v1 ===
routes = Blueprint("routes", __name__, url_prefix="/api/v1")


@routes.route("/chat", methods=["POST"])
def chat():
    """Modified to handle WordPress requests with session_id and language"""
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
    
    session_id = create_chat_session()
    if session_id:
        print(f"Created new session via /session/create: {session_id}")
        return jsonify({"session_id": session_id, "status": "success"})
    return jsonify({"error": "Failed to create session", "status": "error"}), 500


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
    """
    Handle speech-to-speech requests with proper session management
    """
    try:
        # Get language and session ID from form data
        language = request.form.get('language')
        session_id = request.form.get('session_id')

        # Validate session_id - DO NOT create new session here!
        if not session_id or session_id in ['null', 'undefined', '']:
            return jsonify({
                "error": "Session ID is required",
                "message": "Please create a session first using /session/create",
                "status": "error"
            }), 400

        # Validate that the session exists in the database
        session_validation = validate_session_continuity(session_id)
        if not session_validation["valid"]:
             return jsonify({
                "error": "Invalid session ID",
                "message": session_validation["message"],
                "status": "error"
            }), 400

        # Mark this session as using voice features
        update_session_voice_usage(session_id)

        # Call speech_to_speech with the validated session_id
        result = speech_to_speech(language=language, session_id=session_id)

        if not result:
            print("No valid speech input detected or processing failed")
            return jsonify({
                "error": "Speech processing failed", 
                "message": "No speech detected. Please try again.",
                "session_id": session_id,
                "status": "error"
            }), 400


        with open(result["audio_path"], "rb") as f:
            audio_base64 = base64.b64encode(f.read()).decode("utf-8")

        # Clean up temporary audio file
        try:
            os.remove(result["audio_path"])
        except Exception as e:
            print(f"Warning: Error removing temp file: {e}")

        # Return successful response
        return jsonify({
            "user_text": result["original_text"],
            "bot_text": result["response_text"],
            "audio_base64": audio_base64,
            "session_id": session_id,  # Return the same session_id
            "language": result["language"],
            "is_first_interaction": result.get("is_first_interaction", False),
            "status": "success"
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": f"Internal server error: {str(e)}",
            "status": "error"
        }), 500


@routes.route('/session/new', methods=['POST'])
def new_session():
    """
    Create a new session and return the session ID
    This should be called when the page loads or when user wants to start fresh
    """
    try:
        # Create a proper database session
        session_id = create_chat_session()

        if not session_id:
            return jsonify({
                "error": "Failed to create session",
                "status": "error"
            }), 500

        return jsonify({
            "status": "success",
            "session_id": session_id,
            "message": "New session created successfully"
        })

    except Exception as e:
        return jsonify({
            "error": f"Failed to create session: {str(e)}",
            "status": "error"
        }), 500


@routes.route('/session/validate', methods=['POST'])
def validate_session():
    """
    Validate if a session ID exists and is valid
    """
    try:
        data = request.get_json() or {}
        session_id = data.get('session_id')

        if not session_id:
            return jsonify({
                "valid": False,
                "message": "No session ID provided",
                "status": "error"
            }), 400

        validation_result = validate_session_continuity(session_id)

        return jsonify({
            "valid": validation_result["valid"],
            "message": validation_result.get("message", ""),
            "session_info": {
                "message_count": validation_result.get("message_count", 0),
                "has_bot_messages": validation_result.get("has_bot_messages", False)
            } if validation_result["valid"] else None,
            "status": "success"
        })

    except Exception as e:
        return jsonify({
            "valid": False,
            "message": f"Validation error: {str(e)}",
            "status": "error"
        }), 500


@routes.route('/session/end', methods=['POST'])
def end_session():
    """
    Optional: endpoint to explicitly end a session
    With database-based sessions, this is mainly for cleanup/logging
    """
    try:
        data = request.get_json() or {}
        session_id = data.get('session_id')

        if session_id:
            # Could add session cleanup logic here if needed
            return jsonify({
                "status": "success",
                "message": f"Session {session_id} ended"
            })

        return jsonify({
            "status": "error",
            "message": "No session ID provided"
        }), 400

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Error ending session: {str(e)}"
        }), 500

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
  
    try:
        session_id = create_chat_session()
        return render_template("index.html", session_id=session_id)
    except Exception as e:
        return render_template("index.html", session_id=None)


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
    try:
        session_id = request.form.get("session_id")
        language = request.form.get("language")
        from_language = request.form.get("from_language")
        to_language = request.form.get("to_language")

        if not session_id:
            return jsonify({
                "status": "error",
                "message": "No session ID provided"
            }), 400

        # Validate session exists
        validation = validate_session_continuity(session_id)
        if not validation["valid"]:
            return jsonify({
                "status": "error",
                "message": f"Invalid session: {validation['message']}"
            }), 400

        # Store a system message indicating language change
        language_message = f"[SYSTEM] Language changed from {from_language} to {to_language}. All responses should now be in {'Dutch' if to_language == 'nl-NL' else 'English'}."

        message_stored = store_message(session_id, language_message, "system")

        if message_stored:
            return jsonify({
                "status": "success",
                "message": f"Language changed to {to_language}"
            })
        else:
            return jsonify({
                "status": "error",
                "message": "Failed to record language change"
            }), 500

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Error changing language: {str(e)}"
        }), 500
