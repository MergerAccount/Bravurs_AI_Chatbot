# app/controllers/history_controller.py (UPDATED CONTENT)
from flask import request, jsonify
import logging
from app.database import get_db_connection

def handle_history_fetch():
    session_id = request.args.get("session_id")

    # Check for missing, None, or "None" session
    if not session_id or session_id == "None" or session_id == "null":
        return jsonify({"messages": []})


    conn = get_db_connection()
    if conn is None:
        return jsonify({"messages": []})

    try:
        cursor = conn.cursor()

        # Query messages from database
        cursor.execute(
            """
            SELECT content, message_type
            FROM message
            WHERE session_id = %s
            ORDER BY timestamp ASC
            """,
            (session_id,)
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        # Convert to structured response
        history = [{"content": r[0], "type": r[1]} for r in rows]
        return jsonify({"messages": history})
    except Exception as e:
        logging.error(f"Failed to load message history: {e}")
        return jsonify({"messages": []})