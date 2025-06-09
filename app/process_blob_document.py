import os
import io
import logging
import fitz  # PyMuPDF
import docx
import openai
import psycopg2
from azure.storage.blob import BlobServiceClient
from app.config import (
    OPENAI_API_KEY, AZURE_STORAGE_CONNECTION_STRING,
    DB_HOST, DB_NAME, DB_USER, DB_PASSWORD
)


# === CONFIG ===
CONTAINER_NAME = "document-uploads"  # e.g., "documents"
TOP_K_CHUNKS = 5
CHUNK_SIZE = 500
OVERLAP = 50

# === SETUP CLIENTS ===
openai.api_key = OPENAI_API_KEY
blob_service = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)

# === HELPERS ===
def extract_text(file_bytes: bytes, filename: str) -> str:
    ext = filename.lower().split(".")[-1]
    if ext == "pdf":
        return extract_text_pdf(file_bytes)
    elif ext == "docx":
        return extract_text_docx(file_bytes)
    elif ext == "txt":
        return file_bytes.decode("utf-8", errors="ignore")
    else:
        raise ValueError(f"Unsupported file type: {ext}")

def extract_text_pdf(file_bytes: bytes) -> str:
    text = ""
    with fitz.open(stream=file_bytes, filetype="pdf") as doc:
        for page in doc:
            text += page.get_text()
    return text

def extract_text_docx(file_bytes: bytes) -> str:
    text = ""
    doc = docx.Document(io.BytesIO(file_bytes))
    for para in doc.paragraphs:
        text += para.text + "\n"
    return text

def chunk_text(text: str, size=CHUNK_SIZE, overlap=OVERLAP):
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i:i+size])
        chunks.append(chunk)
        i += size - overlap
    return chunks

def embed_chunk(text: str) -> list[float]:
    try:
        response = openai.embeddings.create(
            input=text,
            model="text-embedding-3-large"
        )
        return response.data[0].embedding
    except Exception as e:
        logging.error(f"Embedding failed: {e}")
        return []

def get_pg_conn():
    return psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )

def insert_chunks_into_db(chunks, embeddings, source_document):
    conn = get_pg_conn()
    try:
        with conn.cursor() as cur:
            for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
                if not emb:
                    logging.warning(f"Skipping empty embedding for chunk {i}")
                    continue
                logging.info(f"Inserting chunk {i} from {source_document} with length {len(chunk)}")
                cur.execute("""
                    INSERT INTO document_knowledge (chunk_text, source_document, chunk_order, embedding)
                    VALUES (%s, %s, %s, %s)
                """, (chunk, source_document, i, emb))

        conn.commit()
        logging.info(f"Inserted {len(chunks)} chunks into DB for {source_document}")
    except Exception as e:
        logging.error(f"Failed to insert chunks into DB: {e}")
    finally:
        conn.close()

# === MAIN FUNCTION ===
def process_blob_file(blob_filename: str):
    logging.info(f"Processing file: {blob_filename}")
    blob_client = blob_service.get_blob_client(container=CONTAINER_NAME, blob=blob_filename)
    downloader = blob_client.download_blob()
    file_bytes = downloader.readall()

    try:
        raw_text = extract_text(file_bytes, blob_filename)
    except Exception as e:
        logging.error(f"Failed to extract text from {blob_filename}: {e}")
        return

    chunks = chunk_text(raw_text)
    embeddings = [embed_chunk(chunk) for chunk in chunks if chunk.strip()]
    insert_chunks_into_db(chunks, embeddings, source_document=blob_filename)
    logging.info(f"✅ Successfully processed {len(chunks)} chunks from {blob_filename}")

# === OPTIONAL CLI USAGE ===
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    filename = input("Enter blob filename to process (e.g., 'myfile.docx'): ").strip()
    process_blob_file(filename)
