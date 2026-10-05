"""Storage abstraction: traversal guard + put/get/delete. No database."""

import pytest

from app.services.storage import LocalFileStorage, document_key


def test_document_key_never_uses_original_filename() -> None:
    key = document_key(company_id="c1", document_id="d1")
    assert key == "c1/d1.pdf"
    assert ".." not in key


def test_local_storage_round_trip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    storage = LocalFileStorage(root=tmp_path)
    storage.put(key="c1/d1.pdf", data=b"%PDF-1.4 fake")
    assert storage.get(key="c1/d1.pdf") == b"%PDF-1.4 fake"
    storage.delete(key="c1/d1.pdf")
    with pytest.raises(FileNotFoundError):
        storage.get(key="c1/d1.pdf")
    storage.delete(key="c1/d1.pdf")  # missing delete is tolerated


@pytest.mark.parametrize("key", ["", "../escape.pdf", "/abs.pdf", "a/../../b.pdf"])
def test_local_storage_rejects_escaping_keys(tmp_path, key: str) -> None:  # type: ignore[no-untyped-def]
    storage = LocalFileStorage(root=tmp_path)
    with pytest.raises(ValueError):
        storage.put(key=key, data=b"x")
