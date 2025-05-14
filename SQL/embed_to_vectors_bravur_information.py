import os
import psycopg2
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables from .env
load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# PostgreSQL Connection
conn = psycopg2.connect(
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD")
)
cursor = conn.cursor()

print("Connected to the database...")

# Fetch only rows that need embedding
cursor.execute("""
    SELECT entry_id, title, content
    FROM bravur_data
    WHERE needs_embedding = TRUE;
""")

rows = cursor.fetchall()
print(f"Found {len(rows)} rows needing embedding update...")

for entry_id, title, content in rows:
    if not content:
        print(f"Skipping empty content for entry_id {entry_id}")
        continue

    full_text = f"{title.strip() if title else ''}\n{content.strip()}"
    try:
        response = client.embeddings.create(
            input=full_text,
            model="text-embedding-3-large"
        )
        embedding = response.data[0].embedding

        #Store the embedding and mark as processed
        cursor.execute("""
            UPDATE bravur_data
            SET content_embedding = %s,
                last_updated_embedding = NOW(),
                needs_embedding = FALSE
            WHERE entry_id = %s;
        """, (embedding, entry_id))

        print(f"Embedded entry_id {entry_id}")

    except Exception as e:
        print(f"Failed embedding entry_id {entry_id}: {e}")

# Commit all changes
conn.commit()
cursor.close()
conn.close()
print("Done. All embeddings updated.")