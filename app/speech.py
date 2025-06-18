import os
import requests
import tempfile
import json
import time
import wave
from dotenv import load_dotenv
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
        if (word_clean.startswith('bra') and len(word_clean) >= 5 and len(word_clean) <= 8):
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

if not speech_key or not service_region:
    raise ValueError("Azure Speech credentials not found in environment variables!")

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


def text_to_speech_rest(text, language="en-US"):
    """Text-to-speech using Azure REST API"""
    clean_text = prepare_text_for_tts(text)

    # Choose voice based on language
    if language == "nl-NL":
        voice_name = "nl-NL-FennaNeural"
    else:
        voice_name = "en-US-JennyNeural"

    # Get access token
    token_url = f"https://{service_region}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
    headers = {
        'Ocp-Apim-Subscription-Key': speech_key
    }

    try:
        token_response = requests.post(token_url, headers=headers)
        token_response.raise_for_status()
        access_token = token_response.text
    except Exception as e:
        print(f"Error getting access token: {e}")
        return None

    # Create SSML
    ssml = f'''<speak version='1.0' xml:lang='{language}'>
        <voice xml:lang='{language}' xml:gender='Female' name='{voice_name}'>
            {clean_text}
        </voice>
    </speak>'''

    # Make TTS request
    tts_url = f"https://{service_region}.tts.speech.microsoft.com/cognitiveservices/v1"
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/ssml+xml',
        'X-Microsoft-OutputFormat': 'riff-16khz-16bit-mono-pcm',
        'User-Agent': 'BravurChatbot'
    }

    try:
        response = requests.post(tts_url, headers=headers, data=ssml.encode('utf-8'))
        response.raise_for_status()

        # Save to temp file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        temp_file.write(response.content)
        temp_file.close()

        print("Speech synthesized successfully using REST API!")
        print(f"Original text: {text[:50]}...")
        print(f"Clean text for TTS: {clean_text[:50]}...")
        return temp_file.name

    except Exception as e:
        print(f"Error in TTS REST API: {e}")
        return None


def speech_to_text_from_file_rest(audio_file_path, language=None):
    """Speech-to-text from file using Azure REST API"""

    # Get access token
    token_url = f"https://{service_region}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
    headers = {
        'Ocp-Apim-Subscription-Key': speech_key
    }

    try:
        token_response = requests.post(token_url, headers=headers)
        token_response.raise_for_status()
        access_token = token_response.text
    except Exception as e:
        print(f"Error getting access token: {e}")
        return {"text": "", "status": "error", "message": f"Token error: {str(e)}"}

    # Set language
    if language == "nl-NL":
        recognition_language = "nl-NL"
    elif language == "en-US":
        recognition_language = "en-US"
    else:
        recognition_language = "nl-NL"  # Default to Dutch

    # Read audio file
    try:
        with open(audio_file_path, 'rb') as audio_file:
            audio_data = audio_file.read()
    except Exception as e:
        return {"text": "", "status": "error", "message": f"File read error: {str(e)}"}

    # Make STT request
    stt_url = f"https://{service_region}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"
    params = {
        'language': recognition_language,
        'format': 'detailed'
    }
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'audio/wav; codecs=audio/pcm; samplerate=16000',
        'Accept': 'application/json'
    }

    try:
        response = requests.post(stt_url, headers=headers, params=params, data=audio_data)
        response.raise_for_status()
        result = response.json()

        print(f"STT REST API response: {result}")

        # Parse response
        if result.get('RecognitionStatus') == 'Success':
            recognized_text = result.get('DisplayText', '')
            if recognized_text:
                # Apply Bravur correction
                corrected_text = bravur_corrector.correct_text(recognized_text)
                return {
                    "text": corrected_text,
                    "status": "success"
                }
            else:
                return {"text": "", "status": "error", "message": "No speech recognized"}
        else:
            return {"text": "", "status": "error", "message": f"Recognition failed: {result.get('RecognitionStatus')}"}

    except Exception as e:
        print(f"Error in STT REST API: {e}")
        return {"text": "", "status": "error", "message": f"STT API error: {str(e)}"}


# Legacy functions for compatibility
def text_to_speech(text, language="en-US"):
    """Wrapper to maintain compatibility"""
    return text_to_speech_rest(text, language)


def speech_to_text_from_file(audio_file_path, language=None):
    """Wrapper to maintain compatibility"""
    return speech_to_text_from_file_rest(audio_file_path, language)


def speech_to_text(language=None):
    """Legacy function - returns error suggesting file upload"""
    return {
        "text": "",
        "language": "",
        "status": "error",
        "message": "Microphone access not available. Please use file upload instead."
    }


def get_chatbot_response(user_text, session_id=None, language=None):
    """Get chatbot response with proper timeout and error handling"""

    # First, try calling the chatbot function directly (more reliable)
    try:
        from app.chatbot import company_info_handler_streaming
        print(f"🧠 Calling chatbot directly...")
        response_chunks = []
        for chunk in company_info_handler_streaming(user_text, session_id=session_id, language=language):
            response_chunks.append(chunk)
        result = "".join(response_chunks)
        print(f"✅ Direct chatbot call successful: {len(result)} chars")
        return result

    except Exception as direct_error:
        print(f"❌ Direct chatbot call failed: {direct_error}")

        # Fallback to HTTP call
        url = "http://127.0.0.1:5000/api/v1/chat"
        data = {
            "user_input": user_text,
            "session_id": session_id or ""
        }

        if language:
            data["language"] = language

        print(f"🌐 Fallback: Making HTTP request to: {url}")

        try:
            response = requests.post(url, data=data, timeout=15)
            print(f"📡 Response status: {response.status_code}")

            if response.status_code == 200:
                full_reply = response.text.strip()
                print(f"✅ HTTP fallback successful: {len(full_reply)} chars")
                return full_reply
            else:
                print(f"❌ HTTP Error: {response.status_code}")
                return "I'm having trouble processing your request. Please try again."

        except Exception as http_error:
            print(f"❌ HTTP fallback also failed: {http_error}")

            # Last resort: simple response
            if language == "nl-NL":
                return "Het spijt me, ik ondervind technische problemen. Kun je je vraag opnieuw stellen?"
            else:
                return "Sorry, I'm experiencing technical difficulties. Could you please rephrase your question?"


def is_first_bot_response_in_session(session_id):
    """Same as before - no changes needed"""
    if not session_id:
        print("No session ID provided, treating as first interaction")
        return True

    try:
        messages = get_session_messages(session_id)
        bot_message_count = 0

        for i, message in enumerate(messages):
            if isinstance(message, tuple) and len(message) >= 4:
                message_id, content, timestamp, message_type = message[:4]
                if message_type == 'bot':
                    bot_message_count += 1
            else:
                continue

        return bot_message_count == 0

    except Exception as e:
        return True


def speech_to_speech_from_file_rest(audio_file_path, language=None, session_id=None):
    """File-based speech-to-speech using REST API"""
    stt_result = speech_to_text_from_file_rest(audio_file_path, language=language)

    if stt_result["status"] != "success" or not stt_result["text"]:
        print("No valid speech input detected in file")
        return {
            "error": "No valid speech input detected in the audio file.",
            "session_id": session_id,
            "debug_info": stt_result
        }

    user_text = stt_result["text"]
    print(f"Recognized text: {user_text}")

    response_language = language if language else "nl-NL"
    print(f"Using response language: {response_language}")

    if not session_id:
        return {
            "error": "No session ID provided",
            "session_id": None
        }

    # Store the user message in the database
    user_message_id = store_message(session_id, user_text, "user")

    # Check if this is the first bot response
    is_first_interaction = is_first_bot_response_in_session(session_id)
    print(f"Is first bot interaction in session: {is_first_interaction}")

    # Get the chatbot response
    response_text = get_chatbot_response(user_text, session_id=session_id, language=response_language)
    print(f"Got response text: {response_text[:50]}...")

    # Add intro joke only if this is the first bot response in this session
    final_response_text = response_text
    if is_first_interaction:
        if response_language == "nl-NL":
            intro = "Neem mijn stem niet te serieus, ik ben ook maar een AI. Maar om je vraag te beantwoorden: "
        else:
            intro = "Please go easy on my voice, I'm just an AI. But to answer your question: "
        final_response_text = intro + response_text

    # Store the bot response in the database
    bot_message_id = store_message(session_id, final_response_text, "bot")

    # Convert response to speech using REST API
    tts_output_path = text_to_speech_rest(final_response_text, language=response_language)

    # Return complete result
    return {
        "audio_path": tts_output_path,
        "original_text": user_text,
        "response_text": final_response_text,
        "language": response_language,
        "session_id": session_id,
        "is_first_interaction": is_first_interaction
    }


def speech_to_speech(language=None, session_id=None):
    """Legacy function - returns error for microphone access"""
    return {
        "error": "Microphone access not available. Please use file upload endpoint instead.",
        "session_id": session_id
    }


def save_audio_file(audio_data):
    """Same as before - no changes needed"""
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
    temp_file.write(audio_data)
    temp_file.close()
    return temp_file.name


def reset_session_intro(session_id):
    """Compatibility function"""
    pass


def add_bravur_misrecognition(misrecognition):
    """Same as before"""
    bravur_corrector.add_known_misrecognition(misrecognition)


def validate_session_continuity(session_id):
    """Same as before - no changes needed"""
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
    """Same as before - no changes needed"""
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


def test_azure_speech_setup():
    """Test function using REST API"""
    if not speech_key or not service_region:
        return False

    try:
        # Test with a simple TTS call
        result = text_to_speech_rest("Testing Azure Speech REST API")
        return result is not None
    except Exception as e:
        print(f"REST API test failed: {e}")
        return False