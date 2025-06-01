import os
from dotenv import load_dotenv
import azure.cognitiveservices.speech as speechsdk
import tempfile
import requests
import re

load_dotenv()

speech_key = os.getenv("AZURE_SPEECH_KEY")
service_region = os.getenv("AZURE_SPEECH_REGION")

speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=service_region)


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
        print(f"Recognized text: {result.text}")

        return {
            "text": result.text,
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


def speech_to_speech(language=None, session_id=None):
    print(f"Starting speech_to_speech with language: {language}, session_id: {session_id}")
    stt_result = speech_to_text(language=language)

    print(f"Speech-to-text result: {stt_result}")

    if stt_result["status"] != "success" or not stt_result["text"]:
        print("No valid speech input detected")
        return None

    user_text = stt_result["text"]
    print(f"Recognized text: {user_text}")

    response_language = language if language else stt_result["language"]
    print(f"Using response language: {response_language}")

    # Make sure to pass session_id to get_chatbot_response
    response_text = get_chatbot_response(user_text, session_id=session_id, language=response_language)
    print(f"Got response text: {response_text[:50]}...")

    # The text_to_speech function now automatically removes emojis
    tts_output_path = text_to_speech(response_text, language=response_language)
    print(f"Generated speech at: {tts_output_path}")

    return {
        "audio_path": tts_output_path,
        "original_text": user_text,
        "response_text": response_text,  # Keep original with emojis for display
        "language": response_language
    }


def save_audio_file(audio_data):
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
    temp_file.write(audio_data)
    temp_file.close()
    return temp_file.name