import os
import psycopg2
from openai import OpenAI
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# PostgreSQL connection
conn = psycopg2.connect(
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD")
)
cursor = conn.cursor()

# Select all rows with null embedding
cursor.execute("SELECT id, title, content FROM bravur_information WHERE embedding IS NULL;")
rows = cursor.fetchall()

print(f"Found {len(rows)} rows to embed.")

# Loop and embed
for row_id, title, content in rows:
    full_text = f"{title.strip()}\n{content.strip()}"
    try:
        response = client.embeddings.create(
            input=full_text,
            model="text-embedding-3-large"
        )
        embedding = response.data[0].embedding
        cursor.execute(
            "UPDATE bravur_information SET embedding = %s WHERE id = %s;",
            (embedding, row_id)
        )
        print(f"Embedded row {row_id}")
    except Exception as e:
        print(f"Failed embedding row {row_id}: {e}")

# Save and close
conn.commit()
cursor.close()
conn.close()
print("Done updating all embeddings.")
