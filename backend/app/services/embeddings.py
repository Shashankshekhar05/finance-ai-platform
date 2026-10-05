"""BGE embedding service: exactly one model, loaded once per process.

- Model: BAAI/bge-base-en-v1.5 via SentenceTransformers (locked decision).
- Prefix convention (RAG_RULES §4.5, BGE README): queries carry
  "Represent this sentence for searching relevant passages: "; documents
  carry NO prefix. Same text in different roles → different vectors, by
  design. Changing this invalidates stored vectors.
- L2-normalized on BOTH sides (encode(normalize_embeddings=True)), matching
  the cosine-distance (`<=>`) retrieval metric.
- Batching at the service boundary: `embed_texts` takes a list; per-chunk
  calls are a review-level bug (§34). A lock guards load + encode.
- Dimension guard: the loaded model's dim MUST equal configured
  EMBEDDING_DIMENSIONS (768), else fail fast — never store mismatched dims.
"""

import threading

from app.core.config import Settings

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
DOCUMENT_PREFIX = ""


class EmbeddingService:
    def __init__(self, settings: Settings) -> None:
        self._model_name = settings.embedding_model_name
        self._expected_dimensions = settings.embedding_dimensions
        self._batch_size = settings.embedding_batch_size
        self._lock = threading.Lock()
        self._model = None

    @property
    def model_name(self) -> str:
        return self._model_name

    def _load(self):  # type: ignore[no-untyped-def]
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(self._model_name)
        dimensions = int(model.get_sentence_embedding_dimension())
        if dimensions != self._expected_dimensions:
            raise ValueError(
                f"Embedding dimension mismatch: model reports {dimensions}, "
                f"configured {self._expected_dimensions}."
            )
        return model

    def _model_or_load(self):  # type: ignore[no-untyped-def]
        if self._model is None:
            with self._lock:
                if self._model is None:
                    self._model = self._load()
        return self._model

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def embed_texts(self, texts: list[str], *, role: str) -> list[list[float]]:
        """Batch-encode normalized vectors. role: 'document' | 'query'."""
        if not texts:
            return []
        if role == "query":
            prepared = [f"{QUERY_PREFIX}{text}" for text in texts]
        elif role == "document":
            prepared = [f"{DOCUMENT_PREFIX}{text}" for text in texts]
        else:
            raise ValueError(f"Unknown embedding role: {role!r}")
        model = self._model_or_load()
        with self._lock:
            vectors = model.encode(
                prepared,
                batch_size=self._batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        return [list(map(float, row)) for row in vectors]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text], role="query")[0]


_service: EmbeddingService | None = None
_service_lock = threading.Lock()


def get_embedding_service(settings: Settings | None = None) -> EmbeddingService:
    """Process-level singleton: one loaded model per process, ever."""
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                from app.core.config import get_settings

                _service = EmbeddingService(settings or get_settings())
    return _service


def reset_embedding_service() -> None:
    """Tests only: drop the singleton so settings can vary between tests."""
    global _service
    with _service_lock:
        _service = None
