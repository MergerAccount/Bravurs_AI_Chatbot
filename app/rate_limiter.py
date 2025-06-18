import time
import logging
import redis
import os
from app.config import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD, REDIS_USER

try:
    r = redis.StrictRedis(
        host=REDIS_HOST,
        port=int(REDIS_PORT),
        db=int(REDIS_DB),
        username=REDIS_USER,
        password=REDIS_PASSWORD,
        decode_responses=True,
        ssl=False,
        socket_connect_timeout=5,  # seconds
        socket_timeout=5,         # seconds
        retry_on_timeout=True
    )

    r.ping()
    print(f"Redis Connection Status: Successfully connected to Redis :)")
    logging.info("Successfully connected to Redis for rate limiting using environment variables.")
except redis.exceptions.ConnectionError as e:
    logging.error(f"Could not connect to Redis for rate limiting. "
                  f"Check REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD in your environment/config. "
                  f"Error: {e}")
    print(f"Redis Connection Status: ERROR - Could not connect to Redis: {e}")
    raise Exception("Redis connection failed for rate limiting. Please check your Redis configuration.")

# Rate limit configuration
SESSION_MAX_REQUESTS = 15
SESSION_WINDOW_SECONDS = 3600

IP_MAX_REQUESTS = 30000
IP_WINDOW_SECONDS = 60

FINGERPRINT_MAX_REQUESTS = 10
FINGERPRINT_WINDOW_SECONDS = 3600


def check_session_rate_limit(session_id: str) -> tuple[bool, int, bool]:
    key = f"rate_limit:session:{session_id}"
    count = r.incr(key)

    if count == 1:
        r.expire(key, SESSION_WINDOW_SECONDS)

    logging.info(f"Session {session_id} current request count: {count}")

    limit = int(r.hget(f"rate_limit:meta:{session_id}", "limit") or SESSION_MAX_REQUESTS)
    if count >= int(limit * 0.9):
        return True, 0, True  # allowed, no retry, captcha required

    if count > limit:
        remaining_time = r.ttl(key)
        return False, max(0, remaining_time), False

    return True, 0, False


def mark_captcha_solved(session_id: str) -> int:
    meta_key = f"rate_limit:meta:{session_id}"
    r.hset(meta_key, mapping={"limit": SESSION_MAX_REQUESTS})
    r.set(f"rate_limit:session:{session_id}", 0, ex=SESSION_WINDOW_SECONDS)
    logging.info(f"CAPTCHA solved for session {session_id}. Limit reset to: {SESSION_MAX_REQUESTS}")
    return SESSION_MAX_REQUESTS


def get_session_rate_status(session_id: str) -> dict:
    meta_key = f"rate_limit:meta:{session_id}"
    limit = int(r.hget(meta_key, "limit") or SESSION_MAX_REQUESTS)
    count = int(r.get(f"rate_limit:session:{session_id}") or 0)
    return {
        "success": True,
        "count": count,
        "limit": limit,
        "captcha_required": count >= int(limit * 0.9)
    }


def check_ip_rate_limit(user_ip: str) -> tuple[bool, int]:
    key = f"rate_limit:ip:{user_ip}"
    count = r.incr(key)

    if count == 1:
        r.expire(key, IP_WINDOW_SECONDS)

    logging.info(f"IP {user_ip} current request count: {count}")

    if count > IP_MAX_REQUESTS:
        remaining_time = r.ttl(key)
        return False, max(0, remaining_time)
    return True, 0


def reset_rate_limits():
    logging.warning("Resetting Redis-based rate limits. For production, rely on natural key expiration.")
    pass


def check_fingerprint_rate_limit(fingerprint: str) -> tuple[bool, int, bool]:
    key = f"rate_limit:fingerprint:{fingerprint}"
    count = r.incr(key)
    if count == 1:
        r.expire(key, FINGERPRINT_WINDOW_SECONDS)
    logging.info(f"Fingerprint {fingerprint} current request count: {count}")
    limit = FINGERPRINT_MAX_REQUESTS
    if count >= int(limit * 0.9):
        return True, 0, True  # allowed, no retry, captcha required
    if count > limit:
        remaining_time = r.ttl(key)
        return False, max(0, remaining_time), False
    return True, 0, False


def mark_captcha_solved_fingerprint(fingerprint: str) -> int:
    key = f"rate_limit:fingerprint:{fingerprint}"
    r.set(key, 0, ex=FINGERPRINT_WINDOW_SECONDS)
    logging.info(f"CAPTCHA solved for fingerprint {fingerprint}. Limit reset to: {FINGERPRINT_MAX_REQUESTS}")
    return FINGERPRINT_MAX_REQUESTS


def get_fingerprint_rate_status(fingerprint: str) -> dict:
    key = f"rate_limit:fingerprint:{fingerprint}"
    limit = FINGERPRINT_MAX_REQUESTS
    count = int(r.get(key) or 0)
    return {
        "success": True,
        "count": count,
        "limit": limit,
        "captcha_required": count >= int(limit * 0.9)
    }
