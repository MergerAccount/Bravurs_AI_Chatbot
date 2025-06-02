# app/rate_limiter.py
import time
import logging
from collections import defaultdict

# In-memory stores for rate limits
# IMPORTANT: For production, these should be replaced with a persistent,
# shared store like Redis or a database table to ensure limits
# are maintained across application restarts or multiple instances.
session_request_counts = defaultdict(lambda: {'count': 0, 'last_reset': time.time()})
ip_request_counts = defaultdict(lambda: {'count': 0, 'last_reset': time.time()})

# --- Configuration for Rate Limits ---
# === ADJUST THESE VALUES FOR TESTING OR PRODUCTION ===
# For TESTING: Set these to low numbers (e.g., SESSION_MAX_REQUESTS = 1, IP_MAX_REQUESTS = 2)
# to quickly trigger limits in your tests and reduce the number of requests made.
#
# For PRODUCTION: Set these to your desired real-world limits (e.g., 50 and 100).
# REMEMBER TO CHANGE THEM BACK BEFORE DEPLOYMENT!
SESSION_MAX_REQUESTS = 8      # Max requests per session (set to 1 for quick test failure)
SESSION_WINDOW_SECONDS = 120   # 1 hour

IP_MAX_REQUESTS = 8            # Max requests per IP (set to 2 for quick test failure)
IP_WINDOW_SECONDS = 60          # 1 minute
# =====================================================

# --- Rate Limit Functions ---

def check_session_rate_limit(session_id: int) -> tuple[bool, int]:
    """
    Checks if a session has exceeded its request limit.
    Returns (True, 0) if allowed, (False, remaining_time) if denied.
    """
    current_time = time.time()
    session_data = session_request_counts[session_id]

    # Reset count if window has passed
    if current_time - session_data['last_reset'] > SESSION_WINDOW_SECONDS:
        session_data['count'] = 0
        session_data['last_reset'] = current_time

    session_data['count'] += 1
    logging.info(f"Session {session_id} current count: {session_data['count']}") # Added logging

    if session_data['count'] > SESSION_MAX_REQUESTS:
        remaining_time = SESSION_WINDOW_SECONDS - (current_time - session_data['last_reset'])
        logging.warning(f"Session {session_id} hit rate limit. Retry-After: {int(remaining_time)}s")
        return False, max(0, int(remaining_time)) # Return remaining time in seconds
    return True, 0

def check_ip_rate_limit(user_ip: str) -> tuple[bool, int]:
    """
    Checks if an IP address has exceeded its request limit.
    Returns (True, 0) if allowed, (False, remaining_time) if denied.
    """
    current_time = time.time()
    ip_data = ip_request_counts[user_ip]

    # Reset count if window has passed
    if current_time - ip_data['last_reset'] > IP_WINDOW_SECONDS:
        ip_data['count'] = 0
        ip_data['last_reset'] = current_time

    ip_data['count'] += 1
    logging.info(f"IP {user_ip} current count: {ip_data['count']}") # Added logging

    if ip_data['count'] > IP_MAX_REQUESTS:
        remaining_time = IP_WINDOW_SECONDS - (current_time - ip_data['last_reset'])
        logging.warning(f"IP {user_ip} hit rate limit. Retry-After: {int(remaining_time)}s")
        return False, max(0, int(remaining_time))
    return True, 0

def reset_rate_limits():
    """Resets all in-memory rate limit counters.
    ONLY USE FOR TESTING PURPOSES.
    """
    global session_request_counts
    global ip_request_counts
    session_request_counts = defaultdict(lambda: {'count': 0, 'last_reset': time.time()})
    ip_request_counts = defaultdict(lambda: {'count': 0, 'last_reset': time.time()})
    logging.info("Rate limiters reset for testing.")