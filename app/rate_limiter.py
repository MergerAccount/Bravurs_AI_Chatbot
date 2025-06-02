import time
import logging
import redis
import os

REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT'))
REDIS_DB = int(os.getenv('REDIS_DB'))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD')

try:
    r = redis.StrictRedis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD
    )
    # test Redis connection. If ping fails > connection error handle.
    r.ping()
    # show error handle log.
    print(f"Redis Connection Status: Successfully connected to Redis :)")
    logging.info("Successfully connected to Redis for rate limiting using environment variables.")
except redis.exceptions.ConnectionError as e:
    # log an error if Redis connection fails and raise an exception to prevent
    # the application from starting without a critical dependency.
    logging.error(f"Could not connect to Redis for rate limiting. "
                  f"Check REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD in your environment/config. "
                  f"Error: {e}")
    # print the error for immediate visibility if logging is suppressed
    print(f"Redis Connection Status: ERROR - Could not connect to Redis: {e}")
    raise Exception("Redis connection failed for rate limiting. Please check your Redis configuration.")


# rate limit configuration
SESSION_MAX_REQUESTS = 50       # Max requests allowed per unique session ID
SESSION_WINDOW_SECONDS = 3600   # Time window for session limits (1 hour)

IP_MAX_REQUESTS = 500           # Max requests allowed per unique IP address
IP_WINDOW_SECONDS = 60          # Time window for IP limits (1 minute)


# Rate Limit Functions

def check_session_rate_limit(session_id: str) -> tuple[bool, int]:
    """
    Checks if a given session ID has exceeded its request limit using Redis.
    The rate limit is enforced per session within a defined time window.

    Returns:
        tuple[bool, int]: A tuple where:
            - True if the request is allowed, False otherwise.
            - The remaining time in seconds until the limit resets (0 if allowed).
    """
    #  unique Redis key for this session's rate limit counter.
    key = f"rate_limit:session:{session_id}"

    # auto increment the counter for this key.
    # if the key does not exist, it's created with value 0 then incremented to 1.
    count = r.incr(key)

    # If this is the first request in the current window (count is 1),
    # set an expiration time for the key. This ensures the counter
    # automatically resets after SESSION_WINDOW_SECONDS.
    if count == 1:
        r.expire(key, SESSION_WINDOW_SECONDS)

    logging.info(f"Session {session_id} current request count: {count}")

    # Check if the current request count exceeds the maximum allowed.
    if count > SESSION_MAX_REQUESTS:
        # If the limit is exceeded, get the remaining time until the key expires.
        remaining_time = r.ttl(key)
        # Ensure remaining_time is not negative (can happen if key expired just before ttl call)
        if remaining_time < 0:
            remaining_time = 0
        logging.warning(f"Session {session_id} hit rate limit. Retry-After: {int(remaining_time)}s")
        return False, max(0, int(remaining_time)) # Return False and the retry-after time
    return True, 0 # Return True if the request is allowed

def check_ip_rate_limit(user_ip: str) -> tuple[bool, int]:
    """
    Checks if a given IP address has exceeded its request limit using Redis.
    This provides a broad protection against abuse from a single IP source.

    Args:
        user_ip (str): The IP address of the user.

    Returns:
        tuple[bool, int]: A tuple where:
            - True if the request is allowed, False otherwise.
            - The remaining time in seconds until the limit resets (0 if allowed).
    """
    # unique Redis key for this IP's rate limit counter.
    key = f"rate_limit:ip:{user_ip}"

    # Atomically increment the counter for this key.
    count = r.incr(key)

    # If this is the first request in the current window (count is 1),
    # set an expiration time for the key.
    if count == 1:
        r.expire(key, IP_WINDOW_SECONDS)

    logging.info(f"IP {user_ip} current request count: {count}")

    # Check if the current request count exceeds the maximum allowed.
    if count > IP_MAX_REQUESTS:
        # If the limit is exceeded, get the remaining time until the key expires.
        remaining_time = r.ttl(key)
        if remaining_time < 0:
            remaining_time = 0
        logging.warning(f"IP {user_ip} hit rate limit. Retry-After: {int(remaining_time)}s")
        return False, max(0, int(remaining_time))
    return True, 0

def reset_rate_limits():
    """
    Resets rate limits.
    rate limits are automatically reset when their keys expire.
    This function is primarily a placeholder for testing scenarios where
    a manual reset might be desired (e.g., flushing the Redis database).
    In a production environment, you typically rely on the natural expiration
    of Redis keys.
    """
    logging.warning("Resetting Redis-based rate limits. For production, rely on natural key expiration.")
    # For testing,  might use r.flushdb() here, but be extremely cautious
    # as it clears ALL data from the selected Redis database.
    pass # Let Redis keys expire naturally

