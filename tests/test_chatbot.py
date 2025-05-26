import pytest
import requests
import json
import logging

API_URL = "http://localhost:5000/api/v1/chat"  # Change this to your running endpoint
SESSION_URL = "http://localhost:5000/api/v1/session"  # Endpoint to get new session

# Load prompts from JSON file
with open("test_prompts_bravur.json", "r", encoding="utf-8") as f:
    test_cases = json.load(f)

def is_hallucination(response: str, expected_keywords: list) -> bool:
    """
    Basic heuristic to flag hallucinations: if expected keywords (or phrases) are missing.
    """
    response_lower = response.lower()
    return not any(keyword.lower() in response_lower for keyword in expected_keywords)

@pytest.fixture(scope="module")
def session_id():
    try:
        res = requests.post(SESSION_URL)  # or .get() depending on your API
        res.raise_for_status()
        return res.json().get("session_id")
    except Exception as e:
        logging.error(f"Failed to get session ID: {e}")
        pytest.skip("Skipping tests because no session ID could be obtained")
@pytest.mark.parametrize("test_case", test_cases)
def test_chatbot_responses(test_case):
    prompt = test_case["prompt"]
    expected_keywords = test_case.get("expected_keywords", [])
    expect_error = test_case.get("expect_error", False)

    try:
        res = requests.post(
            API_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"user_input": prompt, "session_id": session_id}
        )
        assert res.status_code == 200, f"API Error: {res.status_code}"
        response_text = res.json().get("response", "")

        if expect_error:
            assert "[Error" in response_text or "couldn’t find" in response_text.lower()
        elif expected_keywords:
            assert not is_hallucination(response_text, expected_keywords), f"Possible hallucination in: {response_text}"
        else:
            assert response_text.strip(), "Empty response received"

    except Exception as e:
        logging.exception(f"Test case failed: {prompt}")
        assert False, f"Exception occurred during test: {e}"
