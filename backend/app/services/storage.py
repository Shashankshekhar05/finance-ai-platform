"""Storage abstraction: callers depend on this interface, never on disks.

Phase 4 ships LocalFileStorage (filesystem under DOCUMENT_STORAGE_ROOT).
A future S3/Supabase backend implements the same three methods — no caller
changes. Storage keys are GENERATED (`{company_id}/{document_id}.pdf`);
user filenames never touch the filesystem (path-traversal safe by design).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class StorageService(Protocol):
    def put(self, *, key: str, data: bytes) -> None: ...
    def get(self, *, key: str) -> bytes: ...
    def delete(self, *, key: str) -> None: ...


@dataclass(frozen=True)
class LocalFileStorage:
    root: Path

    def _resolve(self, key: str) -> Path:
        # Keys are generated (`{company_id}/{document_id}.pdf`), but resolve
        # defensively anyway: no absolute paths, no parent traversal, and the
        # final path must stay under the storage root.
        if not key or Path(key).is_absolute() or ".." in Path(key).parts:
            raise ValueError("Invalid storage key.")
        root = self.root.resolve()
        candidate = (root / key).resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError("Invalid storage key.")
        return candidate

    def put(self, *, key: str, data: bytes) -> None:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, *, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    def delete(self, *, key: str) -> None:
        try:
            self._resolve(key).unlink()
        except FileNotFoundError:
            pass


def document_key(*, company_id: str, document_id: str) -> str:
    """Safe storage key. Original filenames are metadata only, never paths."""
    return f"{company_id}/{document_id}.pdf"


def local_storage(root: str) -> LocalFileStorage:
    return LocalFileStorage(root=Path(root))
