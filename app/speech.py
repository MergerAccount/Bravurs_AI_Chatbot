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
    raise ValueError("Azure Speech credentials not found in environment variables!")

speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=service_region)

bravur_corrector = BravurCorrector()


def remove_emojis(text):
    """Remove emojis from text for TTS processing"""
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # flags (iOS)
        "\U00002700-\U000027BF"  # dingbats
        "\U0001F900-\U0001F9FF"  # supplemental symbols
        "\U00002600-\U000026FF"  # miscellaneous symbols
        "\U0001F170-\U0001F251"
        "]+",
        flags=re.UNICODE
    )
    return emoji_pattern.sub('', text).strip()


def prepare_text_for_tts(text):
    """Prepare text for text-to-speech by removing emojis and cleaning up"""
    clean_text = remove_emojis(text)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()

    return clean_text


def text_to_speech(text, language="en-US"):
    # Clean the text for TTS - this is the key change!
    clean_text = prepare_text_for_tts(text)

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

    # Use the cleaned text instead of the original
    result = speech_synthesizer.speak_text_async(clean_text).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        print("Speech synthesized successfully!")
        print(f"Original text: {text[:50]}...")
        print(f"Clean text for TTS: {clean_text[:50]}...")
        return output_path
    else:
        print(f"Error: {result.reason}")
        return None


def speech_to_text(language=None):
    # Create fresh speech config for each call
    speech_config_stt = speechsdk.SpeechConfig(subscription=speech_key, region=service_region)
    audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)

    if language == "nl-NL":
        speech_config_stt.speech_recognition_language = "nl-NL"
        print("Configured for Dutch speech recognition")
    elif language == "en-US":
        speech_config_stt.speech_recognition_language = "en-US"
        print("Configured for English speech recognition")
    else:
        speech_config_stt.speech_recognition_language = "nl-NL"  # Default to Dutch

    speech_recognizer = speechsdk.SpeechRecognizer(
        speech_config=speech_config_stt,
        audio_config=audio_config,
    )

    print("Speak now...")

    try:
        result = speech_recognizer.recognize_once_async().get()
    except Exception as e:
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
            except:
                detected_language = "nl-NL"

        # Apply Bravur correction
        corrected_text = bravur_corrector.correct_text(result.text)

        return {
            "text": corrected_text,
            "language": detected_language,
            "status": "success"
        }
    elif result.reason == speechsdk.ResultReason.NoMatch:
        return {
            "text": "",
            "language": "",
            "status": "error",
            "message": "No speech recognized. Please check your microphone and speak clearly."
        }
    elif result.reason == speechsdk.ResultReason.Canceled:
        cancellation_details = result.cancellation_details
        error_message = "Speech recognition canceled"
        if cancellation_details.reason == speechsdk.CancellationReason.Error:
            error_message = f"Recognition error: {cancellation_details.error_details}"

        return {
            "text": "",
            "language": "",
            "status": "error",
            "message": error_message
        }


def get_chatbot_response(user_text, session_id=None, language=None):
    url = "https://bravur-chatbot-api-bwepc9bna4fvg8fn.westeurope-01.azurewebsites.net/api/v1/chat"
    data = {
        "user_input": user_text,
        "session_id": session_id or ""
    }

    if language:
        data["language"] = language

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
        bot_message_count = 0

        for i, message in enumerate(messages):
            if isinstance(message, tuple) and len(message) >= 4:
                message_id, content, timestamp, message_type = message[:4]

                if message_type == 'bot':
                    bot_message_count += 1
            else:
                continue

        is_first = bot_message_count == 0

        return is_first

    except Exception as e:
        return True


def speech_to_speech(language=None, session_id=None):
    stt_result = speech_to_text(language=language)

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
        return {
            "error": "No session ID provided",
            "session_id": None
        }

    # Step 4: Store the user message in the database
    user_message_id = store_message(session_id, user_text, "user")

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

    # Step 8: Store the bot response in the database
    bot_message_id = store_message(session_id, final_response_text, "bot")

    # Step 9: Convert response to speech
    tts_output_path = text_to_speech(final_response_text, language=response_language)

    # Step 10: Return complete result
    return {
        "audio_path": tts_output_path,
        "original_text": user_text,
        "response_text": final_response_text,
        "language": response_language,
        "session_id": session_id,
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
    pass


def add_bravur_misrecognition(misrecognition):
    bravur_corrector.add_known_misrecognition(misrecognition)


# New helper function to validate session continuity
def validate_session_continuity(session_id):
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
        return True
    except Exception as e:
        if conn:
            conn.close()
        return False


# Test function to verify Azure Speech setup
def test_azure_speech_setup():
    """
    Test function to verify Azure Speech Service is working
    """
    if not speech_key or not service_region:
        return False

    try:
        test_config = speechsdk.SpeechConfig(subscription=speech_key, region=service_region)
        test_config.speech_synthesis_voice_name = "en-US-JennyNeural"

        synthesizer = speechsdk.SpeechSynthesizer(speech_config=test_config)
        result = synthesizer.speak_text_async("Testing Azure Speech").get()

        return result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted

    except Exception as e:
        return False