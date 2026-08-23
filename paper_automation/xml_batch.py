"""Resumable Elsevier Article Retrieval XML-only batch workflow."""

from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from doi_batch_utils import clean_doi

from .elsevier_api import ElsevierApiClient, ElsevierXmlResult, parse_full_text_xml
from .file_manager import make_pdf_filename, sanitize_filename
from .models import MetadataResult


DEFAULT_MIN_FREE_BYTES = 8 * 1024**3
DEFAULT_RETRIES = 2
INPUT_FIELDS = ("序号", "期刊谱系", "期刊名", "年份", "标题", "DOI", "Scopus ID", "EID")
MANIFEST_FIELDS = INPUT_FIELDS + (
    "状态",
    "HTTP状态",
    "XML文件",
    "字节数",
    "SHA256",
    "尝试次数",
    "失败原因",
    "完成时间",
)
GLOBAL_STOP_STATUSES = frozenset(
    {"api_key_missing", "unauthorized", "not_entitled", "rate_limited"}
)
TERMINAL_FAILURE_STATUSES = frozenset({"not_found", "invalid_identifier"})


@dataclass(frozen=True)
class XmlCatalogRecord:
    source_index: int
    journal_family: str
    journal_name: str
    year: str
    title: str
    doi: str
    scopus_id: str
    eid: str

    @property
    def identifier_type(self) -> str:
        return "doi" if self.doi else "scopus_id"

    @property
    def identifier(self) -> str:
        return self.doi or self.scopus_id


@dataclass(frozen=True)
class XmlBatchResult:
    run_dir: Path
    total: int
    success: int
    failed: int
    pending: int
    reused: int
    stopped_reason: str
    manifest_path: Path
    failed_path: Path
    summary_path: Path


def _clean_text(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _first_value(row: dict[str, str], *field_names: str) -> str:
    for field_name in field_names:
        value = _clean_text(row.get(field_name))
        if value:
            return value
    return ""


def load_xml_catalog(input_path: str | Path) -> list[XmlCatalogRecord]:
    """Load a CSV containing a DOI or Scopus identifier for each article."""

    source = Path(input_path).expanduser().resolve()
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        field_names = set(reader.fieldnames or [])
        catalog = list(reader)
    identifier_fields = {
        "DOI",
        "doi",
        "Scopus ID",
        "Scopus_ID",
        "scopus_id",
        "scopus id",
        "EID",
        "eid",
        "dc:identifier",
    }
    if not catalog or not field_names.intersection(identifier_fields):
        raise ValueError("xml_catalog_fields_invalid")

    records: list[XmlCatalogRecord] = []
    for source_index, row in enumerate(catalog, 1):
        doi = clean_doi(_first_value(row, "DOI", "doi")).lower()
        eid = _first_value(row, "EID", "eid")
        scopus_id = _first_value(
            row,
            "Scopus ID",
            "Scopus_ID",
            "scopus_id",
            "scopus id",
            "dc:identifier",
        )
        if scopus_id.upper().startswith("SCOPUS_ID:"):
            scopus_id = scopus_id.split(":", 1)[1].strip()
        if scopus_id.lower().startswith("2-s2.0-"):
            scopus_id = scopus_id[len("2-s2.0-") :].strip()
        if not scopus_id and eid.lower().startswith("2-s2.0-"):
            scopus_id = eid[len("2-s2.0-") :].strip()
        if not doi and not scopus_id:
            raise ValueError(f"xml_catalog_identifier_missing:index={source_index}")

        journal_name = _first_value(
            row,
            "期刊名",
            "期刊",
            "journal",
            "Journal",
            "publication_name",
        )
        journal_family = _first_value(row, "期刊谱系", "journal_family")
        records.append(
            XmlCatalogRecord(
                source_index=source_index,
                journal_family=journal_family or journal_name or "Elsevier",
                journal_name=journal_name,
                year=_first_value(row, "年份", "year", "Year"),
                title=_first_value(row, "标题", "题名", "title", "Title"),
                doi=doi,
                scopus_id=scopus_id,
                eid=eid,
            )
        )
    return records


def _input_row(record: XmlCatalogRecord) -> dict[str, object]:
    return {
        "序号": record.source_index,
        "期刊谱系": record.journal_family,
        "期刊名": record.journal_name,
        "年份": record.year,
        "标题": record.title,
        "DOI": record.doi,
        "Scopus ID": record.scopus_id,
        "EID": record.eid,
    }


def _write_csv_atomic(path: Path, fields: Iterable[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _validate_input_snapshot(path: Path, records: list[XmlCatalogRecord]) -> None:
    if not path.exists():
        _write_csv_atomic(path, INPUT_FIELDS, (_input_row(record) for record in records))
        return
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        existing = list(csv.DictReader(handle))
    expected = [
        (str(record.source_index), record.doi, record.scopus_id, record.eid)
        for record in records
    ]
    actual = [
        (
            str(row.get("序号") or ""),
            str(row.get("DOI") or ""),
            str(row.get("Scopus ID") or ""),
            str(row.get("EID") or ""),
        )
        for row in existing
    ]
    if actual != expected:
        raise ValueError("xml_input_manifest_mismatch")


def _load_checkpoint(path: Path) -> dict[int, dict[str, object]]:
    latest: dict[int, dict[str, object]] = {}
    if not path.exists():
        return latest
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
                index = int(row["source_index"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                if line_number == sum(1 for _ in path.open("r", encoding="utf-8")):
                    break
                raise ValueError(f"xml_checkpoint_invalid:line={line_number}")
            latest[index] = row
    return latest


def _append_checkpoint(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _safe_checkpoint_file(run_dir: Path, relative: object) -> Path | None:
    text = str(relative or "").strip()
    if not text:
        return None
    candidate = (run_dir / Path(text)).resolve()
    try:
        candidate.relative_to(run_dir.resolve())
    except ValueError:
        return None
    return candidate


def _valid_existing_success(run_dir: Path, row: dict[str, object]) -> bool:
    if str(row.get("status") or "") != "success":
        return False
    path = _safe_checkpoint_file(run_dir, row.get("file"))
    if path is None or not path.is_file():
        return False
    body = path.read_bytes()
    if parse_full_text_xml(body) is None:
        return False
    expected_sha = str(row.get("sha256") or "")
    return not expected_sha or hashlib.sha256(body).hexdigest() == expected_sha


def _xml_filename(result: ElsevierXmlResult, record: XmlCatalogRecord) -> str:
    metadata = MetadataResult(
        source_index=record.source_index,
        query_title=record.title,
        doi=record.doi or result.doi,
        title=result.title or record.title,
        authors=list(result.authors),
        journal=result.journal or record.journal_name,
        year=result.year or record.year,
        source="elsevier_article_xml",
    )
    pdf_name = make_pdf_filename(metadata)
    return str(Path(pdf_name).with_suffix(".xml"))


def _write_xml_no_overwrite(
    run_dir: Path,
    xml_root: Path,
    record: XmlCatalogRecord,
    result: ElsevierXmlResult,
    lock: threading.Lock,
) -> tuple[Path, int, str]:
    body = result.xml_bytes
    digest = hashlib.sha256(body).hexdigest()
    family = sanitize_filename(record.journal_family) or "Unknown journal"
    directory = xml_root / family
    base_name = _xml_filename(result, record)
    identifier_hash = hashlib.sha256(record.identifier.encode("utf-8")).hexdigest()[:10]
    with lock:
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / base_name
        if target.exists():
            existing = target.read_bytes()
            if hashlib.sha256(existing).hexdigest() == digest and parse_full_text_xml(existing) is not None:
                return target, len(existing), digest
            target = target.with_name(f"{target.stem}-{identifier_hash}{target.suffix}")
        counter = 2
        while target.exists():
            existing = target.read_bytes()
            if hashlib.sha256(existing).hexdigest() == digest and parse_full_text_xml(existing) is not None:
                return target, len(existing), digest
            target = target.with_name(
                f"{Path(base_name).stem}-{identifier_hash}-{counter}.xml"
            )
            counter += 1

        temp = directory / f".{target.name}.{uuid.uuid4().hex}.part"
        try:
            with temp.open("xb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            if parse_full_text_xml(temp.read_bytes()) is None:
                raise ValueError("xml_temp_validation_failed")
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
    return target, len(body), digest


def _failure_checkpoint(
    record: XmlCatalogRecord,
    result: ElsevierXmlResult,
    attempts: int,
    *,
    fallback_attempted: bool = False,
    primary_reason: str = "",
) -> dict[str, object]:
    return {
        "source_index": record.source_index,
        "status": result.status,
        "http_status": result.http_status or "",
        "file": "",
        "size_bytes": 0,
        "sha256": "",
        "attempts": attempts,
        "reason": result.reason or result.status,
        "fallback_attempted": fallback_attempted,
        "primary_reason": primary_reason,
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def _download_one(
    record: XmlCatalogRecord,
    *,
    client: ElsevierApiClient,
    run_dir: Path,
    xml_root: Path,
    file_lock: threading.Lock,
    stop_event: threading.Event,
    retries: int,
) -> dict[str, object] | None:
    if stop_event.is_set():
        return None

    def retrieve(identifier: str, identifier_type: str) -> tuple[ElsevierXmlResult | None, int]:
        last: ElsevierXmlResult | None = None
        attempts = 0
        for attempt in range(retries + 1):
            if stop_event.is_set():
                return None, attempts
            attempts = attempt + 1
            last = client.retrieve_article_xml(
                identifier,
                identifier_type=identifier_type,
            )
            if last.status == "success":
                return last, attempts
            retryable = last.status == "network_error" and (
                last.http_status is None or int(last.http_status) >= 500
            )
            if not retryable or attempt >= retries:
                break
            time.sleep(min(2**attempt, 4))
        return last, attempts

    def success_checkpoint(result: ElsevierXmlResult, attempts: int) -> dict[str, object]:
        target, size, digest = _write_xml_no_overwrite(
            run_dir,
            xml_root,
            record,
            result,
            file_lock,
        )
        return {
            "source_index": record.source_index,
            "status": "success",
            "http_status": result.http_status or "",
            "file": target.relative_to(run_dir).as_posix(),
            "size_bytes": size,
            "sha256": digest,
            "attempts": attempts,
            "reason": "",
            "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }

    primary, attempts = retrieve(record.identifier, record.identifier_type)
    if primary is None:
        return None
    if primary.status == "success":
        return success_checkpoint(primary, attempts)

    fallback_statuses = {"not_found", "invalid_xml", "invalid_identifier", "network_error"}
    if record.doi and record.scopus_id and primary.status in fallback_statuses:
        fallback, fallback_attempts = retrieve(record.scopus_id, "scopus_id")
        attempts += fallback_attempts
        if fallback is None:
            return None
        if fallback.status == "success":
            return success_checkpoint(fallback, attempts)
        return _failure_checkpoint(
            record,
            fallback,
            attempts,
            fallback_attempted=True,
            primary_reason=primary.reason or primary.status,
        )
    return _failure_checkpoint(record, primary, attempts)


def _manifest_row(
    record: XmlCatalogRecord,
    checkpoint: dict[str, object] | None,
) -> dict[str, object]:
    row = _input_row(record)
    state = checkpoint or {}
    row.update(
        {
            "状态": state.get("status") or "pending",
            "HTTP状态": state.get("http_status") or "",
            "XML文件": state.get("file") or "",
            "字节数": state.get("size_bytes") or 0,
            "SHA256": state.get("sha256") or "",
            "尝试次数": state.get("attempts") or 0,
            "失败原因": state.get("reason") or "",
            "完成时间": state.get("completed_at") or "",
        }
    )
    return row


def _write_reports(
    run_dir: Path,
    records: list[XmlCatalogRecord],
    latest: dict[int, dict[str, object]],
    *,
    reused: int,
    stopped_reason: str,
    started_at: str,
) -> XmlBatchResult:
    reports = run_dir / "reports"
    manifest_path = reports / "download_manifest.csv"
    failed_path = reports / "failed.csv"
    summary_path = reports / "run_summary.txt"
    manifest_rows = [_manifest_row(record, latest.get(record.source_index)) for record in records]
    failed_rows = [
        row
        for row in manifest_rows
        if row["状态"] not in {"success", "pending"}
    ]
    success = sum(row["状态"] == "success" for row in manifest_rows)
    pending = sum(row["状态"] == "pending" for row in manifest_rows)
    total_bytes = sum(int(row["字节数"] or 0) for row in manifest_rows if row["状态"] == "success")
    _write_csv_atomic(manifest_path, MANIFEST_FIELDS, manifest_rows)
    _write_csv_atomic(failed_path, MANIFEST_FIELDS, failed_rows)
    summary = "\n".join(
        (
            "Elsevier 全文 XML 批次摘要",
            f"开始时间: {started_at}",
            f"报告时间: {datetime.now().astimezone().isoformat(timespec='seconds')}",
            f"输入总数: {len(records)}",
            f"成功: {success}",
            f"失败: {len(failed_rows)}",
            f"待处理: {pending}",
            f"本次复用: {reused}",
            f"成功字节数: {total_bytes}",
            f"停止原因: {stopped_reason or 'none'}",
            "PDF/补充材料/浏览器/OA/Zotero: 未启用",
            "",
        )
    )
    _write_text_atomic(summary_path, summary)
    return XmlBatchResult(
        run_dir=run_dir,
        total=len(records),
        success=success,
        failed=len(failed_rows),
        pending=pending,
        reused=reused,
        stopped_reason=stopped_reason,
        manifest_path=manifest_path,
        failed_path=failed_path,
        summary_path=summary_path,
    )


def run_xml_batch(
    *,
    input_path: str | Path,
    output_root: str | Path,
    run_name: str,
    workers: int = 4,
    timeout_seconds: float = 30.0,
    limit: int = 0,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    retries: int = DEFAULT_RETRIES,
    client: ElsevierApiClient | None = None,
    progress: Callable[[str], None] = print,
) -> XmlBatchResult:
    """Run or resume one fixed XML-only batch."""

    if workers not in range(1, 5):
        raise ValueError("xml_workers_invalid")
    if limit < 0:
        raise ValueError("xml_limit_invalid")
    safe_run_name = sanitize_filename(run_name)
    if not safe_run_name or safe_run_name != run_name or Path(run_name).name != run_name:
        raise ValueError("xml_run_name_invalid")
    api_client = client or ElsevierApiClient(timeout_seconds=timeout_seconds)
    if not api_client.api_key:
        raise RuntimeError("api_key_missing")

    records = load_xml_catalog(input_path)
    root = Path(output_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < min_free_bytes:
        raise RuntimeError("xml_disk_low")
    run_dir = root / safe_run_name
    xml_root = run_dir / "xml"
    reports = run_dir / "reports"
    working = run_dir / "working"
    for path in (xml_root, reports, working):
        path.mkdir(parents=True, exist_ok=True)
    _validate_input_snapshot(reports / "input_manifest.csv", records)

    checkpoint_path = working / "xml_checkpoint.jsonl"
    latest = _load_checkpoint(checkpoint_path)
    reusable: set[int] = {
        index
        for index, row in latest.items()
        if _valid_existing_success(run_dir, row)
    }
    record_by_index = {record.source_index: record for record in records}
    terminal_failures: set[int] = set()
    for index, row in latest.items():
        record = record_by_index.get(index)
        if record is None:
            continue
        status = str(row.get("status") or "")
        fallback_done = bool(row.get("fallback_attempted"))
        if status in TERMINAL_FAILURE_STATUSES and (not record.doi or fallback_done):
            terminal_failures.add(index)
    pending = [
        record
        for record in records
        if record.source_index not in reusable
        and record.source_index not in terminal_failures
    ]
    if limit:
        pending = pending[:limit]
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    progress(
        f"[xml-download] 总数 {len(records)}；已验证复用 {len(reusable)}；"
        f"本次计划 {len(pending)}；并发 {workers}"
    )

    stop_event = threading.Event()
    file_lock = threading.Lock()
    stopped_reason = ""
    completed_this_run = 0
    records_iter = iter(pending)
    futures: dict[Future[dict[str, object] | None], XmlCatalogRecord] = {}

    def submit_next(executor: ThreadPoolExecutor) -> bool:
        nonlocal stopped_reason
        if stop_event.is_set():
            return False
        if shutil.disk_usage(run_dir).free < min_free_bytes:
            stopped_reason = "disk_low"
            stop_event.set()
            return False
        try:
            record = next(records_iter)
        except StopIteration:
            return False
        future = executor.submit(
            _download_one,
            record,
            client=api_client,
            run_dir=run_dir,
            xml_root=xml_root,
            file_lock=file_lock,
            stop_event=stop_event,
            retries=retries,
        )
        futures[future] = record
        return True

    with ThreadPoolExecutor(max_workers=workers) as executor:
        for _ in range(workers):
            if not submit_next(executor):
                break
        while futures:
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                record = futures.pop(future)
                row = future.result()
                if row is None:
                    continue
                _append_checkpoint(checkpoint_path, row)
                latest[record.source_index] = row
                completed_this_run += 1
                status = str(row.get("status") or "")
                if status in GLOBAL_STOP_STATUSES and not stopped_reason:
                    stopped_reason = status
                    stop_event.set()
                if completed_this_run % 25 == 0 or status != "success":
                    progress(
                        f"[xml-download] 本次 {completed_this_run}/{len(pending)}；"
                        f"总进度 {len(reusable) + completed_this_run}/{len(records)}；"
                        f"序号 {record.source_index}：{status}"
                    )
            while len(futures) < workers and submit_next(executor):
                pass

    result = _write_reports(
        run_dir,
        records,
        latest,
        reused=len(reusable),
        stopped_reason=stopped_reason,
        started_at=started_at,
    )
    progress(
        f"[xml-download] 成功 {result.success}；失败 {result.failed}；"
        f"待处理 {result.pending}；报告 {result.manifest_path}"
    )
    return result
