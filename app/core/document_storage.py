import os
from pathlib import Path
from uuid import UUID, uuid4

from app.core.document_config import MAX_UPLOAD_BYTES


def document_path(root: Path, key: str):
    if UUID(hex=key).hex != key:
        raise ValueError("Invalid storage key")
    directory = root.resolve()
    path = directory / key
    if path.resolve() != path:
        raise ValueError("Invalid storage path")
    return path


def store(root: Path, data: bytes):
    key = uuid4().hex
    path = document_path(root, key)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags, mode=0o600)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
    except OSError:
        path.unlink(missing_ok=True)
        raise
    return key, path


def read(root: Path, key: str, declared_size: int):
    path = document_path(root, key)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    with os.fdopen(os.open(path, flags), "rb") as file:
        data = file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) != declared_size or len(data) > MAX_UPLOAD_BYTES:
        raise OSError("Invalid stored file size")
    return data
