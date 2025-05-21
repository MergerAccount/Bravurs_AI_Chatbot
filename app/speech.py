import os
from dotenv import load_dotenv
import azure.cognitiveservices.speech as speechsdk
import tempfile
import requests

load_dotenv()

speech_key = os.getenv("AZURE_SPEECH_KEY")
service_region = os.getenv("AZURE_SPEECH_REGION")

speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=service_region)


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


def speech_to_speech(language=None):
    stt_result = speech_to_text(language=language)

    if stt_result["status"] != "success" or not stt_result["text"]:
        print("No valid speech input detected")
        return None

    user_text = stt_result["text"]
    detected_language = stt_result["language"]

    response_text = get_chatbot_response(user_text)

    tts_output_path = text_to_speech(response_text, language=detected_language)

    return {
        "audio_path": tts_output_path,
        "original_text": user_text,
        "response_text": response_text,
        "language": detected_language
    }

def get_chatbot_response(user_text, session_id=None):
    url = "http://localhost:5000/api/v1/chat"
    data = {
        "user_input": user_text,
        "session_id": session_id or ""
    }

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


def save_audio_file(audio_data):

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
    temp_file.write(audio_data)
    temp_file.close()
    return temp_file.name