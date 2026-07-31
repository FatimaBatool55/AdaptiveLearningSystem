
"""
Lightweight RAG (Retrieval-Augmented Generation) layer for large study
material.

Why this exists: the AI prompt can only reasonably include a few thousand
characters of context. The old approach just took the first N characters of
the document (`text[:12000]`) — for a large PDF (50+ pages), that could be
just the introduction, missing most of the actual content the questions
should be based on.

This module instead:
1. Splits the full extracted text into overlapping chunks (paragraph-aware).
2. Builds a TF-IDF index over those chunks.
3. For each generation request, retrieves the chunks most relevant to a
   generic "key concepts / definitions / important facts" query (or to the
   student's weak topics, when regenerating practice questions).
4. Joins the top chunks (up to a character budget) into the final context
   sent to Groq.

Deliberately uses TF-IDF (via scikit-learn) rather than neural embedding
models (e.g. sentence-transformers). Those require downloading/loading a
100-400MB model into memory, which is a real risk on constrained hosting
(this project has already hit memory-related crashes with much lighter
dependencies like LibreOffice). TF-IDF is pure statistics over word
frequency — a few milliseconds, no model download, no GPU/CPU inference —
while still being far better than naive truncation for picking relevant
chunks out of a large document.
"""

import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def chunk_text(text, chunk_size=1200, overlap=150):
    """
    Splits text into overlapping chunks, breaking on paragraph boundaries
    where possible instead of mid-word, so each chunk reads as a coherent
    unit for the LLM.
    """
    text = text.strip()
    if len(text) <= chunk_size:
        return [text] if text else []

    paragraphs = re.split(r"\n\s*\n", text)
    chunks = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) + 1 <= chunk_size:
            current = f"{current}\n{para}".strip()
        else:
            if current:
                chunks.append(current)
            if len(para) > chunk_size:
                start = 0
                while start < len(para):
                    end = start + chunk_size
                    chunks.append(para[start:end])
                    start = end - overlap
                current = ""
            else:
                current = para

    if current:
        chunks.append(current)

    overlapped = []
    for i, chunk in enumerate(chunks):
        if i > 0:
            tail = chunks[i - 1][-overlap:]
            chunk = f"{tail}\n{chunk}"
        overlapped.append(chunk)

    return overlapped


def retrieve_relevant_chunks(chunks, query, top_k=6):
    """Ranks chunks by TF-IDF cosine similarity to `query` and returns the
    top_k most relevant, in their ORIGINAL document order (not score order)
    so the final context still reads coherently front-to-back."""
    if len(chunks) <= top_k:
        return chunks

    vectorizer = TfidfVectorizer(stop_words="english")
    try:
        chunk_vectors = vectorizer.fit_transform(chunks)
        query_vector = vectorizer.transform([query])
    except ValueError:
        return chunks[:top_k]

    scores = cosine_similarity(query_vector, chunk_vectors)[0]
    top_indices = sorted(
        sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)[:top_k]
    )
    return [chunks[i] for i in top_indices]


def get_context_for_generation(full_text, difficulty=None, topics_filter=None,
                                max_chars=9000, chunk_size=1200):
    """
    Main entry point used by ai_service.py. Chunks the full extracted text
    and returns a condensed, relevance-ranked context string capped at
    max_chars — used in place of the old `text[:12000]` truncation.
    """
    chunks = chunk_text(full_text, chunk_size=chunk_size)
    if not chunks:
        return full_text[:max_chars]

    if len(chunks) == 1:
        return chunks[0][:max_chars]

    if topics_filter:
        query = "Key concepts, definitions, and facts about: " + ", ".join(topics_filter)
    else:
        query = "Key concepts, definitions, important facts, terminology, and explanations."

    top_k = max(3, max_chars // chunk_size)
    relevant_chunks = retrieve_relevant_chunks(chunks, query, top_k=top_k)

    context = "\n\n".join(relevant_chunks)
    return context[:max_chars]
