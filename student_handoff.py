from __future__ import annotations

import csv
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


STUDENT_DIR_NAME = "00_给研究生查看"
README_NAME = "README_先看我.txt"
PAPER_INDEX_NAME = "paper_index.csv"
PAPER_INDEX_XLSX_NAME = "paper_index.xlsx"
FAILURE_NEXT_STEPS_NAME = "失败项_下一步处理.csv"
LIBRARY_INDEX_NAME = "library_index.csv"

PAPER_INDEX_FIELDS = [
    "序号",
    "PDF状态",
    "DOI",
    "PII",
    "题名",
    "正文PDF相对路径",
    "补充材料状态汇总",
    "补充材料数量",
    "补充材料相对路径",
    "处理类别",
    "备注或失败原因",
]

FAILURE_FIELDS = [
    "类别",
    "DOI",
    "题名",
    "来源",
    "状态",
    "失败原因",
    "建议操作",
]


@dataclass(frozen=True)
class StudentHandoffPaths:
    student_dir: Path
    readme_path: Path
    paper_index_path: Path
    paper_index_xlsx_path: Path
    failure_next_steps_path: Path
    library_index_path: Path


def write_student_handoff(
    output_dir: str | Path,
    *,
    resolved_records: Iterable[dict[str, object]] | None = None,
    failed_records: Iterable[dict[str, object]] | None = None,
    pdf_records: Iterable[object] | None = None,
    supplement_records: Iterable[object] | None = None,
    intake_preview_path: str | Path | None = None,
    merged_input_path: str | Path | None = None,
    resolved_path: str | Path | None = None,
    failed_path: str | Path | None = None,
    pdf_report_path: str | Path | None = None,
    supplement_report_path: str | Path | None = None,
) -> StudentHandoffPaths:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    student_dir = root / STUDENT_DIR_NAME
    student_dir.mkdir(parents=True, exist_ok=True)

    resolved_rows = _rows_from_records_or_file(resolved_records, resolved_path)
    failed_rows = _rows_from_records_or_file(failed_records, failed_path)
    pdf_rows = _rows_from_records_or_file(pdf_records, pdf_report_path)
    supplement_rows = _rows_from_records_or_file(supplement_records, supplement_report_path)
    intake_rows = _read_csv_rows(intake_preview_path)
    merged_rows = _read_csv_rows(merged_input_path)

    index_rows = build_paper_index_rows(
        resolved_rows=resolved_rows,
        failed_rows=failed_rows,
        pdf_rows=pdf_rows,
        supplement_rows=supplement_rows,
        intake_rows=intake_rows,
        merged_rows=merged_rows,
    )
    failure_rows = build_failure_next_step_rows(index_rows=index_rows, supplement_rows=supplement_rows)

    paper_index_path = student_dir / PAPER_INDEX_NAME
    _write_csv(paper_index_path, PAPER_INDEX_FIELDS, index_rows)
    library_index_path = root / LIBRARY_INDEX_NAME
    shutil.copyfile(paper_index_path, library_index_path)

    paper_index_xlsx_path = student_dir / PAPER_INDEX_XLSX_NAME
    _write_xlsx(paper_index_xlsx_path, PAPER_INDEX_FIELDS, index_rows)

    failure_path = student_dir / FAILURE_NEXT_STEPS_NAME
    _write_csv(failure_path, FAILURE_FIELDS, failure_rows)

    readme_path = student_dir / README_NAME
    readme_path.write_text(
        _student_readme_text(index_rows=index_rows, failure_rows=failure_rows),
        encoding="utf-8",
    )

    return StudentHandoffPaths(
        student_dir=student_dir,
        readme_path=readme_path,
        paper_index_path=paper_index_path,
        paper_index_xlsx_path=paper_index_xlsx_path,
        failure_next_steps_path=failure_path,
        library_index_path=library_index_path,
    )


def build_paper_index_rows(
    *,
    resolved_rows: list[dict[str, str]],
    failed_rows: list[dict[str, str]],
    pdf_rows: list[dict[str, str]],
    supplement_rows: list[dict[str, str]],
    intake_rows: list[dict[str, str]],
    merged_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    rows_by_doi: dict[str, dict[str, str]] = {}
    order: list[str] = []

    def ensure_row(doi: str, title: str = "", pii: str = "") -> dict[str, str]:
        key = _row_key(doi, title, len(order) + 1)
        if key not in rows_by_doi:
            rows_by_doi[key] = {
                "DOI": doi,
                "PII": pii,
                "题名": title,
                "PDF状态": "",
                "正文PDF相对路径": "",
                "备注或失败原因": "",
                "_key": key,
            }
            order.append(key)
        row = rows_by_doi[key]
        if doi and not row["DOI"]:
            row["DOI"] = doi
        if pii and not row["PII"]:
            row["PII"] = pii
        if title and not row["题名"]:
            row["题名"] = title
        return row

    for source_row in merged_rows:
        ensure_row(_clean(source_row.get("doi")), _clean(source_row.get("title")))

    for source_row in resolved_rows:
        ensure_row(
            _clean(source_row.get("doi")),
            _first(source_row, "title", "题名", "article_title"),
            _clean(source_row.get("pii")),
        )

    for source_row in pdf_rows:
        row = ensure_row(
            _clean(source_row.get("doi")),
            _first(source_row, "title", "题名", "article_title"),
            _clean(source_row.get("pii")),
        )
        row["PDF状态"] = _clean(source_row.get("status")) or row["PDF状态"]
        row["正文PDF相对路径"] = _normalize_relative_path(source_row.get("file")) or row["正文PDF相对路径"]
        row["备注或失败原因"] = _clean(source_row.get("reason")) or row["备注或失败原因"]

    for source_row in intake_rows:
        doi = _clean(source_row.get("doi")) or _clean(source_row.get("input_doi"))
        title = _clean(source_row.get("title")) or _clean(source_row.get("input_title"))
        if doi or title:
            row = ensure_row(doi, title)
            status = _clean(source_row.get("status"))
            reason = _clean(source_row.get("reason"))
            if status and status != "valid" and not row["PDF状态"]:
                row["PDF状态"] = status
            if reason and not row["备注或失败原因"]:
                row["备注或失败原因"] = reason

    for source_row in failed_rows:
        doi = _clean(source_row.get("doi"))
        title = _first(source_row, "title", "题名", "article_title")
        row = ensure_row(doi, title)
        row["PDF状态"] = "failed"
        row["备注或失败原因"] = _clean(source_row.get("reason")) or row["备注或失败原因"]

    supplements_by_doi = _supplement_summary_by_doi(supplement_rows)
    final_rows: list[dict[str, str]] = []
    for index, key in enumerate(order, start=1):
        row = rows_by_doi[key]
        doi = row["DOI"]
        supplement_summary = supplements_by_doi.get(doi.lower(), {})
        status = row["PDF状态"] or "not_requested"
        reason = row["备注或失败原因"]
        category = classify_failure(status=status, reason=reason, doi=doi, source="pdf")
        final_rows.append({
            "序号": str(index),
            "PDF状态": status,
            "DOI": doi,
            "PII": row["PII"],
            "题名": row["题名"],
            "正文PDF相对路径": _normalize_relative_path(row["正文PDF相对路径"]),
            "补充材料状态汇总": str(supplement_summary.get("summary", "")),
            "补充材料数量": str(supplement_summary.get("count", "0")),
            "补充材料相对路径": str(supplement_summary.get("files", "")),
            "处理类别": category,
            "备注或失败原因": reason,
        })

    return final_rows


def build_failure_next_step_rows(
    *,
    index_rows: list[dict[str, str]],
    supplement_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []

    for row in index_rows:
        status = _clean(row.get("PDF状态")).lower()
        category = _clean(row.get("处理类别"))
        if status in {"success", "skipped"} and category == "已完成":
            continue
        if category == "已完成":
            continue
        failures.append({
            "类别": category,
            "DOI": _clean(row.get("DOI")),
            "题名": _clean(row.get("题名")),
            "来源": "paper_index.csv",
            "状态": _clean(row.get("PDF状态")),
            "失败原因": _clean(row.get("备注或失败原因")),
            "建议操作": next_step_for_category(category),
        })

    for row in supplement_rows:
        if _clean(row.get("status")).lower() != "failed":
            continue
        category = "补充材料失败"
        failures.append({
            "类别": category,
            "DOI": _clean(row.get("doi")),
            "题名": _clean(row.get("article_title")),
            "来源": "supplement_download_report.csv",
            "状态": _clean(row.get("status")),
            "失败原因": _clean(row.get("reason")),
            "建议操作": next_step_for_category(category),
        })

    return failures


def classify_failure(*, status: str, reason: str, doi: str, source: str) -> str:
    status_l = _clean(status).lower()
    reason_l = _clean(reason).lower()
    doi_l = _clean(doi).lower()
    joined = f"{status_l} {reason_l}"

    if status_l in {"success", "skipped", "scihub_downloaded"} and not reason_l.startswith("pdf download failed"):
        return "已完成"
    if source == "supplement":
        return "补充材料失败"
    if "duplicate" in joined or "重复" in joined:
        return "重复输入"
    if "empty" in joined or "doi 为空" in joined or "空 doi" in joined or (not doi_l and status_l == "failed"):
        return "需补 DOI/文献信息"
    if doi_l and not doi_l.startswith("10.1016/"):
        return "非 ScienceDirect"
    if "no_institutional_pdf_access" in joined or "no entitlement" in joined or "权限" in joined or "entitlement" in joined:
        return "无机构权限"
    if any(marker in joined for marker in ("captcha", "rate_limit", "blocked", "403", "forbidden", "access denied", "verify you are human", "验证码", "限速", "封锁")):
        return "验证码或限速"
    if any(marker in joined for marker in ("response_not_pdf", "not pdf", "non-pdf", "非 pdf", "非pdf", "响应非 pdf", "响应不是 pdf")):
        return "响应不是 PDF"
    if status_l in {"not_requested", "dry_run", "preflight"} or reason_l in {"preflight", "dry_run", "no_download_pdfs"}:
        return "未请求下载"
    return "可重试 PDF 失败"


def next_step_for_category(category: str) -> str:
    return {
        "需补 DOI/文献信息": "补齐 DOI、完整题名、期刊、年份或卷页后重新预检。",
        "非 ScienceDirect": "改用合法 OA 流程，或人工确认该 DOI 是否属于 Elsevier/ScienceDirect。",
        "重复输入": "无需重试；保留首次记录即可。",
        "无机构权限": "在校内网络、VPN 或 CARSI 环境确认机构是否有正文 PDF 权限。",
        "验证码或限速": "暂停下载，检查调试浏览器中的验证码或限速提示，稍后小批量重试。",
        "响应不是 PDF": "打开 pdf_download_report.csv 对应链接和浏览器状态，确认是否返回登录页、HTML 或错误页。",
        "补充材料失败": "查看 supplement_download_report.csv；必要时手工打开附件链接或稍后重试。",
        "未请求下载": "这是预检、dry-run 或未启用 PDF 下载的记录；确认后再正式下载。",
        "可重试 PDF 失败": "生成重试 DOI CSV，小批量重试；重试前先确认 Cookie 和机构权限。",
        "已完成": "无需处理。",
    }.get(category, "查看对应报告并人工判断下一步。")


def _supplement_summary_by_doi(rows: list[dict[str, str]]) -> dict[str, dict[str, str | int]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        doi = _clean(row.get("doi")).lower()
        if doi:
            grouped[doi].append(row)

    result: dict[str, dict[str, str | int]] = {}
    for doi, items in grouped.items():
        counts = Counter(_clean(item.get("status")).lower() or "unknown" for item in items)
        summary = "；".join(f"{status}:{count}" for status, count in sorted(counts.items()))
        files = [
            _normalize_relative_path(item.get("file"))
            for item in items
            if _normalize_relative_path(item.get("file"))
        ]
        result[doi] = {
            "summary": summary,
            "count": len(files),
            "files": "；".join(files),
        }
    return result


def _rows_from_records_or_file(records: Iterable[object] | None, path: str | Path | None) -> list[dict[str, str]]:
    if records is not None:
        return [_object_to_row(record) for record in records]
    return _read_csv_rows(path)


def _object_to_row(record: object) -> dict[str, str]:
    if isinstance(record, dict):
        return {str(key): _clean(value) for key, value in record.items()}
    if hasattr(record, "__dataclass_fields__"):
        return {name: _clean(getattr(record, name, "")) for name in record.__dataclass_fields__}
    return {}


def _read_csv_rows(path: str | Path | None) -> list[dict[str, str]]:
    if not path:
        return []
    csv_path = Path(path)
    if not csv_path.exists() or csv_path.suffix.lower() != ".csv":
        return []
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk", "cp936"):
        try:
            with csv_path.open("r", newline="", encoding=encoding) as f:
                return [{str(k): _clean(v) for k, v in row.items()} for row in csv.DictReader(f)]
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error:
        raise ValueError(f"无法读取 CSV 编码: {csv_path}") from last_error
    return []


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _write_xlsx(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    try:
        from openpyxl import Workbook
    except ImportError:
        return

    wb = Workbook()
    ws = wb.active
    ws.title = "paper_index"
    ws.append(fieldnames)
    for row in rows:
        ws.append([row.get(field, "") for field in fieldnames])
    for column_cells in ws.columns:
        max_length = max(len(str(cell.value or "")) for cell in column_cells)
        ws.column_dimensions[column_cells[0].column_letter].width = min(max(max_length + 2, 10), 60)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def _student_readme_text(*, index_rows: list[dict[str, str]], failure_rows: list[dict[str, str]]) -> str:
    status_counts = Counter(row.get("PDF状态", "") or "unknown" for row in index_rows)
    lines = [
        "研究生文献查看说明",
        "==================",
        "",
        "先打开 paper_index.xlsx；如果电脑没有 Excel/WPS，就打开 paper_index.csv。",
        "这个目录只放索引和说明，不复制 PDF 或补充材料，避免占用双倍空间。",
        "",
        "路径说明:",
        "- 正文 PDF 相对路径指向上级输出目录里的 pdfs\\。",
        "- 补充材料相对路径指向上级输出目录里的 supplements\\。",
        "- supplement 状态 not_found 表示网页中没有检测到可下载附件链接，不代表正文 PDF 下载失败。",
        "",
        "合规边界:",
        "- 只使用学校/机构已有权限、Cookie JSON、浏览器登录或合法开放获取来源。",
        "",
        "- Cookie 和调试浏览器目录属于凭据状态，不要上传、转发或提交到 Git。",
        "",
        "本次统计:",
    ]
    if status_counts:
        for status, count in sorted(status_counts.items()):
            lines.append(f"- PDF状态 {status}: {count}")
    else:
        lines.append("- 无论文记录")
    lines.extend([
        f"- 失败/待处理项: {len(failure_rows)}",
        "",
        "处理失败项:",
        "- 先打开 失败项_下一步处理.csv，按类别处理。",
        "- 不要反复大批量重试同一批失败 DOI；先确认 Cookie、机构权限、验证码、限速或 DOI 信息是否正确。",
        "- 需要重试时，优先小批量重试。",
        "",
    ])
    return "\n".join(lines)


def _row_key(doi: str, title: str, fallback_index: int) -> str:
    if doi:
        return f"doi:{doi.lower()}"
    if title:
        return f"title:{title.lower()}"
    return f"row:{fallback_index}"


def _first(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = _clean(row.get(key))
        if value:
            return value
    return ""


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_relative_path(value: object) -> str:
    text = _clean(value)
    if not text:
        return ""
    return text.replace("/", "\\")
