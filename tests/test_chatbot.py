import pytest
import requests
import json
import logging
import re
from difflib import SequenceMatcher

API_URL = "http://127.0.0.1:5000/api/v1/chat"
SESSION_URL = "http://127.0.0.1:5000/api/v1/session/create"
CONSENT_URL = "http://127.0.0.1:5000/api/v1/consent/accept"

LOG_FILE = "chatbot_test_output.txt"
PROMPT_FILE = "test_prompts_bravur.json"

# Reset the log file
with open(LOG_FILE, "w", encoding="utf-8") as f:
    f.write("BRAVUR CHATBOT TEST RESULTS\n" + "=" * 80 + "\n")

def log_result(title: str, prompt: str, expected_keywords: list, response: str, exception: str = None):
    block = f"\n{'='*80}\n{title}\nPrompt:\n{prompt}\nExpected Keywords: {expected_keywords}\n"
    block += f"Response:\n{response.strip() if response else '[EMPTY]'}\n"
    if exception:
        block += f"Exception:\n{exception}\n"
    block += f"{'='*80}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(block)

def is_acceptable_paraphrase(response: str, expected_keywords: list) -> bool:
    response_lower = response.lower()
    for keyword in expected_keywords:
        similarity = SequenceMatcher(None, keyword.lower(), response_lower).ratio()
        if similarity >= 0.65:
            return True
    return False

def is_valid_english_or_emoji(text: str) -> bool:
    try:
        ascii_text = re.sub(r'[^\x00-\x7F\u1F600-\u1F64F]+', '', text)
        return len(ascii_text) / max(1, len(text)) >= 0.7
    except Exception:
        return False

# Load test prompts
with open(PROMPT_FILE, "r", encoding="utf-8") as f:
    test_cases = json.load(f)

@pytest.fixture(scope="module")
def session_id():
    try:
        res = requests.post(SESSION_URL)
        res.raise_for_status()
        sid = res.json().get("session_id")

        # Accept consent
        consent_res = requests.post(CONSENT_URL, json={"session_id": sid})
        consent_res.raise_for_status()

        return sid
    except Exception as e:
        pytest.skip(f"❌ Failed to create session or accept consent: {e}")

@pytest.mark.parametrize("test_case", test_cases)
def test_chatbot_responses(test_case, session_id):
    prompt = test_case["prompt"]
    expected_keywords = test_case.get("expected_keywords", [])
    expect_error = test_case.get("expect_error", False)

    try:
        # Keep x-www-form-urlencoded format
        response = requests.post(
            API_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "user_input": prompt,
                "session_id": session_id,
                "language": "en-US"
            }
        )
        response.raise_for_status()

        if "application/json" in response.headers.get("Content-Type", ""):
            response_text = response.json().get("response", "")
        else:
            response_text = response.text.strip()

        if not response_text:
            raise ValueError("Empty response from API")

        if not is_valid_english_or_emoji(response_text):
            raise AssertionError("Response might not be in English or recognizable")

        # Test expectations
        if expect_error:
            assert "[Error" in response_text or "not supported" in response_text.lower() \
                   or "not allowed" in response_text.lower() or "unsupported" in response_text.lower(), \
                   "Expected error but response seems normal"
        elif expected_keywords:
            assert is_acceptable_paraphrase(response_text, expected_keywords), \
                f"Response lacks expected keywords or paraphrases: {response_text}"
        else:
            assert response_text.strip(), "Response is unexpectedly blank"

        log_result("✅ PASSED", prompt, expected_keywords, response_text)

    except Exception as e:
        response_text = response.text if 'response' in locals() and hasattr(response, 'text') else "[NO RESPONSE]"
        log_result("❌ FAILED", prompt, expected_keywords, response_text, str(e))
        assert False, f"Test failed: {e}"
