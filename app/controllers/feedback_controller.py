# Updated feedback_controller.py to handle both WordPress (JSON) and existing (form) requests

from flask import request, jsonify
import logging
from app.database import get_db_connection


def handle_feedback_submission():
    """
    Handle feedback submissions from both existing frontend (form data) 
    and WordPress (JSON data)
    """

    if request.content_type and 'application/json' in request.content_type:
        # WordPress JSON request
        data = request.get_json()
        if not data:
            return jsonify({"message": "No data provided"}), 400

        session_id = data.get("session_id")
        rating = data.get("rating")
        comment = data.get("comment", "")
        request_type = "wordpress"
    else:
        # Existing form data request
        session_id = request.form.get("session_id")
        rating = request.form.get("rating")
        comment = request.form.get("comment", "")
        request_type = "form"

    # Require session ID and rating
    if not session_id or not rating:
        error_msg = "Missing session ID or rating"
        if request_type == "wordpress":
            return jsonify({"message": error_msg}), 400
        else:
            return jsonify({"message": error_msg}), 400

    conn = get_db_connection()
    if conn is None:
        error_msg = "Failed to connect to DB"
        if request_type == "wordpress":
            return jsonify({"message": error_msg}), 500
        else:
            return jsonify({"message": error_msg}), 500

    try:
        cursor = conn.cursor()

        # Check if feedback already exists
        cursor.execute("SELECT feedback_id FROM feedback WHERE session_id = %s;", (session_id,))
        existing = cursor.fetchone()

        if existing:
            # Update existing feedback
            cursor.execute(
                """
                UPDATE feedback
                SET rating = %s, comment = %s, timestamp = NOW()
                WHERE session_id = %s;
                """,
                (rating, comment, session_id)
            )
            message = "Feedback updated successfully!"
        else:
            # Insert new feedback
            cursor.execute(
                """
                INSERT INTO feedback (session_id, rating, comment, timestamp)
                VALUES (%s, %s, %s, NOW());
                """,
                (session_id, rating, comment)
            )
            message = "Feedback submitted successfully!"

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"message": message})

    except Exception as e:
        logging.error(f"Feedback save failed: {e}")
        error_msg = "Failed to save feedback"
        return jsonify({"message": error_msg}), 500