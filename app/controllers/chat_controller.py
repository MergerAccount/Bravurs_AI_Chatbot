# app/controllers/chat_controller.py

from flask import request, jsonify, Response, stream_with_context
import logging
from typing import Tuple, Dict, Any, Generator, Optional, Union
from app.chatbot import company_info_handler_streaming
from app.database import create_chat_session, store_message, is_session_active
from app.rate_limiter import (
    check_session_rate_limit, get_session_rate_status,
    check_fingerprint_rate_limit, get_fingerprint_rate_status,
    check_ip_rate_limit, r as redis_client
)
from app.utils import get_client_ip

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def handle_chat() -> Tuple[Dict[str, Any], int]:
    """
    Handle chat requests from both existing frontend and WordPress.
    
    Supports:
    - JSON requests (API)
    - Form data requests (WordPress)
    - Streaming responses (frontend)
    - Rate limiting with fingerprint/session/IP tracking
    - CAPTCHA verification
    
    Returns:
        Tuple[Dict[str, Any], int]: Response data and HTTP status code
    """
    # Debug logging
    logger.debug("=== CHAT REQUEST DEBUG ===")
    logger.debug(f"Content-Type: {request.content_type}")
    logger.debug(f"Method: {request.method}")
    logger.debug(f"Form data: {dict(request.form)}")
    logger.debug(f"Headers: {dict(request.headers)}")
    
    try:
        json_data = request.get_json(silent=True)
        logger.debug(f"JSON data: {json_data}")
    except Exception as e:
        logger.error(f"JSON parse error: {e}")
        json_data = None

    # Extract request data
    user_input, session_id, fingerprint, language, request_type = _extract_request_data(json_data)
    
    # Validate user input
    if not user_input:
        error_response = "Message is required" if request_type == "wordpress" else "User input is required"
        return jsonify({"error": error_response}), 400

    # Handle session creation/validation
    session_id = _handle_session(session_id)
    if isinstance(session_id, tuple):  # Error response
        return session_id

    # Check rate limits
    rate_check = _check_rate_limits(session_id, fingerprint)
    if isinstance(rate_check, tuple):  # Rate limit error response
        return rate_check

    # Validate input length
    if len(user_input) > 1000:
        logger.warning(f"User input too long for session {session_id}")
        return jsonify({
            "error": "Your message is too long. Please keep it under 1000 characters."
        }), 400

    # Store user message
    store_message(session_id, user_input, "user")

    # Handle response based on request type
    if request_type in ["wordpress", "json"]:
        return handle_wordpress_chat(user_input, session_id, language)
    return handle_streaming_chat(user_input, session_id, language)

def _extract_request_data(json_data: Optional[Dict]) -> Tuple[str, str, str, str, str]:
    """
    Extract and validate request data from different sources.
    
    Args:
        json_data: Optional JSON data from request
        
    Returns:
        Tuple containing (user_input, session_id, fingerprint, language, request_type)
    """
    if request.content_type and 'application/json' in request.content_type and json_data:
        user_input = json_data.get("message") or json_data.get("user_input")
        session_id = json_data.get("session_id")
        fingerprint = json_data.get("fingerprint")
        language = json_data.get("language", "nl-NL")
        request_type = "json"
    else:
        user_input = request.form.get("user_input")
        session_id = request.form.get("session_id")
        fingerprint = request.form.get("fingerprint")
        language = request.form.get("language", "nl-NL")
        user_agent = request.headers.get('User-Agent', '')
        referrer = request.headers.get('Referer', '')
        request_type = "wordpress" if 'WordPress' in user_agent or 'bravurwp.local' in referrer else "form"

    # Check header for fingerprint
    if not fingerprint:
        fingerprint = request.headers.get("X-Client-Fingerprint")

    logger.debug(f"Request type: {request_type}")
    logger.debug(f"User input: {user_input}")
    logger.debug(f"Session ID: {session_id}")
    logger.debug(f"Language: {language}")
    logger.debug(f"Fingerprint: {fingerprint}")

    return user_input, session_id, fingerprint, language, request_type

def _handle_session(session_id: Optional[str]) -> Union[int, Tuple[Dict[str, Any], int]]:
    """
    Handle session creation and validation.
    
    Args:
        session_id: Optional session ID from request
        
    Returns:
        Either validated session ID (int) or error response tuple
    """
    if not session_id or session_id in ("None", "null"):
        session_id = create_chat_session()
        if not session_id:
            return jsonify({"error": "Sorry, I'm having trouble with your session. Please try again."}), 500

    try:
        session_id = int(session_id)
    except (ValueError, TypeError):
        session_id = create_chat_session()
        if not session_id:
            return jsonify({"error": "Sorry, I'm having trouble with your session. Please try again."}), 500

    if not is_session_active(session_id):
        logger.warning(f"Attempted to use inactive session: {session_id}")
        return jsonify({
            "error": "This session is no longer active. Please start a new conversation.",
            "session_expired": True,
            "new_session_required": True
        }), 403

    return session_id

def _check_rate_limits(session_id: int, fingerprint: Optional[str]) -> Optional[Tuple[Dict[str, Any], int]]:
    """
    Check rate limits for the request.
    
    Args:
        session_id: Validated session ID
        fingerprint: Optional client fingerprint
        
    Returns:
        None if rate limits pass, or error response tuple if limits exceeded
    """
    allowed = True
    retry_after = 0
    captcha_required = False
    rate_status = None

    if fingerprint:
        allowed, retry_after, captcha_required = check_fingerprint_rate_limit(fingerprint)
        rate_status = get_fingerprint_rate_status(fingerprint)
        rate_id = fingerprint
        rate_type = 'fingerprint'
        count = redis_client.get(f"rate_limit:fingerprint:{fingerprint}") or 0
        logger.info(f"🔢 Fingerprint {fingerprint} has made {count} requests so far.")
    elif session_id:
        allowed, retry_after, captcha_required = check_session_rate_limit(session_id)
        rate_status = get_session_rate_status(session_id)
        rate_id = session_id
        rate_type = 'session'
        count = redis_client.get(f"rate_limit:session:{session_id}") or 0
        logger.info(f"🔢 Session {session_id} has made {count} requests so far.")
    else:
        user_ip = get_client_ip()
        allowed, retry_after = check_ip_rate_limit(user_ip)
        captcha_required = False
        rate_status = None
        rate_id = user_ip
        rate_type = 'ip'

    if not allowed:
        return jsonify({
            "error": f"Too many requests for this {rate_type}. Please try again in {retry_after} seconds."
        }), 429, {'Retry-After': str(retry_after)}

    if captcha_required:
        return jsonify({
            "error": "CAPTCHA required before continuing",
            "captcha_required": True,
            "count": rate_status['count'] if rate_status else None,
            "limit": rate_status['limit'] if rate_status else None,
            "rate_type": rate_type
        }), 403

    return None

def handle_wordpress_chat(user_input: str, session_id: int, language: str) -> Tuple[Dict[str, Any], int]:
    """
    Handle WordPress chat requests with complete JSON response.
    
    Args:
        user_input: User's message
        session_id: Validated session ID
        language: Requested language code
        
    Returns:
        Tuple containing response data and HTTP status code
    """
    try:
        logger.info(f"Processing WordPress chat for session {session_id}")
        full_reply = ""
        for chunk in company_info_handler_streaming(user_input, session_id, language):
            full_reply += chunk
            
        if full_reply.strip():
            store_message(session_id, full_reply.strip(), "bot")
            
        logger.debug(f"WordPress chat response: {full_reply[:100]}...")
        return jsonify({
            "response": full_reply.strip() or "Sorry, I couldn't generate a response.",
            "session_id": session_id,
            "language": language,
            "status": "success"
        })
    except Exception as e:
        logger.error(f"Error in WordPress chat: {e}")
        return jsonify({"error": "Internal server error"}), 500

def handle_streaming_chat(user_input: str, session_id: int, language: str) -> Response:
    """
    Handle streaming chat requests for the frontend.
    
    Args:
        user_input: User's message
        session_id: Validated session ID
        language: Requested language code
        
    Returns:
        Flask Response object with streaming content
    """
    def generate() -> Generator[str, None, None]:
        full_reply = ""
        try:
            for chunk in company_info_handler_streaming(user_input, session_id, language):
                full_reply += chunk
                yield chunk
        finally:
            if full_reply.strip():
                store_message(session_id, full_reply.strip(), "bot")

    return Response(stream_with_context(generate()), mimetype="text/plain")