"""Embedding service tests: model identity, shape, convention, lifecycle.

Uses the real BAAI/bge-base-en-v1.5 (downloads once to the HF cache).
Asserts shapes and properties — never exact float values.
"""

import math

import pytest

from app.core.config import get_settings
from app.services.embeddings import (
    EmbeddingService,
    get_embedding_service,
    reset_embedding_service,
)


@pytest.fixture(scope="module")
def service():
    return EmbeddingService(get_settings())


def test_correct_model_and_dimensions(service: EmbeddingService) -> None:
    assert service.model_name == "BAAI/bge-base-en-v1.5"
    vectors = service.embed_texts(["revenue grew in fiscal 2025"], role="document")
    assert len(vectors) == 1 and len(vectors[0]) == 768
    assert all(isinstance(v, float) for v in vectors[0])


def test_embeddings_are_l2_normalized(service: EmbeddingService) -> None:
    vectors = service.embed_texts(["operating expenses fell"], role="document")
    assert math.isclose(sum(v * v for v in vectors[0]), 1.0, rel_tol=1e-4)


def test_query_and_document_conventions_differ(service: EmbeddingService) -> None:
    text = "What was revenue in fiscal 2025?"
    as_doc = service.embed_texts([text], role="document")[0]
    as_query = service.embed_texts([text], role="query")[0]
    assert as_doc != as_query  # prefixes change the representation, by design


def test_batch_encoding_single_call(service: EmbeddingService) -> None:
    texts = [f"financial statement line number {i}" for i in range(5)]
    vectors = service.embed_texts(texts, role="document")
    assert len(vectors) == 5
    assert all(len(v) == 768 for v in vectors)
    assert len({tuple(v) for v in vectors}) == 5  # distinct inputs, distinct vectors


def test_empty_input_never_touches_model(service: EmbeddingService) -> None:
    assert service.embed_texts([], role="document") == []
    with pytest.raises(ValueError):
        service.embed_texts(["x"], role="passage")


def test_embed_query_matches_batched_query_encoding(service: EmbeddingService) -> None:
    single = service.embed_query("ebitda margin expanded")
    batched = service.embed_texts(["ebitda margin expanded"], role="query")[0]
    assert single == batched


def test_singleton_lifecycle_loads_once() -> None:
    reset_embedding_service()
    first = get_embedding_service(get_settings())
    assert first.is_loaded is False
    first.embed_texts(["warmup vector content here"], role="document")
    assert first.is_loaded is True
    assert get_embedding_service(get_settings()) is first
    reset_embedding_service()
