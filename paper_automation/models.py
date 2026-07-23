from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PaperCandidate:
    source_index: int
    raw_text: str
    doi: str = ""
    title: str = ""
    status: str = "recognized"
    reason: str = ""


@dataclass(frozen=True)
class DuplicateMapping:
    source_index: int
    duplicate_of: int
    reason: str
    score: float = 1.0


@dataclass(frozen=True)
class DeduplicationResult:
    unique: list[PaperCandidate]
    duplicates: list[DuplicateMapping]


@dataclass
class MetadataResult:
    source_index: int
    query_title: str
    doi: str = ""
    title: str = ""
    authors: list[str] = field(default_factory=list)
    journal: str = ""
    year: str = ""
    publisher: str = ""
    url: str = ""
    is_oa: bool = False
    confidence: float = 0.0
    source: str = ""
    match_basis: str = ""
    reason: str = ""
    crossref: dict = field(default_factory=dict)
    openalex: dict = field(default_factory=dict)
    unpaywall: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PdfCandidate:
    url: str
    source: str
    license: str = ""
    host_type: str = ""
    evidence: str = ""


@dataclass(frozen=True)
class DownloadResponse:
    content: bytes
    content_type: str = ""
    final_url: str = ""


@dataclass(frozen=True)
class DownloadResult:
    status: str
    file: str = ""
    reason: str = ""


@dataclass(frozen=True)
class WorkflowResult:
    output_dir: str
    total_input: int
    unique_count: int
    duplicate_count: int
    resolved_count: int
    downloaded_count: int
    failed_count: int
    manifest_csv: str
    manifest_json: str
    duplicates_csv: str
