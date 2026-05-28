"""Lazy-loaded sentence-transformers encoder for search queries."""

import logging

logger = logging.getLogger(__name__)

_model = None


def encode_query(text: str, model_name: str = "all-MiniLM-L6-v2") -> list[float]:
    """Encode a search query string into a 384-dim vector."""
    global _model

    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer(model_name)
            logger.info("Loaded sentence-transformers model: %s", model_name)
        except ImportError:
            logger.warning("sentence-transformers not installed")
            return []

    embedding = _model.encode(text, normalize_embeddings=True)
    return [float(v) for v in embedding]
