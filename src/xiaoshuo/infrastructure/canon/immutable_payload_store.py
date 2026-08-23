"""Content-addressed immutable payload storage for the Canon MVP."""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from pathlib import Path
from xiaoshuo.infra.config_manager import get_config


class PayloadStoreError(RuntimeError):
    """A payload root, identifier, or byte stream violates the C2 contract."""


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def _hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _production_root() -> Path:
    try:
        return Path(get_config()["canon_mvp"]["payloads_dir"])
    except (KeyError, TypeError) as exc:
        raise PayloadStoreError("canon_mvp.payloads_dir is required") from exc


def _validate_production_root(root: Path) -> None:
    if root.resolve() != _production_root().resolve():
        raise PayloadStoreError("unapproved payload root")


class ImmutablePayloadStore:
    """A byte-only store; it never treats an ArtifactRef as payload content."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else _production_root()
        _validate_production_root(self.root)

    def put(self, data: bytes) -> str:
        if not isinstance(data, bytes):
            raise PayloadStoreError("payload must be bytes")
        digest = _hash(data)
        target = self.root / digest.removeprefix("sha256:")
        self.root.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != data:
                raise PayloadStoreError("payload hash collision")
        else:
            # A partially written content-addressed object must never become
            # authoritative.  Write and verify a sibling first, then promote
            # it with one same-volume replace operation.
            temporary = self.root / ("." + target.name + "." + uuid.uuid4().hex + ".tmp")
            try:
                temporary.write_bytes(data)
                if temporary.read_bytes() != data:
                    raise PayloadStoreError("payload write verification failed")
                os.replace(temporary, target)
            finally:
                if temporary.exists():
                    temporary.unlink()
        if target.read_bytes() != data:
            raise PayloadStoreError("payload write verification failed")
        return digest

    def read(self, digest: str) -> bytes:
        if not _DIGEST.fullmatch(digest):
            raise PayloadStoreError("invalid payload digest")
        target = self.root / digest.removeprefix("sha256:")
        try:
            data = target.read_bytes()
        except FileNotFoundError as exc:
            raise PayloadStoreError("payload is missing") from exc
        if _hash(data) != digest:
            raise PayloadStoreError("payload hash mismatch")
        return data
