import os
import base64
from app.speech import speech_to_text_from_file, save_audio_file
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
    """Create a new chat session for WordPress frontend"""
    try:
        user_ip = get_client_ip()
        print(f"API Session Creation - User IP: {user_ip}")
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
def handle_speech_to_text():
    """Simple speech-to-text endpoint for testing"""
    print("=" * 60)
    print("🎤 STT REQUEST RECEIVED")
    print("=" * 60)
    
    try:
        # Log request details
        print(f"📋 Request Method: {request.method}")
        print(f"📋 Content-Type: {request.content_type}")
        print(f"📋 Content-Length: {request.content_length}")
        print(f"📋 Form Data: {dict(request.form)}")
        print(f"📋 Files: {list(request.files.keys())}")
        
        if 'audio' in request.files:
            file = request.files['audio']
            print(f"📁 Audio File Details:")
            print(f"   - Filename: {file.filename}")
            print(f"   - Content-Type: {file.content_type}")
            
            if file.filename == '':
                print("❌ No file selected")
                return jsonify({"error": "No file selected"}), 400

            language = request.form.get('language', 'nl-NL')
            print(f"🌍 Language: {language}")

            # Save uploaded file temporarily
            import tempfile
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.webm')
            file.save(temp_file.name)
            temp_file.close()

            file_size = os.path.getsize(temp_file.name)
            print(f"💾 File saved: {temp_file.name}")
            print(f"💾 File size: {file_size} bytes")
            
            # Check if file is not empty
            if file_size == 0:
                print("❌ Audio file is empty!")
                os.unlink(temp_file.name)
                return jsonify({
                    "error": "Empty audio file",
                    "message": "The recorded audio file is empty."
                }), 400

            # Process speech-to-text
            print("🔍 Starting STT processing...")
            from app.speech import speech_to_text_from_file_rest
            stt_result = speech_to_text_from_file_rest(temp_file.name, language=language)
            print(f"📝 STT Result: {stt_result}")

            # Clean up temp file
            try:
                os.unlink(temp_file.name)
                print("🗑️ Temp file cleaned up")
            except Exception as e:
                print(f"⚠️ Error removing temp file: {e}")

            print("✅ STT request completed")
            print("=" * 60)
            return jsonify(stt_result)

        else:
            print("❌ No audio file in request")
            return jsonify({
                "error": "No audio file",
                "message": "No audio file received."
            }), 422

    except Exception as e:
        print(f"❌ Error in STT: {str(e)}")
        import traceback
        traceback.print_exc()
        print("=" * 60)
        return jsonify({"error": str(e)}), 500


@routes.route("/sts", methods=["POST"])
def handle_speech_to_speech():
    """Speech-to-speech endpoint using REST API"""
    print("🎤 Speech-to-Speech Request")
    
    try:
        if 'audio' in request.files:
            file = request.files['audio']
            
            if file.filename == '':
                print("❌ No file selected")
                return jsonify({"error": "No file selected"}), 400

            language = request.form.get('language')
            session_id = request.form.get('session_id')
            fingerprint = request.form.get('fingerprint')

            # Save uploaded file temporarily
            import tempfile
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.webm')
            file.save(temp_file.name)
            temp_file.close()

            file_size = os.path.getsize(temp_file.name)
            
            # Check if file is not empty
            if file_size == 0:
                print("❌ Audio file is empty!")
                os.unlink(temp_file.name)
                return jsonify({
                    "error": "Empty audio file",
                    "message": "The recorded audio file is empty. Please try speaking more clearly."
                }), 400

            # Process speech-to-text
            from app.speech import speech_to_text_from_file_rest
            stt_result = speech_to_text_from_file_rest(temp_file.name, language=language)

            # Clean up temp file
            try:
                os.unlink(temp_file.name)
            except Exception as e:
                pass

            if stt_result["status"] != "success" or not stt_result["text"]:
                print(f"❌ Speech recognition failed")
                return jsonify({
                    "error": "No valid speech detected",
                    "message": stt_result.get("message", "Could not detect speech in audio. Please speak more clearly."),
                    "debug_info": stt_result
                }), 400

            user_text = stt_result["text"]
            print(f"👤 User said: '{user_text}'")

            if not session_id:
                print("❌ No session ID provided")
                return jsonify({"error": "No session ID provided"}), 400

            # Store user message
            store_message(session_id, user_text, "user")

            # Get chatbot response
            from app.speech import get_chatbot_response, is_first_bot_response_in_session

            is_first_interaction = is_first_bot_response_in_session(session_id)
            
            response_text = get_chatbot_response(user_text, session_id=session_id, language=language)

            # Add intro if first interaction
            final_response_text = response_text
            if is_first_interaction:
                if language == "nl-NL":
                    intro = "Neem mijn stem niet te serieus, ik ben ook maar een AI. Maar om je vraag te beantwoorden: "
                else:
                    intro = "Please go easy on my voice, I'm just an AI. But to answer your question: "
                final_response_text = intro + response_text

            # Store bot response
            store_message(session_id, final_response_text, "bot")

            print(f"🤖 Bot responded: '{final_response_text}'")

            # Generate speech
            from app.speech import text_to_speech_rest
            tts_output_path = text_to_speech_rest(final_response_text, language=language)

            if not tts_output_path:
                print("❌ TTS generation failed")
                return jsonify({"error": "Failed to generate speech response"}), 500

            # Read and encode audio
            try:
                with open(tts_output_path, "rb") as f:
                    audio_data = f.read()
                    audio_base64 = base64.b64encode(audio_data).decode("utf-8")

                # Clean up generated audio file
                try:
                    os.remove(tts_output_path)
                except Exception as e:
                    pass

                response_data = {
                    "user_text": user_text,
                    "bot_text": final_response_text,
                    "audio_base64": audio_base64,
                    "language": language,
                    "session_id": session_id,
                    "is_first_interaction": is_first_interaction
                }
                
                print("✅ Speech-to-speech completed")
                return jsonify(response_data)
                
            except Exception as e:
                print(f"❌ Error processing audio output: {str(e)}")
                return jsonify({"error": f"Failed to process audio output: {str(e)}"}), 500

        else:
            print("❌ No audio file in request")
            return jsonify({
                "error": "microphone_not_available",
                "message": "No audio file received. Please check microphone permissions."
            }), 422

    except Exception as e:
        print(f"❌ Error in speech-to-speech: {str(e)}")
        import traceback
        traceback.print_exc()
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
    """Keep this for direct testing of your Python app"""
    user_ip = get_client_ip()
    print(f"Frontend Home Page - User IP: {user_ip}")
    session_id = create_chat_session()
    return render_template("index.html", session_id=session_id)