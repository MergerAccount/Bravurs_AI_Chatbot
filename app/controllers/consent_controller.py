import logging
from datetime import datetime
from flask import jsonify, request
from app.database import get_db_connection


def handle_accept_consent():
    try:
        data = request.get_json()
        session_id = data.get('session_id')

        if not session_id:
            return jsonify({"success": False, "error": "No session ID provided"}), 400

        conn = get_db_connection()
        if conn is None:
            return jsonify({"success": False, "error": "Database connection failed"}), 500

        cursor = conn.cursor()

        cursor.execute("SELECT consent_id FROM consent WHERE session_id = %s", (session_id,))
        existing_consent = cursor.fetchone()

        now = datetime.now()

        if existing_consent:
            cursor.execute(
                """
                UPDATE consent 
                SET has_consent = TRUE, timestamp = %s, is_withdrawn = FALSE
                WHERE session_id = %s
                """,
                (now, session_id)
            )
        else:
            cursor.execute(
                """
                INSERT INTO consent (session_id, has_consent, timestamp, is_withdrawn)
                VALUES (%s, TRUE, %s, FALSE)
                """,
                (session_id, now)
            )

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"success": True, "message": "Consent accepted"}), 200

    except Exception as e:
        logging.error(f"Error accepting consent: {e}")
        return jsonify({"success": False, "error": "Server error"}), 500


def handle_withdraw_consent():
    try:
        data = request.get_json()
        session_id = data.get('session_id')

        if not session_id:
            return jsonify({"success": False, "error": "No session ID provided"}), 400

        conn = get_db_connection()
        if conn is None:
            return jsonify({"success": False, "error": "Database connection failed"}), 500

        cursor = conn.cursor()
        now = datetime.now()

        cursor.execute("SELECT consent_id FROM consent WHERE session_id = %s", (session_id,))
        existing_consent = cursor.fetchone()

        if existing_consent:
            cursor.execute("DELETE FROM message WHERE session_id = %s", (session_id,))
            cursor.execute("DELETE FROM feedback WHERE session_id = %s", (session_id,))

            cursor.execute(
                """
                UPDATE consent 
                SET is_withdrawn = TRUE, timestamp = %s, has_consent = FALSE
                WHERE session_id = %s
                """,
                (now, session_id)
            )

            conn.commit()
            cursor.close()
            conn.close()

            return jsonify({
                "success": True,
                "message": "Consent withdrawn and data deleted"
            }), 200
        else:
            cursor.execute(
                """
                INSERT INTO consent (session_id, has_consent, timestamp, is_withdrawn)
                VALUES (%s, FALSE, %s, TRUE)
                """,
                (session_id, now)
            )

            conn.commit()
            cursor.close()
            conn.close()

            return jsonify({
                "success": True,
                "message": "Consent withdrawal recorded"
            }), 200

    except Exception as e:
        logging.error(f"Error withdrawing consent: {e}")
        return jsonify({"success": False, "error": "Server error"}), 500


def check_consent_status(session_id):
    try:
        if not session_id:
            return {"can_proceed": False, "reason": "No session ID"}

        conn = get_db_connection()
        if conn is None:
            return {"can_proceed": False, "reason": "Database error"}

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT has_consent, is_withdrawn
            FROM consent
            WHERE session_id = %s
            """,
            (session_id,)
        )

        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result:
            has_consent, is_withdrawn = result
            can_proceed = has_consent and not is_withdrawn
            reason = None if can_proceed else "Consent not given or withdrawn"
            return {"can_proceed": can_proceed, "reason": reason}
        else:
            return {"can_proceed": False, "reason": "Consent not yet given"}

    except Exception as e:
        logging.error(f"Error checking consent: {e}")
        return {"can_proceed": False, "reason": "Server error"}


def handle_view_consent(session_id=None):
    try:
        if request.method == 'POST':
            data = request.get_json()
            session_id = data.get('session_id')

        if not session_id:
            return jsonify({"success": False, "error": "No session ID provided"}), 400

        conn = get_db_connection()
        if conn is None:
            return jsonify({"success": False, "error": "Database connection failed"}), 500

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT consent_id, has_consent, timestamp, is_withdrawn
            FROM consent
            WHERE session_id = %s
            """,
            (session_id,)
        )

        consent_result = cursor.fetchone()

        cursor.execute(
            """
            SELECT timestamp, voice_enabled, duration_minutes
            FROM chat_session
            WHERE session_id = %s
            """,
            (session_id,)
        )

        session_result = cursor.fetchone()

        cursor.execute(
            """
            SELECT message_id, content, timestamp, message_type
            FROM message
            WHERE session_id = %s
            ORDER BY timestamp
            """,
            (session_id,)
        )

        messages_result = cursor.fetchall()

        cursor.execute(
            """
            SELECT feedback_id, rating, comment, timestamp
            FROM feedback
            WHERE session_id = %s
            ORDER BY timestamp DESC
            """,
            (session_id,)
        )

        feedback_result = cursor.fetchall()

        cursor.close()
        conn.close()

        consent_data = None
        if consent_result:
            consent_id, has_consent, consent_timestamp, is_withdrawn = consent_result
            consent_data = {
                "consent_id": consent_id,
                "has_consent": has_consent,
                "timestamp": consent_timestamp.isoformat() if consent_timestamp else None,
                "is_withdrawn": is_withdrawn
            }

        session_data = None
        if session_result:
            session_timestamp, voice_enabled, duration_minutes = session_result
            session_data = {
                "timestamp": session_timestamp.isoformat() if session_timestamp else None,
                "voice_enabled": voice_enabled,
                "duration_minutes": duration_minutes
            }

        messages_data = []
        if messages_result:
            for msg in messages_result:
                msg_id, content, msg_timestamp, msg_type = msg
                messages_data.append({
                    "message_id": msg_id,
                    "content": content,
                    "timestamp": msg_timestamp.isoformat() if msg_timestamp else None,
                    "type": msg_type
                })

        feedback_data = []
        if feedback_result:
            for fb in feedback_result:
                fb_id, rating, comment, fb_timestamp = fb
                feedback_data.append({
                    "feedback_id": fb_id,
                    "rating": rating,
                    "comment": comment,
                    "timestamp": fb_timestamp.isoformat() if fb_timestamp else None
                })

        return jsonify({
            "success": True,
            "session_id": session_id,
            "consent": consent_data,
            "session": session_data,
            "messages": messages_data,
            "feedback": feedback_data
        }), 200

    except Exception as e:
        logging.error(f"Error viewing consent: {e}")
        return jsonify({"success": False, "error": f"Server error: {str(e)}"}), 500