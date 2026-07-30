"""
Embedding service using local sentence-transformers (gte-small).

Uses a small, fast on-device model. No API calls needed.
"""
import os
import json
import numpy as np
from typing import List, Optional

# Global model instance (lazy loaded)
_model = None


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("TaylorAI/gte-small")
    return _model


def embed_text(text: str) -> List[float]:
    """Embed a single text. Returns 384-dim vector."""
    model = get_model()
    emb = model.encode(text, normalize_embeddings=True)
    return emb.tolist()


def embed_batch(texts: List[str]) -> List[List[float]]:
    """Embed multiple texts in batch."""
    model = get_model()
    embs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [e.tolist() for e in embs]


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Vectors are already normalized (L2), so dot product = cosine similarity."""
    return float(np.dot(a, b))


# ── Disk Cache ──

EMBEDDINGS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
os.makedirs(EMBEDDINGS_DIR, exist_ok=True)
CACHE_FILE = os.path.join(EMBEDDINGS_DIR, "chunk_embeddings.json")


def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_cache(cache: dict):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)


def get_cached_embedding(chunk_id: int) -> Optional[List[float]]:
    cache = load_cache()
    return cache.get(f"chunk-{chunk_id}")


def cache_embedding(chunk_id: int, embedding: List[float]):
    cache = load_cache()
    cache[f"chunk-{chunk_id}"] = embedding
    save_cache(cache)
