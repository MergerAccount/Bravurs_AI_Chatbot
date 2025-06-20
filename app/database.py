# app/database.py (UPDATED CONTENT)
import psycopg2
import logging
from datetime import datetime, timedelta, timezone
from app.config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, OPENAI_API_KEY
from openai import OpenAI
import secrets

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# Get a PostgreSQL connection using config values
def get_db_connection():
    try:
        return psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            sslmode='require',
            connect_timeout=20  # Increase timeout slightly for potentially slower SSL handshake
        )
    except Exception as e:
        logging.error(f"Database connection failed: {e}")
        return None

# Fetch all Bravur company info for context injection
def fetch_relevant_info():
    conn = get_db_connection()
    if conn is None:
        return ""

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, category, title, content FROM bravur_data;")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        # Format all rows into a readable block for GPT
        formatted_data = "\n".join(
            [f"Row ID: {row_id}\nCategory: {category}\nTitle: {title}\nContent: {content}\n"
             for row_id, category, title, content in rows]
        )

        logging.info(f"Retrieved DB Data:\n{formatted_data}")
        return formatted_data
    except Exception as e:
        logging.error(f"Error fetching data: {e}")
        return ""

# Create a new chat session with default values and return session_id
def create_chat_session():
    print("DEBUG: create_chat_session() called")
    conn = get_db_connection()
    if conn is None:
        print("DEBUG: Failed to get DB connection")
        logging.error("Failed to get DB connection in create_chat_session")
        return None

    try:
        cursor = conn.cursor()
        now = datetime.now()
        print(f"DEBUG: About to insert session with timestamp: {now}")

        # Generate a unique, random string as session_id
        # Using secrets.token_urlsafe for a robust, URL-safe random string
        session_id = secrets.token_urlsafe(16)

        # Insert session with the generated session_id
        cursor.execute(
            """
            INSERT INTO chat_session (session_id, timestamp, voice_enabled, duration_minutes, is_active) 
            VALUES (%s, %s, %s, %s, %s) 
            RETURNING session_id
            """,
            (session_id, now, False, 0, True) # Explicitly set is_active
        )

        conn.commit()
        cursor.close()
        conn.close()

        print(f"DEBUG: Successfully created session_id: {session_id}")
        logging.info(f"Created new chat session: {session_id}")

        # Initialize Redis limit (session_id is treated as a string key by Redis, so this is fine)
        from app.rate_limiter import r, SESSION_MAX_REQUESTS
        meta_key = f"rate_limit:meta:{session_id}"
        if not r.hexists(meta_key, "limit"):
            r.hset(meta_key, mapping={"limit": SESSION_MAX_REQUESTS})
            print(f"DEBUG: Redis meta limit set for session {session_id} → {SESSION_MAX_REQUESTS}")

        return session_id

    except Exception as e:
        print(f"DEBUG: Exception in create_chat_session: {e}")
        logging.error(f"Error creating chat session: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return None

# Store a user/bot message in the message table
def store_message(session_id, content, message_type="user"):
    if not session_id:
        logging.error("No session ID")
        return False


    conn = get_db_connection()
    if conn is None:
        return False

    try:
        cursor = conn.cursor()
        now = datetime.now()
        cursor.execute(
            """
            INSERT INTO message (session_id, content, timestamp, message_type)
            VALUES (%s, %s, %s, %s)
            RETURNING message_id
            """,
            (session_id, content, now, message_type)
        )
        message_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()
        logging.info(f"Stored message {message_id} in session {session_id}")
        return message_id
    except Exception as e:
        logging.error(f"Failed to store message: {e}")
        if conn:
            conn.close()
        return False

# Retrieve all messages for a given session_id
def get_session_messages(session_id):
    # Handle the "None" string case
    if not session_id or session_id == "None" or session_id == "null":
        return []


    conn = get_db_connection()
    if conn is None:
        return []

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT message_id, content, timestamp, message_type
            FROM message
            WHERE session_id = %s
            ORDER BY timestamp
            """,
            (session_id,)
        )
        results = cursor.fetchall()
        cursor.close()
        conn.close()
        return results
    except Exception as e:
        logging.error(f"Failed to retrieve messages: {e}")
        if conn:
            conn.close()
        return []

# Use pgvector similarity search to find best semantic matches
def semantic_search(query_embedding, top_k=5):
    conn = get_db_connection()
    if conn is None:
        logging.error("No DB connection for semantic search")
        return []

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT entry_id, title, content, content_embedding <=> %s::vector AS similarity
            FROM bravur_data
            ORDER BY similarity ASC
            LIMIT %s;
            """,
            (query_embedding, top_k)
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows
    except Exception as e:
        logging.error(f"Semantic search failed: {e}")
        return []

def embed_query(query):
    try:
        response = client.embeddings.create(
            input=query,
            model="text-embedding-3-large"
        )
        return response.data[0].embedding
    except Exception as e:
        logging.error(f"Error embedding query: {e}")
        return None

# Run both semantic and fallback keyword search if needed
def hybrid_search(query, top_k=5):
    embedding = embed_query(query)
    if embedding:
        results = semantic_search(embedding, top_k=top_k)
        if results:
            return results

    # Fallback to full-text search using tsvector
    conn = get_db_connection()
    if conn is None:
        logging.error("No DB connection for fallback search")
        return []

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT entry_id, title, content, 1.0 AS similarity
            FROM bravur_data
            WHERE to_tsvector('english', content) @@ plainto_tsquery(%s)
            LIMIT %s;
            """,
            (query, top_k)
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows
    except Exception as e:
        logging.error(f"Fallback search failed: {e}")
        return []

# Update rows in bravur_data that are missing vector embeddings
def update_pending_embeddings():
    conn = get_db_connection()
    if conn is None:
        logging.error("No DB connection for embedding update")
        return

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT entry_id, title, content FROM bravur_data WHERE needs_embedding = TRUE;")
        rows = cursor.fetchall()

        for entry_id, title, content in rows:
            if not content:
                continue

            full_text = f"{title.strip() if title else ''}\n{content.strip()}"

            try:
                response = client.embeddings.create(
                    input=full_text,
                    model="text-embedding-3-large"
                )
                embedding = response.data[0].embedding

                cursor.execute("""
                    UPDATE bravur_data
                    SET content_embedding = %s,
                        last_updated_embedding = NOW(),
                        needs_embedding = FALSE
                    WHERE entry_id = %s;
                """, (embedding, entry_id))

                logging.info(f"Updated embedding for entry_id {entry_id}")

            except Exception as e:
                logging.error(f"Failed to embed entry_id {entry_id}: {e}")

        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logging.error(f"Error during embedding update: {e}")

def is_session_active(session_id):
    """
    Check if a session exists and is active
    Returns: True if active, False if inactive/doesn't exist
    """
    conn = get_db_connection()
    if conn is None:
        logging.error("Failed to get DB connection in is_session_active")
        return False

    try:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT is_active FROM chat_session WHERE session_id = %s",
            (session_id,)
        )

        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result is None:
            # Session doesn't exist
            logging.warning(f"Session {session_id} does not exist")
            return False

        is_active = result[0]
        if not is_active:
            logging.warning(f"Session {session_id} is inactive")

        return is_active

    except Exception as e:
        logging.error(f"Error checking session activity: {e}")
        if conn:
            conn.close()
        return False

def is_session_expired(session_id, expiration_hours=72):
    """
    Returns True if the session is older than `expiration_hours` or doesn't exist.
    """
    conn = get_db_connection()
    if conn is None:
        logging.error("Failed to get DB connection in is_session_expired")
        return True

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT timestamp FROM chat_session WHERE session_id = %s", (session_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if row is None:
            return True

        session_time = row[0]

        # ✅ Make it timezone-aware if it isn't already
        if session_time.tzinfo is None:
            session_time = session_time.replace(tzinfo=timezone.utc)

        expiration_time = session_time + timedelta(days=3)
        return datetime.now(timezone.utc) > expiration_time

    except Exception as e:
        print(f"Error checking session expiration: {e}")
        return True

def is_session_valid(session_id):
    if is_session_expired(session_id):
        return False
    return is_session_active(session_id)