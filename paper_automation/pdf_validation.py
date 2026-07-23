"""Shared PDF byte/path validation used by OA, batch, and institutional paths."""

from __future__ import annotations

from pathlib import Path

# Floor below a real article PDF but above empty stubs (%PDF- + %%EOF).
DEFAULT_MINIMUM_SIZE = 16
_EOF_SCAN_BYTES = 2048


def is_pdf_bytes(content: bytes | bytearray | memoryview, minimum_size: int = DEFAULT_MINIMUM_SIZE) -> bool:
    """Return True when *content* looks like a complete-enough PDF.

    Checks:
    - minimum size
    - ``%PDF-`` header
    - ``%%EOF`` marker near the end (last 2 KiB)
    """
    data = bytes(content)
    if minimum_size < 0:
        minimum_size = DEFAULT_MINIMUM_SIZE
    if len(data) < minimum_size:
        return False
    if not data.startswith(b"%PDF-"):
        return False
    tail = data[-_EOF_SCAN_BYTES:] if len(data) > _EOF_SCAN_BYTES else data
    return b"%%EOF" in tail


def is_valid_pdf(path: str | Path, minimum_size: int = DEFAULT_MINIMUM_SIZE) -> bool:
    """Return True when *path* is a regular file that passes :func:`is_pdf_bytes`."""
    target = Path(path)
    try:
        if not target.is_file() or target.is_symlink():
            return False
        size = target.stat().st_size
        if size < minimum_size:
            return False
        with target.open("rb") as handle:
            header = handle.read(5)
            if header != b"%PDF-":
                return False
            if size <= _EOF_SCAN_BYTES:
                rest = handle.read()
                return b"%%EOF" in (header + rest)
            handle.seek(max(0, size - _EOF_SCAN_BYTES))
            return b"%%EOF" in handle.read()
    except OSError:
        return False


def minimal_pdf_bytes(payload: bytes = b"fixture") -> bytes:
    """Build a tiny byte string accepted by :func:`is_pdf_bytes` (for tests/fixtures)."""
    body = bytes(payload or b"fixture")
    return b"%PDF-1.7\n" + body + b"\n%%EOF\n"
