from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class InstitutionalPaper:
    row_number: int
    input_doi: str
    doi: str
    title: str
    input_title: str = ""
    authors: tuple[str, ...] = field(default_factory=tuple)
    journal: str = ""
    year: str = ""
    publisher: str = ""
    landing_url: str = ""
    metadata_source: str = ""
    raw_value: str = ""


@dataclass(frozen=True)
class PageSnapshot:
    requested_url: str
    final_url: str
    html: str = ""
    text: str = ""


@dataclass(frozen=True)
class PdfUrlCandidate:
    label: str
    url: str
    fetch_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class PdfCaptureResult:
    requested_url: str
    pdf_url: str = ""
    pdf_bytes: bytes = b""
    note: str = ""


@dataclass(frozen=True)
class InstitutionalReportRow:
    row_number: int
    doi: str
    title: str
    journal: str
    year: str
    publisher: str
    adapter: str
    status: str
    file: str = ""
    reason: str = ""
    landing_url: str = ""
    final_landing_url: str = ""
    pdf_url: str = ""
    metadata_source: str = ""


@dataclass(frozen=True)
class InstitutionalWorkflowResult:
    output_dir: str
    pdf_dir: str
    total_input: int
    resolved_count: int
    downloaded_count: int
    failed_count: int
    status_counts: dict[str, int]
    report_path: str
    run_summary_path: str
    manifest_update_path: str = ""
    rows: tuple[InstitutionalReportRow, ...] = ()
