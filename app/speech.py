import os
from dotenv import load_dotenv
import azure.cognitiveservices.speech as speechsdk

load_dotenv()

speech_key = os.getenv("AZURE_SPEECH_KEY")
service_region = os.getenv("AZURE_SPEECH_REGION")

speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=service_region)

def text_to_speech(text, language="en-US"):
    if language == "nl-NL":
        speech_config.speech_synthesis_voice_name = "nl-NL-ColetteNeural"
    else:
        speech_config.speech_synthesis_voice_name = "en-US-JennyNeural"

    output_path = "temp_audio.wav"

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