import logging
from datetime import datetime
from flask import jsonify, request
from app.database import get_db_connection


def handle_accept_consent():
    try:
        # Handle both JSON and form data from WordPress
        if request.content_type and 'application/json' in request.content_type:
            data = request.get_json()
            session_id = data.get('session_id')
        else:
            # WordPress sends form data
            session_id = request.form.get('session_id')

        print(f"Accept consent for session: {session_id}")

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

        print(f"Consent accepted successfully for session {session_id}")
        return jsonify({"success": True, "message": "Consent accepted"}), 200

    except Exception as e:
        logging.error(f"Error accepting consent: {e}")
        print(f"Error accepting consent: {e}")
        return jsonify({"success": False, "error": "Server error"}), 500


def handle_withdraw_consent():
    try:
        # Handle both JSON and form data from WordPress
        if request.content_type and 'application/json' in request.content_type:
            data = request.get_json()
            session_id = data.get('session_id')
        else:
            # WordPress sends form data
            session_id = request.form.get('session_id')

        print(f"Withdraw consent for session: {session_id}")

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

            print(f"Consent withdrawn successfully for session {session_id}")
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

            print(f"Consent withdrawal recorded for session {session_id}")
            return jsonify({
                "success": True,
                "message": "Consent withdrawal recorded"
            }), 200

    except Exception as e:
        logging.error(f"Error withdrawing consent: {e}")
        print(f"Error withdrawing consent: {e}")
        return jsonify({"success": False, "error": "Server error"}), 500


def check_consent_status(session_id):
    try:
        print(f"Checking consent status for session: {session_id}")

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
            print(f"Consent status: can_proceed={can_proceed}, reason={reason}")
            return {"can_proceed": can_proceed, "reason": reason}
        else:
            print("No consent record found")
            return {"can_proceed": False, "reason": "Consent not yet given"}

    except Exception as e:
        logging.error(f"Error checking consent: {e}")
        print(f"Error checking consent: {e}")
        return {"can_proceed": False, "reason": "Server error"}