# app/chatbot_documents.py

import logging
from typing import List, Generator, Optional
from groq import Groq
from openai import OpenAI

from app.config import OPENAI_API_KEY, GROQ_API_KEY
from app.database import get_session_messages, store_message, embed_query, get_db_connection

# Initialize OpenAI and Groq clients
openai_client_for_query_embedding = OpenAI(api_key=OPENAI_API_KEY)
rag_response_client = Groq(api_key=GROQ_API_KEY)


def get_recent_conversation(session_id: str, max_tokens: int = 100) -> List[dict]:
    if not session_id:
        return []
    messages = get_session_messages(session_id)
    formatted = []
    for _, content, _, msg_type in messages:
        if msg_type == "user":
            formatted.append({"role": "user", "content": content})
        elif msg_type == "bot":
            formatted.append({"role": "assistant", "content": content})

    selected = []
    current_len = 0
    for msg in reversed(formatted):
        if current_len + len(msg["content"]) > max_tokens * 4:
            break
        selected.insert(0, msg)
        current_len += len(msg["content"])
    return selected


def search_document_knowledge(query_embedding: List[float], top_k: int = 5) -> List[tuple]:
    conn = get_db_connection()
    if conn is None:
        logging.error("No DB connection for document_knowledge search")
        return []

    results = []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT chunk_id, chunk_text, source_document, embedding <=> %s::vector AS similarity
                FROM document_knowledge
                WHERE embedding IS NOT NULL
                ORDER BY similarity ASC
                LIMIT %s;
                """,
                (query_embedding, top_k)
            )
            rows = cur.fetchall()
            results = [(row[0], row[1], row[2], row[3]) for row in rows]
    except Exception as e:
        logging.error(f"Error searching document_knowledge: {e}")
    finally:
        conn.close()

    return results


def document_rag_handler_streaming(
    user_input: str, session_id: Optional[str] = None, language: str = "en-US"
) -> Generator[str, None, None]:
    language_name = "Dutch" if language == "nl-NL" else "English"
    logging.info(f"RAG DOC query: '{user_input}', session: {session_id}, lang: {language}")

    query_embedding = embed_query(user_input)
    if not query_embedding:
        yield "Sorry, I couldn't process your question. Try again."
        return

    retrieved_chunks = search_document_knowledge(query_embedding, top_k=3)
    if not retrieved_chunks:
        yield "I couldn't find any information in the document about that. Try asking differently?"
        return

    context_for_llm = "\n\n---\n\n".join([
        f"From document '{source_doc}' (Chunk ID: {chunk_id}):\n{text_chunk}"
        for chunk_id, text_chunk, source_doc, _ in retrieved_chunks
    ])

    recent_convo = get_recent_conversation(session_id, max_tokens=150)

    system_prompt = (
        f"You are an AI assistant specializing in answering based on a document. "
        f"Use only the provided excerpts below to answer. Do not make up information. "
        f"Respond in {language_name}. Be concise.\n\n"
        f"Excerpts:\n{context_for_llm}"
    )

    messages = [{"role": "system", "content": system_prompt}] + recent_convo + [
        {"role": "user", "content": user_input}
    ]

    try:
        stream = rag_response_client.chat.completions.create(
            model="llama3-70b-8192",
            messages=messages,
            max_tokens=1000,
            temperature=0.3,
            stream=True
        )

        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    except Exception as e:
        logging.error(f"Error in document RAG generation: {e}")
        yield "An error occurred while generating a response."


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_session_id = "test_doc_session"

    while True:
        query = input("Ask a question (type 'quit' to exit): ")
        if query.lower() == "quit":
            break

        full_response = ""
        store_message(test_session_id, query, "user")

        for chunk in document_rag_handler_streaming(query, test_session_id):
            print(chunk, end="", flush=True)
            full_response += chunk

        print("\n")
        store_message(test_session_id, full_response, "bot")
