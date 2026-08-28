"""
RAG Agent (Local ChromaDB + SentenceTransformers Retrieval)
==========================================================
Embeds markdown knowledge files from `backend/knowledge/` and stores vector embeddings in a persistent
ChromaDB collection at `storage/chromadb`.
Exposes `retrieve_rag_context(query: str, category: str = None, top_k: int = 2)` to retrieve relevant knowledge.
"""
from __future__ import annotations
import os
import glob
import functools
from typing import List, Dict, Any

CHROMA_PERSIST_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "storage", "chromadb")
KNOWLEDGE_DIR = os.path.join(os.path.dirname(__file__), "..", "knowledge")

_rag_initialized = False
_chroma_collection = None


def _load_knowledge_chunks() -> List[Dict[str, Any]]:
    chunks = []
    md_files = glob.glob(os.path.join(KNOWLEDGE_DIR, "*.md"))
    for filepath in md_files:
        filename = os.path.basename(filepath)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                text = f.read()
            sections = text.split("\n## ")
            doc_title = sections[0].strip("# ").split("\n")[0] if sections else filename
            for idx, sec in enumerate(sections):
                sec_text = sec.strip()
                if not sec_text:
                    continue
                full_chunk = f"## {sec_text}" if idx > 0 else sec_text
                chunk_title = full_chunk.split("\n")[0].strip("# ")
                chunks.append({
                    "id": f"{filename}_{idx}",
                    "text": full_chunk,
                    "metadata": {"source": filename, "doc_title": doc_title, "chunk_title": chunk_title}
                })
        except Exception as e:
            print(f"[RAGAgent] Error reading knowledge file {filename}: {e}")
    return chunks


def init_rag_knowledge_base():
    global _rag_initialized, _chroma_collection
    if _rag_initialized and _chroma_collection is not None:
        return _chroma_collection

    os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
    try:
        import chromadb
        client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        
        embed_fn = None
        try:
            from chromadb.utils import embedding_functions
            embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
        except Exception as e:
            print(f"[RAGAgent] SentenceTransformer embedding function fallback: {e}")

        collection_kwargs = {"name": "webguardian_knowledge"}
        if embed_fn:
            collection_kwargs["embedding_function"] = embed_fn

        collection = client.get_or_create_collection(**collection_kwargs)

        if collection.count() == 0:
            chunks = _load_knowledge_chunks()
            if chunks:
                ids = [c["id"] for c in chunks]
                documents = [c["text"] for c in chunks]
                metadatas = [c["metadata"] for c in chunks]
                collection.add(ids=ids, documents=documents, metadatas=metadatas)
                print(f"[RAGAgent] Indexed {len(chunks)} knowledge chunks into ChromaDB")

        _chroma_collection = collection
        _rag_initialized = True
        return collection
    except Exception as e:
        print(f"[RAGAgent] Failed to initialize ChromaDB collection: {e}")
        return None


@functools.lru_cache(maxsize=128)
def retrieve_rag_context(query: str, category: str = None, top_k: int = 2) -> str:
    """
    Query RAG knowledge base for top_k relevant context snippets.
    Returns concatenated retrieved context string or fallback text.
    """
    search_text = f"{category}: {query}" if category else query

    # Try ChromaDB if initialized without hanging
    try:
        collection = init_rag_knowledge_base()
        if collection:
            results = collection.query(query_texts=[search_text], n_results=top_k)
            docs = results.get("documents", [[]])[0]
            if docs:
                return "\n\n---\n\n".join(docs)
    except Exception:
        pass

    # Fast, deterministic knowledge chunk matching fallback
    chunks = _load_knowledge_chunks()
    q_words = set(w.lower() for w in search_text.split() if len(w) > 2)
    scored = []
    for c in chunks:
        text_lower = c["text"].lower()
        score = sum(1 for w in q_words if w in text_lower)
        if score > 0:
            scored.append((score, c["text"]))
    scored.sort(key=lambda x: x[0], reverse=True)
    if scored:
        return "\n\n---\n\n".join(t[1] for t in scored[:top_k])

    return "Reference standard web QA best practices for accessibility, security, and responsive UI."
