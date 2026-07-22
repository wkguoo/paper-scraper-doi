"""Stable paper identities and durable, collision-safe PDF publication."""

from __future__ import annotations

import hashlib
import errno
import os
import re
import tempfile
import time
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping

from doi_batch_utils import clean_doi

from .pdf_validation import is_pdf_bytes, is_valid_pdf

if os.name == "nt":
    import msvcrt
else:
    import fcntl


IDENTITY_HASH_LENGTH = 12
DEFAULT_PDF_MAX_BYTES = 256 * 1024 * 1024
DEFAULT_SUPPLEMENT_MAX_BYTES = 2 * 1024 * 1024 * 1024
STREAM_CHUNK_SIZE = 1024 * 1024
_SAFE_PII_RE = re.compile(r"[^a-z0-9]+")
_TITLE_WORD_RE = re.compile(r"[^\w]+", flags=re.UNICODE)


@dataclass(frozen=True)
class PaperIdentity:
    """Canonical identity chosen in DOI -> PII -> title priority order."""

    kind: str
    value: str
    digest: str


def _value(source: Any, name: str) -> str:
    if isinstance(source, Mapping):
        return str(source.get(name, "") or "")
    return str(getattr(source, name, "") or "")


def normalize_pii(value: object) -> str:
    return _SAFE_PII_RE.sub("", str(value or "").strip().casefold())


def normalize_title_identity(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(part for part in _TITLE_WORD_RE.split(text) if part)


def paper_identity(
    source: Any | None = None,
    *,
    doi: object = "",
    pii: object = "",
    title: object = "",
) -> PaperIdentity:
    """Return one stable paper identity without relying on a display filename."""

    if source is not None:
        doi = doi or _value(source, "doi") or _value(source, "input_doi")
        pii = pii or _value(source, "pii")
        title = (
            title
            or _value(source, "title")
            or _value(source, "input_title")
            or _value(source, "query_title")
        )
    normalized_doi = clean_doi(str(doi or "")).strip().casefold()
    normalized_pii = normalize_pii(pii)
    normalized_title = normalize_title_identity(title)
    if normalized_doi:
        kind, canonical = "doi", normalized_doi
    elif normalized_pii:
        kind, canonical = "pii", normalized_pii
    elif normalized_title:
        kind, canonical = "title", normalized_title
    else:
        # Callers should normally have at least one identity field.  Keeping a
        # deterministic fallback is safer than letting a display name decide.
        kind, canonical = "unknown", "unknown"
    digest = hashlib.sha256(f"{kind}:{canonical}".encode("utf-8")).hexdigest()
    return PaperIdentity(kind=kind, value=canonical, digest=digest[:IDENTITY_HASH_LENGTH])


def make_artifact_filename(
    index: int,
    source: Any | None = None,
    *,
    doi: object = "",
    pii: object = "",
    title: object = "",
) -> str:
    identity = paper_identity(source, doi=doi, pii=pii, title=title)
    safe_index = max(1, int(index or 1))
    return f"paper-{safe_index:04d}_{identity.digest}.pdf"


def publish_pdf_bytes_atomic(
    content: bytes | bytearray | memoryview,
    destination_dir: str | Path,
    filename: str,
    *,
    lock_timeout: float = 10.0,
    max_bytes: int = DEFAULT_PDF_MAX_BYTES,
) -> Path:
    """Durably publish PDF bytes without overwriting an existing different file.

    The private file is created in the destination directory, flushed and
    fsynced, validated, then handed to the shared exclusive publisher.  The
    latter reuses identical content and adds a content-hash suffix on collision.
    """

    data = bytes(content)
    if not is_pdf_bytes(data):
        raise ValueError("not_pdf_response")
    return publish_stream_atomic(
        (data,),
        destination_dir,
        filename,
        max_bytes=max_bytes,
        content_length=len(data),
        validator=_validate_pdf_artifact,
        lock_timeout=lock_timeout,
        temporary_prefix=".pdf_stream_",
    )


def publish_pdf_stream_atomic(
    chunks: Iterable[bytes | bytearray | memoryview],
    destination_dir: str | Path,
    filename: str,
    *,
    content_length: int | None = None,
    max_bytes: int = DEFAULT_PDF_MAX_BYTES,
    lock_timeout: float = 10.0,
) -> Path:
    return publish_stream_atomic(
        chunks,
        destination_dir,
        filename,
        max_bytes=max_bytes,
        content_length=content_length,
        validator=_validate_pdf_artifact,
        lock_timeout=lock_timeout,
        temporary_prefix=".pdf_stream_",
    )


def publish_stream_atomic(
    chunks: Iterable[bytes | bytearray | memoryview],
    destination_dir: str | Path,
    filename: str,
    *,
    max_bytes: int,
    content_length: int | None = None,
    validator: Callable[[Path], object] | None = None,
    lock_timeout: float = 10.0,
    temporary_prefix: str = ".artifact_stream_",
) -> Path:
    """Stream one response into a private same-directory file and publish exclusively."""

    limit = int(max_bytes)
    if limit <= 0:
        raise ValueError("invalid_max_bytes")
    if content_length is not None:
        try:
            declared = int(content_length)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid_content_length") from exc
        if declared < 0:
            raise ValueError("invalid_content_length")
        if declared > limit:
            raise ValueError("response_too_large")

    safe_filename = _safe_artifact_filename(filename)
    destination = Path(destination_dir).expanduser()
    if not destination.is_absolute():
        destination = Path.cwd() / destination
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=temporary_prefix,
        suffix=".tmp",
        dir=destination,
    )
    temporary = Path(temporary_name)
    descriptor_open = True
    digest = hashlib.sha256()
    total = 0
    try:
        handle = os.fdopen(descriptor, "wb")
        descriptor_open = False
        with handle:
            for raw_chunk in chunks:
                if raw_chunk is None:
                    continue
                chunk = bytes(raw_chunk)
                if not chunk:
                    continue
                total += len(chunk)
                if total > limit:
                    raise ValueError("response_too_large")
                handle.write(chunk)
                digest.update(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if total <= 0:
            raise ValueError("empty_response")
        if content_length is not None and total != int(content_length):
            raise ValueError("response_length_mismatch")
        if validator is not None and validator(temporary) is False:
            raise ValueError("artifact_validation_failed")
        with _artifact_publish_lock(destination, timeout=lock_timeout):
            return _publish_private_artifact(
                temporary,
                destination / safe_filename,
                digest.hexdigest(),
            )
    finally:
        if descriptor_open:
            try:
                os.close(descriptor)
            except OSError:
                pass
        temporary.unlink(missing_ok=True)


def iter_file_chunks(path: str | Path, *, chunk_size: int = STREAM_CHUNK_SIZE) -> Iterator[bytes]:
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                return
            yield chunk


def _validate_pdf_artifact(path: Path) -> bool:
    if not is_valid_pdf(path):
        raise ValueError("not_pdf_response")
    return True


def _safe_artifact_filename(filename: object) -> str:
    value = str(filename or "")
    path = Path(value)
    if (
        not value
        or path.is_absolute()
        or path.name != value
        or value in {".", ".."}
        or value != value.rstrip(". ")
        or any(char in '<>:"/\\|?*' or ord(char) < 32 for char in value)
    ):
        raise ValueError("invalid_filename")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(STREAM_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _same_artifact(path: Path, expected_hash: str) -> bool:
    return path.is_file() and not path.is_symlink() and _sha256_file(path) == expected_hash


def _publish_private_artifact(temporary: Path, target: Path, digest: str) -> Path:
    candidates = [target]
    counter = 1
    while True:
        candidate = candidates[-1]
        if candidate.exists() or candidate.is_symlink():
            if _same_artifact(candidate, digest):
                return candidate
        else:
            try:
                os.link(temporary, candidate)
            except FileExistsError:
                pass
            else:
                return candidate
        suffix = f"_{digest[:8]}" if counter == 1 else f"_{digest[:8]}_{counter}"
        candidates.append(target.with_name(f"{target.stem}{suffix}{target.suffix}"))
        counter += 1


def _try_lock(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _artifact_publish_lock(directory: Path, *, timeout: float) -> Iterator[None]:
    lock_path = directory.parent / f".{directory.name}.artifact_publish.lock"
    handle = lock_path.open("a+b")
    acquired = False
    deadline = time.monotonic() + float(timeout)
    try:
        while True:
            try:
                _try_lock(handle)
            except OSError as exc:
                contention = (
                    isinstance(exc, BlockingIOError)
                    or exc.errno in {errno.EACCES, errno.EAGAIN}
                    or getattr(exc, "winerror", None) in {32, 33}
                )
                if not contention:
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("artifact_publish_lock_timeout") from exc
                time.sleep(min(0.05, remaining))
            else:
                acquired = True
                break
        yield
    finally:
        try:
            if acquired:
                _unlock(handle)
        finally:
            handle.close()
