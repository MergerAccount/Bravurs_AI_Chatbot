import os
from dotenv import load_dotenv
import azure.cognitiveservices.speech as speechsdk
import tempfile
import requests
from app.database import get_session_messages
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


_intro_said_sessions = set()
load_dotenv()

speech_key = os.getenv("AZURE_SPEECH_KEY")
service_region = os.getenv("AZURE_SPEECH_REGION")

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
    speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=service_region)
    audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)

    if language == "nl-NL":
        speech_config.speech_recognition_language = "nl-NL"
        speech_recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config
        )
        print("Listening for Dutch speech...")
    elif language == "en-US":
        speech_config.speech_recognition_language = "en-US"
        speech_recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config
        )
        print("Listening for English speech...")
    else:
        print("Using language auto-detection...")
        auto_detect_source_language_config = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
            languages=["nl-NL", "en-US"]
        )
        speech_recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
            auto_detect_source_language_config=auto_detect_source_language_config
        )

    print("Speak now...")

    result = speech_recognizer.recognize_once_async().get()

    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        if language:
            detected_language = language
        else:
            try:
                auto_detect_result = speechsdk.AutoDetectSourceLanguageResult(result)
                detected_language = auto_detect_result.language
            except:
                detected_language = "unknown"

        print(f"Detected language: {detected_language}")
        print(f"Original recognized text: {result.text}")

        corrected_text = bravur_corrector.correct_text(result.text)

        if corrected_text != result.text:
            print(f"Bravur correction applied: '{result.text}' -> '{corrected_text}'")

        print(f"Final recognized text: {corrected_text}")

        return {
            "text": corrected_text,
            "language": detected_language,
            "status": "success"
        }
    elif result.reason == speechsdk.ResultReason.NoMatch:
        print("No speech could be recognized")
        return {
            "text": "",
            "language": "",
            "status": "error",
            "message": "No speech recognized."
        }
    elif result.reason == speechsdk.ResultReason.Canceled:
        cancellation_details = result.cancellation_details
        print(f"Speech recognition canceled: {cancellation_details.reason}")
        if cancellation_details.reason == speechsdk.CancellationReason.Error:
            print(f"Error details: {cancellation_details.error_details}")

        return {
            "text": "",
            "language": "",
            "status": "error",
            "message": f"Speech recognition canceled: {cancellation_details.reason}. Details: {cancellation_details.error_details}"
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
        return True  # If no session ID, treat as first interaction

    try:
        # Get all messages for this session
        messages = get_session_messages(session_id)

        # Count bot messages (excluding system messages)
        bot_message_count = 0
        for message in messages:
            if message.get('type') == 'bot' or message.get('sender') == 'bot':
                bot_message_count += 1

        # If there are no bot messages yet, this is the first one
        return bot_message_count == 0

    except Exception as e:
        print(f"Error checking message history: {e}")
        # If we can't check the history, fall back to the session tracking
        return session_id not in _intro_said_sessions


def speech_to_speech(language=None, session_id=None):
    print(f"=== DEBUGGING SESSION ===")
    print(f"Starting speech_to_speech with language: {language}, session_id: {session_id}")
    print(f"Session ID type: {type(session_id)}")
    print(f"Session ID value: '{session_id}'")

    stt_result = speech_to_text(language=language)

    print(f"Speech-to-text result: {stt_result}")

    if stt_result["status"] != "success" or not stt_result["text"]:
        print("No valid speech input detected")
        return None

    user_text = stt_result["text"]
    print(f"Recognized text: {user_text}")

    response_language = language if language else stt_result["language"]
    print(f"Using response language: {response_language}")

    # Debug session messages in detail
    is_first_interaction = False
    if session_id:
        session_messages = get_session_messages(session_id)
        print(f"=== SESSION DEBUG ===")
        print(f"Session messages count: {len(session_messages)}")
        print(f"Raw session messages: {session_messages}")

        # Count and list all message types
        user_messages = []
        bot_messages = []
        system_messages = []

        for i, (timestamp, content, session, msg_type) in enumerate(session_messages):
            print(f"Message {i}: session='{session}', type='{msg_type}', content='{content[:50]}...'")
            if msg_type == "user":
                user_messages.append(content)
            elif msg_type == "bot":
                bot_messages.append(content)
            elif msg_type == "system":
                system_messages.append(content)

        print(f"User messages count: {len(user_messages)}")
        print(f"Bot messages count: {len(bot_messages)}")
        print(f"System messages count: {len(system_messages)}")

        is_first_interaction = len(bot_messages) == 0
    else:
        print("=== NO SESSION ID ===")
        is_first_interaction = True

    print(f"Is first interaction: {is_first_interaction}")
    print(f"=== END SESSION DEBUG ===")

    # Get the chatbot response
    response_text = get_chatbot_response(user_text, session_id=session_id, language=response_language)
    print(f"Got response text: {response_text[:50]}...")

    # Add joke only if this is the first bot response in this session
    if is_first_interaction:
        if response_language == "nl-NL":
            intro = "Neem mijn stem niet te serieus, ik ben ook maar een AI. Maar om je vraag te beantwoorden: "
        else:
            intro = "Please go easy on my voice, I'm just an AI. But to answer your question: "
        response_text = intro + response_text
        print("*** ADDED INTRO JOKE TO RESPONSE ***")
    else:
        print("*** NO INTRO ADDED - NOT FIRST INTERACTION ***")

    tts_output_path = text_to_speech(response_text, language=response_language)
    print(f"Generated speech at: {tts_output_path}")

    return {
        "audio_path": tts_output_path,
        "original_text": user_text,
        "response_text": response_text,
        "language": response_language
    }


def save_audio_file(audio_data):
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
    temp_file.write(audio_data)
    temp_file.close()
    return temp_file.name


def reset_session_intro(session_id):
    """
    Helper function to reset the intro status for a session.
    Call this when a new session starts or when you want to reset the intro.
    """
    if session_id in _intro_said_sessions:
        _intro_said_sessions.remove(session_id)
        print(f"Reset intro status for session: {session_id}")


def clear_old_sessions():
    """
    Helper function to clear old session tracking.
    You might want to call this periodically to prevent memory buildup.
    """
    global _intro_said_sessions
    _intro_said_sessions.clear()
    print("Cleared all session intro tracking")


def add_bravur_misrecognition(misrecognition):
    bravur_corrector.add_known_misrecognition(misrecognition)
    print(f"Added new Bravur misrecognition: '{misrecognition}' -> 'Bravur'")