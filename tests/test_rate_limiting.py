# tests/test_rate_limiting.py
import pytest
import time
from app import create_app
from app.rate_limiter import reset_rate_limits # Import the new reset function

@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    # Reset rate limits for a clean slate before each test
    reset_rate_limits()
    with app.test_client() as client:
        yield client

def test_ip_rate_limit_exceeded(client):
    # Simulate hitting the IP limit with fewer requests for testing
    # IP_MAX_REQUESTS is 100 in app/rate_limiter.py.
    # We will make 5 requests to trigger the limit in the test, assuming the test
    # environment's 'IP_MAX_REQUESTS' is effectively 4 or less for this test scenario.
    # Note: For robust testing, you might mock IP_MAX_REQUESTS from app/rate_limiter.py.
    # For now, we are just triggering the limit with fewer actual requests.
    for i in range(5): # This number can be small, e.g., 5 or 10
        response = client.post('/api/v1/session/create')
        # Consume the response data to ensure the context is properly closed
        _ = response.data # Read the data
        time.sleep(0.01) # Small delay to allow context to settle
    assert response.status_code == 429
    assert 'Retry-After' in response.headers

def test_session_rate_limit_exceeded(client):
    # First, create a session
    session_response = client.post('/api/v1/session/create')
    session_id = session_response.json['session_id']
    _ = session_response.data # Consume response

    # Simulate hitting the session limit with fewer requests for testing
    # SESSION_MAX_REQUESTS is 50 in app/rate_limiter.py.
    # We will make 3 requests to trigger the limit in the test.
    for i in range(3): # This number can be small, e.g., 3 or 5
        response = client.post('/api/v1/chat', data={'user_input': 'test', 'session_id': session_id})
        # Consume the response data to ensure the context is properly closed
        _ = response.data # Read the data
        time.sleep(0.01) # Small delay to allow context to settle
    assert response.status_code == 429
    assert 'Retry-After' in response.headers

def test_input_length_limit(client):
    long_input = 'a' * 1001 # MAX_INPUT_CHARS + 1 (assuming 1000 MAX_INPUT_CHARS)
    response = client.post('/api/v1/chat', data={'user_input': long_input, 'session_id': '1'}) # Use any session_id
    _ = response.data # Consume response
    assert response.status_code == 400
    assert 'Your message is too long' in response.json['error']

# Add tests for normal behavior (within limits)
def test_normal_chat_request(client):
    session_response = client.post('/api/v1/session/create')
    session_id = session_response.json['session_id']
    _ = session_response.data # Consume response

    response = client.post('/api/v1/chat', data={'user_input': 'Hello', 'session_id': session_id})
    _ = response.data # Consume response
    assert response.status_code == 200
    # Further assertions to check the content of the streamed response, if applicable