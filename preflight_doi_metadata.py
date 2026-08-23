"""对 Markdown DOI 表做联网元数据预检，不下载任何 PDF。

输入：本项目使用的 Markdown 管道表格。
输出：UTF-8-SIG CSV；前五列可直接作为后续批量下载输入。
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import socket
import sys
import threading
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from doi_batch_utils import clean_doi
from paper_automation.deduplicator import title_similarity


SOURCE_COLUMNS = [
    "source_index",
    "journal_family",
    "source_journal",
    "source_year",
    "source_volume",
    "source_issue",
    "source_pages",
    "source_title",
    "source_authors",
    "source_category",
    "source_system",
    "source_topic",
    "input_doi",
    "source_checked",
    "source_confidence",
]

OUTPUT_FIELDS = [
    "doi",
    "title",
    "authors",
    "journal",
    "year",
    "source_index",
    "preflight_status",
    "metadata_source",
    "title_similarity",
    "source_title",
    "source_authors",
    "source_journal",
    "source_year",
    "source_volume",
    "source_issue",
    "source_pages",
    "journal_family",
    "source_category",
    "source_system",
    "source_topic",
    "source_checked",
    "source_confidence",
    "publisher",
    "article_type",
    "api_volume",
    "api_issue",
    "api_pages",
    "http_status",
    "attempts",
    "preflight_reason",
]

HttpGetter = Callable[[str, int], tuple[int, dict, dict[str, str]]]


def parse_markdown_table(path: Path) -> list[dict[str, str]]:
    """读取固定 15 字段数据行；允许表头多出的空 Notes 列。"""
    rows: list[dict[str, str]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.split("|")]
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        if not cells or not cells[0].isdigit():
            continue
        if len(cells) != len(SOURCE_COLUMNS):
            raise ValueError(
                f"markdown_table_field_count:{line_number}:"
                f"expected={len(SOURCE_COLUMNS)}:actual={len(cells)}"
            )
        row = dict(zip(SOURCE_COLUMNS, cells, strict=True))
        row["input_doi"] = clean_doi(row["input_doi"]).lower()
        if not row["input_doi"]:
            raise ValueError(f"invalid_doi:{line_number}")
        rows.append(row)

    if not rows:
        raise ValueError("no_markdown_data_rows")
    indexes = [int(row["source_index"]) for row in rows]
    if indexes != list(range(1, len(rows) + 1)):
        raise ValueError("source_index_not_contiguous")
    dois = [row["input_doi"] for row in rows]
    if len(dois) != len(set(dois)):
        raise ValueError("duplicate_doi")
    return rows


def _clean_metadata_text(value: object) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _crossref_year(item: dict) -> str:
    for key in ("published-print", "published-online", "published", "issued", "created"):
        parts = (item.get(key) or {}).get("date-parts") or []
        if parts and parts[0]:
            return str(parts[0][0])
    return ""


def _crossref_authors(item: dict) -> str:
    names: list[str] = []
    for author in item.get("author") or []:
        family = _clean_metadata_text(author.get("family"))
        given = _clean_metadata_text(author.get("given"))
        name = " ".join(part for part in (family, given) if part)
        if name:
            names.append(name)
    return "; ".join(names)


def fetch_crossref(doi: str, timeout: int) -> tuple[int, dict, dict[str, str]]:
    url = f"https://api.crossref.org/works/{quote(doi, safe='')}"
    request = Request(url, headers={"User-Agent": "paper-scraper-doi-preflight/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            headers = {key.lower(): value for key, value in response.headers.items()}
            return int(response.status), payload, headers
    except HTTPError as exc:
        headers = {key.lower(): value for key, value in exc.headers.items()}
        return int(exc.code), {}, headers


def preflight_one(
    source: dict[str, str],
    *,
    timeout: int,
    retries: int,
    getter: HttpGetter = fetch_crossref,
) -> dict[str, str]:
    doi = source["input_doi"]
    http_status = ""
    last_reason = ""
    item: dict = {}
    attempts = 0
    for attempt in range(1, retries + 2):
        attempts = attempt
        try:
            status, payload, headers = getter(doi, timeout)
            http_status = str(status)
            if status == 200:
                item = payload.get("message") or {}
                if item:
                    break
                last_reason = "crossref_empty_message"
            elif status == 404:
                last_reason = "crossref_not_found"
                break
            elif status == 429 or 500 <= status < 600:
                last_reason = f"crossref_http_{status}"
                if attempt <= retries:
                    retry_after = str(headers.get("retry-after", "") or "").strip()
                    delay = min(float(retry_after), 30.0) if retry_after.isdigit() else min(2**attempt, 10)
                    time.sleep(delay)
                    continue
            else:
                last_reason = f"crossref_http_{status}"
                break
        except (TimeoutError, socket.timeout, URLError, OSError, json.JSONDecodeError) as exc:
            last_reason = f"network_error:{type(exc).__name__}"
            if attempt <= retries:
                time.sleep(min(2**attempt, 10))
                continue
        break

    canonical_doi = clean_doi(item.get("DOI") or doi).lower() if item else doi
    canonical_title = _clean_metadata_text(item.get("title")) if item else ""
    canonical_authors = _crossref_authors(item) if item else ""
    canonical_journal = _clean_metadata_text(item.get("container-title")) if item else ""
    canonical_year = _crossref_year(item) if item else ""
    similarity = title_similarity(source["source_title"], canonical_title) if canonical_title else 0.0

    if item and canonical_doi != doi:
        preflight_status = "doi_mismatch"
        last_reason = f"returned_doi={canonical_doi}"
    elif item and canonical_title and canonical_authors and canonical_year:
        preflight_status = "verified_crossref"
        last_reason = "title_difference_review" if similarity < 0.45 else ""
    elif item:
        preflight_status = "metadata_incomplete"
        missing = [
            name
            for name, value in (
                ("title", canonical_title),
                ("authors", canonical_authors),
                ("year", canonical_year),
            )
            if not value
        ]
        last_reason = "missing:" + ",".join(missing)
    elif http_status == "404":
        preflight_status = "doi_not_found"
    elif http_status == "429":
        preflight_status = "rate_limited"
    else:
        preflight_status = "api_error"

    return {
        "doi": canonical_doi,
        "title": canonical_title or _clean_metadata_text(source["source_title"]),
        "authors": canonical_authors or source["source_authors"],
        "journal": canonical_journal or source["source_journal"],
        "year": canonical_year or source["source_year"],
        "source_index": source["source_index"],
        "preflight_status": preflight_status,
        "metadata_source": "crossref" if item else "source",
        "title_similarity": f"{similarity:.4f}" if item else "",
        "source_title": source["source_title"],
        "source_authors": source["source_authors"],
        "source_journal": source["source_journal"],
        "source_year": source["source_year"],
        "source_volume": source["source_volume"],
        "source_issue": source["source_issue"],
        "source_pages": source["source_pages"],
        "journal_family": source["journal_family"],
        "source_category": source["source_category"],
        "source_system": source["source_system"],
        "source_topic": source["source_topic"],
        "source_checked": source["source_checked"],
        "source_confidence": source["source_confidence"],
        "publisher": _clean_metadata_text(item.get("publisher")) if item else "",
        "article_type": _clean_metadata_text(item.get("type")) if item else "",
        "api_volume": _clean_metadata_text(item.get("volume")) if item else "",
        "api_issue": _clean_metadata_text(item.get("issue")) if item else "",
        "api_pages": _clean_metadata_text(item.get("page")) if item else "",
        "http_status": http_status,
        "attempts": str(attempts),
        "preflight_reason": last_reason,
    }


def write_csv_atomic(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def run_preflight(
    sources: list[dict[str, str]],
    *,
    output: Path,
    workers: int,
    timeout: int,
    retries: int,
    checkpoint_every: int,
) -> list[dict[str, str]]:
    partial = output.with_suffix(".partial.csv")
    completed: dict[str, dict[str, str]] = {}
    if partial.exists():
        with partial.open(encoding="utf-8-sig", newline="") as handle:
            completed = {row["doi"].lower(): row for row in csv.DictReader(handle) if row.get("doi")}
        print(f"[续跑] 已载入 {len(completed)} 条预检结果", flush=True)

    pending = [source for source in sources if source["input_doi"] not in completed]
    lock = threading.Lock()
    executor = ThreadPoolExecutor(max_workers=workers)
    futures: dict[Future[dict[str, str]], dict[str, str]] = {}
    try:
        for source in pending:
            future = executor.submit(preflight_one, source, timeout=timeout, retries=retries)
            futures[future] = source
        total = len(sources)
        while futures:
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                source = futures.pop(future)
                row = future.result()
                with lock:
                    completed[source["input_doi"]] = row
                    count = len(completed)
                if count % checkpoint_every == 0 or count == total:
                    ordered = [completed[item["input_doi"]] for item in sources if item["input_doi"] in completed]
                    write_csv_atomic(partial, ordered)
                    counts = Counter(item["preflight_status"] for item in ordered)
                    print(f"[预检] {count}/{total} {dict(counts)}", flush=True)
    except KeyboardInterrupt:
        ordered = [completed[item["input_doi"]] for item in sources if item["input_doi"] in completed]
        write_csv_atomic(partial, ordered)
        executor.shutdown(wait=False, cancel_futures=True)
        print(f"[暂停] 已保存 {len(ordered)} 条到 {partial}", flush=True)
        raise
    else:
        executor.shutdown(wait=True)

    ordered = [completed[item["input_doi"]] for item in sources]
    if output.exists():
        raise FileExistsError(f"output_already_exists:{output}")
    write_csv_atomic(output, ordered)
    return ordered


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="全量 DOI 联网元数据预检（不下载 PDF）")
    parser.add_argument("--input", required=True, help="Markdown DOI 表路径")
    parser.add_argument("--output", required=True, help="最终 UTF-8-SIG CSV 路径")
    parser.add_argument("--workers", type=int, default=4, help="并发请求数（默认 4）")
    parser.add_argument("--timeout", type=int, default=15, help="单次请求超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="网络/限流重试次数")
    parser.add_argument("--checkpoint-every", type=int, default=25, help="每 N 条写入断点")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    if args.workers < 1 or args.workers > 8:
        raise ValueError("workers_must_be_between_1_and_8")
    sources = parse_markdown_table(input_path)
    print(f"[输入] {len(sources)} 条唯一 DOI", flush=True)
    rows = run_preflight(
        sources,
        output=output_path,
        workers=args.workers,
        timeout=args.timeout,
        retries=args.retries,
        checkpoint_every=max(1, args.checkpoint_every),
    )
    counts = Counter(row["preflight_status"] for row in rows)
    print(f"[完成] {output_path}", flush=True)
    print(f"[状态] {dict(counts)}", flush=True)
    return 0 if all(row["preflight_status"] == "verified_crossref" for row in rows) else 2


if __name__ == "__main__":
    sys.exit(main())
