from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

from .models import DuplicateMapping


MANIFEST_FIELDS = [
    "source_index",
    "input_doi",
    "input_title",
    "doi",
    "title",
    "authors",
    "journal",
    "year",
    "publisher",
    "url",
    "is_oa",
    "confidence",
    "pdf_source",
    "pdf_url",
    "download_status",
    "file",
    "reason",
]


def write_manifest(rows: list[dict], metadata_dir: str | Path) -> tuple[Path, Path]:
    path = Path(metadata_dir)
    path.mkdir(parents=True, exist_ok=True)
    csv_path = path / "manifest.csv"
    json_path = path / "manifest.json"

    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            normalized = dict(row)
            if isinstance(normalized.get("authors"), list):
                normalized["authors"] = "; ".join(normalized["authors"])
            writer.writerow(normalized)

    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return csv_path, json_path


def write_duplicates(duplicates: list[DuplicateMapping], failed_dir: str | Path) -> Path:
    path = Path(failed_dir)
    path.mkdir(parents=True, exist_ok=True)
    csv_path = path / "duplicates.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["source_index", "duplicate_of", "reason", "score"])
        writer.writeheader()
        for duplicate in duplicates:
            writer.writerow(asdict(duplicate))
    return csv_path

