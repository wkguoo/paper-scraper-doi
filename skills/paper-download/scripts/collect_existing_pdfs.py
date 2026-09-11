"""用 Codex Zotero 插件只读查库，为现有批次生成附件交接 CSV。

请在 paper-scraper-doi 项目根目录运行；不下载、不修改 Zotero，也不自动 finalize。
输入：--run-dir 和官方插件 --zotero-helper；输出：working/结果 CSV、reports/查询报告。
退出 0 表示全部匹配；2 表示有未解决项或输入错误。有成功行时仍可 finalize。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import runpy
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

# 安装到个人技能目录后，项目模块仍从运行命令的项目根目录读取。
sys.path.insert(0, str(Path.cwd()))
from doi_batch_utils import clean_doi
from paper_automation import batch_workflow as workflow


REPORT_FIELDS = [
    "task_id", "doi", "prior_status", "prior_reason", "status", "reason",
    "zotero_item_id", "candidates",
]
SUPPLEMENT_RE = re.compile(
    r"\b(?:supplement(?:al|ary)?|supporting)[ _-]+(?:information|materials?|data|files?)\b"
    r"|补充材料|补充信息",
    re.IGNORECASE,
)
# 识别出版社文件名和附件标题末尾的明确标识；不把正文中的 Si 当作补充材料。
SUPPLEMENT_SUFFIX_RE = re.compile(
    r"(?:^|[ _-])(?:mmc\d+|moesm\d+[ _-]esm|supplement(?:al|ary)?)(?:\.pdf)?$",
    re.IGNORECASE,
)


def normalized_doi(value: object) -> str:
    return clean_doi(str(value or "")).lower()


def pending_rows(run_dir: Path) -> list[dict]:
    """核对用户指定批次和项目生成的失败清单，不接受手改或过期的任务集合。"""
    if (run_dir / "working" / "zotero_bridge_jobs.json").exists():
        raise ValueError("existing_bridge_batch_use_paper_batch_zotero")
    state = workflow.load_batch_state(run_dir)
    workflow._validate_state(state, expected_run_dir=run_dir)
    expected = []
    if not state["options"].get("api_only", False):
        _, expected = workflow._pending_rows(
            state["rows"], manual_retry_used=state["manual_retry_used"],
        )
    expected = [
        {field: str(row.get(field, "") or "").strip() for field in workflow.NORMALIZED_FIELDS}
        for row in expected
    ]
    path = run_dir / "working" / "zotero_fallback.csv"
    with path.open(newline="", encoding="utf-8-sig") as handle:
        records = list(csv.reader(handle, strict=True))
    if not records or records[0] != workflow.NORMALIZED_FIELDS:
        raise ValueError("fallback_fields_invalid")
    rows = []
    for values in records[1:]:
        if not any(value.strip() for value in values):
            continue
        if len(values) != len(workflow.NORMALIZED_FIELDS):
            raise ValueError("fallback_row_invalid")
        rows.append(dict(zip(workflow.NORMALIZED_FIELDS, (v.strip() for v in values))))
    if rows != expected:
        raise ValueError("fallback_state_mismatch")
    return rows


def official_reader(helper_path: Path):
    """复用官方脚本的请求函数；不调用 enable、restart、import 或配置文件探测。"""
    if not helper_path.is_file():
        raise ValueError("official_helper_missing")
    helper = runpy.run_path(str(helper_path), run_name="codex_zotero_readonly")
    request, parse_body = helper.get("request"), helper.get("parse_body")
    if not callable(request) or not callable(parse_body):
        raise ValueError("official_helper_interface_unavailable")

    def read(path: str):
        response = request(path, method="GET", timeout=10)
        if response.status != 200:
            # 不把响应正文、认证信息或配置内容写入报告。
            code = f"http_{response.status}" if response.status is not None else "connection_unavailable"
            raise RuntimeError(f"zotero_api_{code}")
        return parse_body(response)

    return read


def local_file_path(file_url: str) -> Path:
    """官方接口返回 file URL；Windows 的盘符、空格、中文由标准库解码。"""
    if not isinstance(file_url, str):
        raise ValueError("attachment_file_url_invalid")
    url = urlsplit(file_url.strip())
    if url.scheme != "file" or url.netloc not in {"", "localhost"} or url.query or url.fragment:
        raise ValueError("attachment_not_local_file_url")
    path = Path(url2pathname(url.path))
    if not path.is_absolute():
        raise ValueError("attachment_path_not_absolute")
    return path


def item_key(item: dict) -> str:
    key = item.get("key", "")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Z0-9]{8}", key):
        raise ValueError("zotero_item_key_invalid")
    return key


def find_attachment(item: dict, read) -> tuple[str, str, str, list[dict]]:
    parent_key = item_key(item)
    children = read(f"/api/users/0/items/{parent_key}/children")
    if not isinstance(children, list):
        raise ValueError("zotero_children_invalid")
    candidates, valid = [], {}
    for attachment in children:
        data = attachment["data"]
        if data.get("itemType") != "attachment" or data.get("contentType") != "application/pdf":
            continue
        key = item_key(attachment)
        candidate = {"key": key, "title": data.get("title", ""), "status": ""}
        candidates.append(candidate)
        label = f"{data.get('title', '')} {data.get('filename', '')}".replace("_", " ")
        supplement_label = re.fullmatch(
            r"supplement(?:al|ary)?|supporting information|si|esm",
            str(data.get("title", "")).strip(), re.IGNORECASE,
        )
        supplement_filename = re.fullmatch(
            r"(?:si|esm|suppl)(?:[_ -]?\d+)?|mmc\d+",
            Path(data.get("filename", "")).stem, re.IGNORECASE,
        )
        supplement_suffix = any(
            SUPPLEMENT_SUFFIX_RE.search(str(data.get(field, "")).strip())
            for field in ("title", "filename")
        )
        if SUPPLEMENT_RE.search(label) or supplement_label or supplement_filename or supplement_suffix:
            candidate["status"] = "supplement_excluded"
            continue
        try:
            path = local_file_path(read(f"/api/users/0/items/{key}/file/view/url"))
            # 复用交付端已有的路径链和 PDF 内容校验，保留原附件。
            source = workflow._local_zotero_attachment(str(path))
            candidate.update(path=str(source), status="valid_pdf")
            valid.setdefault(workflow._sha256(source), source)
        except (OSError, ValueError, RuntimeError) as exc:
            candidate["status"] = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
    if len(valid) > 1:
        return "metadata_uncertain", "multiple_distinct_pdfs", "", candidates
    if valid:
        return "existing_pdf", "", str(next(iter(valid.values()))), candidates
    return "no_pdf", "no_valid_local_main_pdf", "", candidates


def lookup(rows: list[dict], read) -> tuple[list[dict], list[dict]]:
    # 一次读取个人文库顶层元数据；不检索全文、不导出无关文献或读取 SQLite。
    items = read("/api/users/0/items/top?includeTrashed=0")
    if not isinstance(items, list):
        raise ValueError("zotero_items_invalid")
    wanted = {normalized_doi(row["doi"] or row["input_doi"]) for row in rows}
    index = {}
    for item in items:
        doi = normalized_doi(item["data"].get("DOI"))
        if doi and doi in wanted:
            index.setdefault(doi, []).append(item)
    successes, reports = [], []
    for row in rows:
        doi = normalized_doi(row["doi"] or row["input_doi"])
        report = {
            "task_id": row["task_id"], "doi": doi,
            "prior_status": row["status"], "prior_reason": row["reason"],
            "status": "not_found", "reason": "doi_not_in_library",
            "zotero_item_id": "", "candidates": "[]",
        }
        matches = index.get(doi, [])
        if len(matches) > 1:
            report.update(
                status="metadata_uncertain", reason="multiple_doi_matches",
                candidates=json.dumps([{"key": item_key(item)} for item in matches]),
            )
        elif matches:
            try:
                report["zotero_item_id"] = f"users/0/items/{item_key(matches[0])}"
                status, reason, path, candidates = find_attachment(matches[0], read)
                report.update(status=status, reason=reason, candidates=json.dumps(candidates, ensure_ascii=False))
                if status == "existing_pdf":
                    successes.append({
                        "task_id": row["task_id"], "zotero_item_id": report["zotero_item_id"],
                        "attachment_path": path, "status": status, "reason": "",
                    })
            except (OSError, ValueError, RuntimeError) as exc:
                report.update(status="zotero_api_unavailable", reason=str(exc))
        reports.append(report)
    return successes, reports


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    # 时间标记 + 独占创建，禁止截断旧查询证据。
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def collect(run_dir: Path, helper_path: Path) -> dict:
    root = run_dir.expanduser().resolve()
    rows = pending_rows(root)
    successes, reports = [], []
    if rows:
        try:
            successes, reports = lookup(rows, official_reader(helper_path.expanduser().resolve()))
        except (OSError, ValueError, RuntimeError) as exc:
            reports = [{
                "task_id": row["task_id"], "doi": row["doi"] or row["input_doi"],
                "prior_status": row["status"], "prior_reason": row["reason"],
                "status": "zotero_api_unavailable", "reason": str(exc),
                "zotero_item_id": "", "candidates": "[]",
            } for row in rows]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    results_path = root / "working" / f"zotero_results_existing_{stamp}.csv"
    report_path = root / "reports" / f"zotero_lookup_{stamp}.csv"
    write_csv(report_path, REPORT_FIELDS, reports)
    write_csv(results_path, workflow.ZOTERO_RESULT_FIELDS, successes)
    return {
        "total": len(rows), "matched": len(successes),
        "unresolved": len(rows) - len(successes),
        "results": str(results_path), "report": str(report_path),
        "ready_to_finalize": bool(successes),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--zotero-helper", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = collect(args.run_dir, args.zotero_helper)
    except (OSError, ValueError, RuntimeError, csv.Error) as exc:
        print(f"无法收集：{exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result["unresolved"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
