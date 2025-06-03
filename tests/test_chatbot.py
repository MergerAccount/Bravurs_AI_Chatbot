import pytest
import requests
import json
import logging
import re
from difflib import SequenceMatcher

API_URL = "http://127.0.0.1:5000/api/v1/chat"
SESSION_URL = "http://127.0.0.1:5000/api/v1/session/create"

# Load test prompts
with open("test_prompts_bravur.json", "r", encoding="utf-8") as f:
    test_cases = json.load(f)

def is_acceptable_paraphrase(response: str, expected_keywords: list) -> bool:
    """
    Accept the response if it shares semantic meaning with any expected keyword/phrase.
    """
    response_lower = response.lower()
    for keyword in expected_keywords:
        similarity = SequenceMatcher(None, keyword.lower(), response_lower).ratio()
        if similarity >= 0.65:  # Accept paraphrased matches
            return True
    return False

def is_valid_english_or_emoji(text: str) -> bool:
    """
    Accept if mostly ASCII and/or contains emoji.
    """
    try:
        ascii_text = re.sub(r'[^\x00-\x7F\u1F600-\u1F64F]+', '', text)
        return len(ascii_text) / max(1, len(text)) >= 0.7
    except Exception:
        return False

@pytest.fixture(scope="module")
def session_id():
    try:
        res = requests.post(SESSION_URL)
        res.raise_for_status()
        session_id = res.json().get("session_id")

        # Accept consent
        consent_res = requests.post("http://127.0.0.1:5000/api/v1/consent/accept", json={"session_id": session_id})
        consent_res.raise_for_status()

        return session_id
    except Exception as e:
        logging.error(f"Failed to get session ID: {e}")
        pytest.skip("Skipping tests because no session ID could be obtained")

@pytest.mark.parametrize("test_case", test_cases)
def test_chatbot_responses(test_case, session_id):
    prompt = test_case["prompt"]
    expected_keywords = test_case.get("expected_keywords", [])
    expect_error = test_case.get("expect_error", False)

    try:
        res = requests.post(
            API_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"user_input": prompt, "session_id": session_id, "language": "en-US"}
        )

        assert res.status_code == 200, f"API Error: {res.status_code}"

        content_type = res.headers.get("Content-Type", "")
        if "application/json" in content_type:
            response_text = res.json().get("response", "")
        else:
            print(f"⚠️ Expected JSON but got: {content_type}")
            response_text = res.text.strip()

        if not response_text:
            raise ValueError("Received an empty response.")

        if not is_valid_english_or_emoji(response_text):
            raise AssertionError("Response may not be in understandable English.")

        if expect_error:
            assert "[Error" in response_text or "couldn’t find" in response_text.lower()
        elif expected_keywords:
            assert is_acceptable_paraphrase(response_text, expected_keywords), \
                f"Relevant keywords not found or paraphrased too far off: {response_text}"
        else:
            assert response_text.strip(), "Empty response received"

    except Exception as e:
        print("⚠️ Test failed.")
        print(f"Prompt: {prompt}")
        print(f"Raw response:\n{res.text}")
        print(f"Exception:\n{e}")
        logging.exception(f"Test case failed: {prompt}")
        assert False, f"Exception occurred during test: {e}"
