import pytest
from datetime import datetime, timedelta, timezone
import psycopg2
from app.database import create_chat_session, is_session_expired
from app.config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
from app.database import is_session_valid, get_db_connection;

def manually_set_session_timestamp(session_id, fake_time):
    conn = get_db_connection()
    if conn is None:
        raise Exception("DB connection failed")
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE chat_session SET timestamp = %s WHERE session_id = %s",
            (fake_time, session_id)
        )
        conn.commit()
        cursor.close()
    finally:
        conn.close()

def test_session_expired_after_3_days():
    # Create a new session
    session_id = create_chat_session()
    assert session_id is not None

    # Simulate that the session is older than 3 days
    old_time = datetime.now(timezone.utc) - timedelta(days=3, minutes=1)  # 3 days + 1 minute
    manually_set_session_timestamp(session_id, old_time)

    # Assert it is expired
    assert is_session_valid(session_id) is False
def test_session_not_expired_within_3_days():
    session_id = create_chat_session()
    assert session_id is not None

    recent_time = datetime.now(timezone.utc) - timedelta(days=2, hours=23)
    manually_set_session_timestamp(session_id, recent_time)

    assert is_session_valid(session_id) is True


def test_session_expired_invalid_id():
    assert is_session_valid("invalid id") is False

