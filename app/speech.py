import os
from dotenv import load_dotenv
import azure.cognitiveservices.speech as speechsdk
import tempfile
import requests
from app.database import get_session_messages, store_message
import re
from difflib import SequenceMatcher


class BravurCorrector:
    def __init__(self):
        # Known misrecognitions of Bravur
        self.exact_corrections = {
            "barber": "Bravur",
            "bravo": "Bravur",
            "barbara": "Bravur",
            "brevard": "Bravur",
            "bravoure": "Bravur",
            "bravure": "Bravur",
            "braver": "Bravur",
            "bravor": "Bravur",
            "bravour": "Bravur",
            "brabur": "Bravur",
            "brapur": "Bravur"
        }

        self.similarity_threshold = 0.65

    def similarity_score(self, word1, word2):
        return SequenceMatcher(None, word1.lower(), word2.lower()).ratio()

    def is_likely_bravur(self, word):
        word_clean = word.lower().strip('.,!?;:')

        if word_clean in self.exact_corrections:
            return True

        if self.similarity_score(word_clean, "bravur") > self.similarity_threshold:
            return True

        if (word_clean.startswith('bra') and
                len(word_clean) >= 5 and len(word_clean) <= 8):
            if self.similarity_score(word_clean, "bravur") > 0.5:
                return True

        return False

    def correct_text(self, text):
        if not text:
            return text

        words = text.split()
        corrected_words = []

        for word in words:
            punctuation = ""
            clean_word = word

            while clean_word and clean_word[-1] in '.,!?;:':
                punctuation = clean_word[-1] + punctuation
                clean_word = clean_word[:-1]

            if self.is_likely_bravur(clean_word):
                corrected_words.append("Bravur" + punctuation)
            else:
                corrected_words.append(word)

        return " ".join(corrected_words)

    def add_known_misrecognition(self, misrecognition):
        self.exact_corrections[misrecognition.lower()] = "Bravur"


load_dotenv()

speech_key = os.getenv("AZURE_SPEECH_KEY")
service_region = os.getenv("AZURE_SPEECH_REGION")

# Validate Azure credentials
if not speech_key or not service_region:
    print("ERROR: Azure Speech credentials not found in environment variables!")
    print(f"AZURE_SPEECH_KEY exists: {bool(speech_key)}")
    print(f"AZURE_SPEECH_REGION exists: {bool(service_region)}")

speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=service_region)

bravur_corrector = BravurCorrector()


def text_to_speech(text, language="en-US"):
    if language == "nl-NL":
        speech_config.speech_synthesis_voice_name = "nl-NL-FennaNeural"
    else:
        speech_config.speech_synthesis_voice_name = "en-US-JennyNeural"

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    temp_file.close()
    output_path = temp_file.name

    speech_synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config,
        audio_config=speechsdk.audio.AudioOutputConfig(filename=output_path)
    )

    result = speech_synthesizer.speak_text_async(text).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        print("Speech synthesized successfully!")
        return output_path
    else:
        print(f"Error: {result.reason}")
        return None


def speech_to_text(language=None):
    print(f"=== SPEECH TO TEXT DEBUG ===")
    print(f"Input language: {language}")
    print(f"Azure Speech Key exists: {bool(speech_key)}")
    print(f"Azure Speech Region: {service_region}")

    # Create fresh speech config for each call
    speech_config_stt = speechsdk.SpeechConfig(subscription=speech_key, region=service_region)

    # Configure audio input with better settings
    audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)

    if language == "nl-NL":
        speech_config_stt.speech_recognition_language = "nl-NL"
        print("Configured for Dutch speech recognition")
    elif language == "en-US":
        speech_config_stt.speech_recognition_language = "en-US"
        print("Configured for English speech recognition")
    else:
        print("Using language auto-detection...")
        # Set a default language for better recognition
        speech_config_stt.speech_recognition_language = "nl-NL"  # Default to Dutch

    # Configure recognition settings for better performance
    speech_config_stt.set_property(speechsdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs, "8000")
    speech_config_stt.set_property(speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs, "2000")
    speech_config_stt.set_property(speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, "2000")

    if language and language != "auto":
        speech_recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config_stt,
            audio_config=audio_config
        )
        print(f"Listening for {language} speech...")
    else:
        print("Using auto-detection with fallback...")
        try:
            auto_detect_source_language_config = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
                languages=["nl-NL", "en-US"]
            )
            speech_recognizer = speechsdk.SpeechRecognizer(
                speech_config=speech_config_stt,
                audio_config=audio_config,
                auto_detect_source_language_config=auto_detect_source_language_config
            )
        except Exception as e:
            print(f"Auto-detection failed, falling back to Dutch: {e}")
            speech_recognizer = speechsdk.SpeechRecognizer(
                speech_config=speech_config_stt,
                audio_config=audio_config
            )

    print("Speak now...")

    try:
        # Try continuous recognition with timeout
        result = speech_recognizer.recognize_once_async().get()

        print(f"Recognition result reason: {result.reason}")
        print(f"Recognition result text: '{result.text}'")

    except Exception as e:
        print(f"Recognition exception: {e}")
        return {
            "text": "",
            "language": "",
            "status": "error",
            "message": f"Recognition exception: {str(e)}"
        }

    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        if language:
            detected_language = language
        else:
            try:
                auto_detect_result = speechsdk.AutoDetectSourceLanguageResult(result)
                detected_language = auto_detect_result.language
                print(f"Auto-detected language: {detected_language}")
            except:
                detected_language = "nl-NL"  # Default fallback
                print("Language detection failed, using Dutch as default")

        print(f"Detected language: {detected_language}")
        print(f"Original recognized text: '{result.text}'")

        # Apply Bravur correction
        corrected_text = bravur_corrector.correct_text(result.text)

        if corrected_text != result.text:
            print(f"Bravur correction applied: '{result.text}' -> '{corrected_text}'")

        print(f"Final recognized text: '{corrected_text}'")

        return {
            "text": corrected_text,
            "language": detected_language,
            "status": "success"
        }
    elif result.reason == speechsdk.ResultReason.NoMatch:
        print("No speech could be recognized - possible causes:")
        print("1. Microphone not working or not accessible")
        print("2. No speech detected within timeout period")
        print("3. Speech too quiet or unclear")
        print("4. Background noise interference")

        return {
            "text": "",
            "language": "",
            "status": "error",
            "message": "No speech recognized. Please check your microphone and speak clearly."
        }
    elif result.reason == speechsdk.ResultReason.Canceled:
        cancellation_details = result.cancellation_details
        print(f"Speech recognition canceled: {cancellation_details.reason}")

        error_message = "Speech recognition canceled"
        if cancellation_details.reason == speechsdk.CancellationReason.Error:
            print(f"Error details: {cancellation_details.error_details}")
            error_message = f"Recognition error: {cancellation_details.error_details}"

        return {
            "text": "",
            "language": "",
            "status": "error",
            "message": error_message
        }


def get_chatbot_response(user_text, session_id=None, language=None):
    url = "http://localhost:5000/api/v1/chat"
    data = {
        "user_input": user_text,
        "session_id": session_id or ""
    }

    if language:
        data["language"] = language
        print(f"Adding language to request: {language}")

    try:
        response = requests.post(url, data=data, stream=True)
        if response.status_code == 200:
            full_reply = ""
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    full_reply += chunk.decode("utf-8")
            return full_reply.strip()
        else:
            return "Sorry, I couldn't get a response from the chat service."
    except Exception as e:
        return f"Error contacting chat service: {str(e)}"


def is_first_bot_response_in_session(session_id):
    """
    Check if this is the first bot response in the session by looking at message history
    """
    if not session_id:
        print("No session ID provided, treating as first interaction")
        return True

    try:
        # Get all messages for this session
        messages = get_session_messages(session_id)
        print(f"Retrieved {len(messages)} messages for session {session_id}")

        # Count bot messages
        bot_message_count = 0

        for i, message in enumerate(messages):
            print(f"Message {i}: {message}")

            # The correct format from get_session_messages is:
            # (message_id, content, timestamp, message_type)
            if isinstance(message, tuple) and len(message) >= 4:
                message_id, content, timestamp, message_type = message[:4]
                print(f"Message type identified as: {message_type}")

                if message_type == 'bot':
                    bot_message_count += 1
            else:
                print(f"Unexpected message format: {type(message)} - {message}")
                continue

        print(f"Found {bot_message_count} bot messages in session {session_id}")

        # If there are no bot messages yet, this is the first one
        is_first = bot_message_count == 0

        print(f"{'This is the first' if is_first else 'This is NOT the first'} bot response for session {session_id}")
        return is_first

    except Exception as e:
        print(f"Error checking message history: {e}")
        # If we can't check the history, assume it's the first interaction
        return True


def speech_to_speech(language=None, session_id=None):
    """
    Main speech-to-speech function that properly handles session management

    Args:
        language: Language preference for the conversation
        session_id: Existing session ID to continue the conversation

    Returns:
        Dictionary with audio_path, texts, language, and session_id
    """
    print(f"=== SPEECH TO SPEECH SESSION DEBUG ===")
    print(f"Input - language: {language}, session_id: {session_id}")
    print(f"Session ID type: {type(session_id)}")
    print(f"Session ID value: '{session_id}'")

    # Step 1: Get speech input from user
    stt_result = speech_to_text(language=language)
    print(f"Speech-to-text result: {stt_result}")

    if stt_result["status"] != "success" or not stt_result["text"]:
        print("No valid speech input detected")
        return {
            "error": "No valid speech input detected. Please check your microphone and try speaking again.",
            "session_id": session_id,
            "debug_info": stt_result
        }

    user_text = stt_result["text"]
    print(f"Recognized text: {user_text}")

    # Step 2: Determine response language
    response_language = language if language else stt_result["language"]
    print(f"Using response language: {response_language}")

    # Step 3: Validate and ensure we have a session_id
    if not session_id:
        print("ERROR: No session_id provided to speech_to_speech!")
        return {
            "error": "No session ID provided",
            "session_id": None
        }

    # Step 4: Store the user message in the database
    user_message_id = store_message(session_id, user_text, "user")
    if not user_message_id:
        print(f"WARNING: Failed to store user message in session {session_id}")
    else:
        print(f"Stored user message {user_message_id} in session {session_id}")

    # Step 5: Check if this is the first bot response BEFORE getting the response
    is_first_interaction = is_first_bot_response_in_session(session_id)
    print(f"Is first bot interaction in session: {is_first_interaction}")

    # Step 6: Get the chatbot response
    response_text = get_chatbot_response(user_text, session_id=session_id, language=response_language)
    print(f"Got response text: {response_text[:50]}...")

    # Step 7: Add intro joke only if this is the first bot response in this session
    final_response_text = response_text
    if is_first_interaction:
        if response_language == "nl-NL":
            intro = "Neem mijn stem niet te serieus, ik ben ook maar een AI. Maar om je vraag te beantwoorden: "
        else:
            intro = "Please go easy on my voice, I'm just an AI. But to answer your question: "
        final_response_text = intro + response_text
        print("*** ADDED INTRO JOKE TO RESPONSE ***")
    else:
        print("*** NO INTRO ADDED - NOT FIRST INTERACTION ***")

    # Step 8: Store the bot response in the database
    bot_message_id = store_message(session_id, final_response_text, "bot")
    if not bot_message_id:
        print(f"WARNING: Failed to store bot message in session {session_id}")
    else:
        print(f"Stored bot message {bot_message_id} in session {session_id}")

    # Step 9: Convert response to speech
    tts_output_path = text_to_speech(final_response_text, language=response_language)
    print(f"Generated speech at: {tts_output_path}")

    # Step 10: Return complete result
    return {
        "audio_path": tts_output_path,
        "original_text": user_text,
        "response_text": final_response_text,
        "language": response_language,
        "session_id": session_id,  # Return the same session_id to maintain continuity
        "is_first_interaction": is_first_interaction
    }


def save_audio_file(audio_data):
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
    temp_file.write(audio_data)
    temp_file.close()
    return temp_file.name


def reset_session_intro(session_id):
    """
    Helper function to reset the intro status for a session.
    Since we're now using database-based checking, this function
    doesn't need to do anything, but kept for backward compatibility.
    """
    print(f"Reset intro status called for session: {session_id} (no action needed with DB-based checking)")


def add_bravur_misrecognition(misrecognition):
    bravur_corrector.add_known_misrecognition(misrecognition)
    print(f"Added new Bravur misrecognition: '{misrecognition}' -> 'Bravur'")


# New helper function to validate session continuity
def validate_session_continuity(session_id):
    """
    Validate that a session exists and return relevant info about it
    """
    if not session_id:
        return {"valid": False, "message": "No session ID provided"}

    try:
        messages = get_session_messages(session_id)
        return {
            "valid": True,
            "message_count": len(messages),
            "has_bot_messages": any(msg[3] == 'bot' for msg in messages if len(msg) >= 4)
        }
    except Exception as e:
        return {"valid": False, "message": f"Session validation error: {e}"}


def update_session_voice_usage(session_id):
    """
    Mark a session as having used voice features
    """
    from app.database import get_db_connection

    conn = get_db_connection()
    if conn is None:
        return False

    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE chat_session SET voice_enabled = TRUE WHERE session_id = %s",
            (session_id,)
        )
        conn.commit()
        cursor.close()
        conn.close()
        print(f"Marked session {session_id} as voice-enabled")
        return True
    except Exception as e:
        print(f"Error updating session voice usage: {e}")
        if conn:
            conn.close()
        return False


# Test function to verify Azure Speech setup
def test_azure_speech_setup():
    """
    Test function to verify Azure Speech Service is working
    """
    print("=== TESTING AZURE SPEECH SETUP ===")

    if not speech_key or not service_region:
        print("❌ Azure credentials missing!")
        return False

    try:
        # Test TTS
        test_config = speechsdk.SpeechConfig(subscription=speech_key, region=service_region)
        test_config.speech_synthesis_voice_name = "en-US-JennyNeural"

        synthesizer = speechsdk.SpeechSynthesizer(speech_config=test_config)
        result = synthesizer.speak_text_async("Testing Azure Speech").get()

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            print("✅ Azure Speech Service connection successful!")
            return True
        else:
            print(f"❌ Azure Speech Service test failed: {result.reason}")
            return False

    except Exception as e:
        print(f"❌ Azure Speech Service error: {e}")
        return False