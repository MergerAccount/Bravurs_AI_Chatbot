import psycopg2
import logging
from datetime import datetime
from app.config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, OPENAI_API_KEY
from openai import OpenAI

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
            password=DB_PASSWORD
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
        cursor.execute("SELECT id, category, title, content FROM bravur_information;")
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
    conn = get_db_connection()
    if conn is None:
        logging.error("Failed to get DB connection in create_chat_session")
        return None

    try:
        cursor = conn.cursor()
        now = datetime.now()
        cursor.execute(
            "INSERT INTO chat_session (timestamp, voice_enabled, duration_minutes) VALUES (%s, %s, %s) RETURNING session_id",
            (now, False, 0)
        )
        session_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()
        logging.info(f"Created new chat session: {session_id}")
        return session_id
    except Exception as e:
        logging.error(f"Error creating chat session: {e}")
        if conn:
            conn.close()
        return None

# Store a user/bot message in the message table
def store_message(session_id, content, message_type="user"):
    if not session_id:
        logging.error("No session ID")
        return False

    try:
        session_id = int(session_id)
    except (ValueError, TypeError):
        logging.error(f"Invalid session ID: {session_id}")
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
    if not session_id:
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

# Call OpenAI to embed a query for semantic search
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
