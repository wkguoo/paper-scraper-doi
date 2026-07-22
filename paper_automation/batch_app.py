"""Application-facing helpers shared by the unified batch CLI and UI.

This module deliberately contains no Tkinter or argparse code.  It provides a
small, typed boundary for command construction, read-only status inspection,
Zotero defaults, and stable exit-code decisions.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .batch_workflow import (
    SUCCESS_STATUSES,
    batch_state_lock,
    load_batch_state,
    paths_from_run_dir,
    result_from_state,
)
from .failure_routing import classify_failure_next_hop


UNIFIED_BATCH_ACTIONS = (
    "start",
    "resume",
    "retry-failed",
    "recover-oa",
    "zotero",
    "status",
)
DEFAULT_ZOTERO_WAIT_SECONDS = 0
STATUS_SCHEMA_VERSION = 1
RECOVER_TRANSIENT_STATUSES = frozenset({"recovery_timeout", "publisher_unreachable"})


@dataclass(frozen=True)
class BatchCommandRequest:
    """Typed command request used by the unified UI command adapter."""

    action: str
    run_dir: str = ""
    input_path: str = ""
    input_text: str = ""
    output_root: str = ""
    run_name: str = ""
    email: str = ""
    cookies: str = ""
    library_id: int = 1
    wait_seconds: int = DEFAULT_ZOTERO_WAIT_SECONDS
    auto_zotero: bool = True
    extra_args: tuple[str, ...] = ()

    def to_argv(self) -> list[str]:
        if self.action not in UNIFIED_BATCH_ACTIONS:
            raise ValueError("invalid_batch_action")
        if not 0 <= int(self.wait_seconds) <= 86400:
            raise ValueError("bridge_wait_seconds_invalid")
        argv = [self.action]
        if self.action == "start":
            if self.input_path:
                argv += ["--input", self.input_path]
            elif self.input_text:
                argv += ["--text", self.input_text]
            else:
                raise ValueError("empty_input")
            if self.output_root:
                argv += ["--out", self.output_root]
            if self.run_name:
                argv += ["--run-name", self.run_name]
            if self.email:
                argv += ["--email", self.email]
            if self.cookies:
                argv += ["--cookies", self.cookies]
        else:
            if not self.run_dir:
                raise ValueError("batch_run_dir_missing")
            argv += ["--run-dir", self.run_dir]
            if self.action == "recover-oa" and self.email:
                argv += ["--email", self.email]
        if self.action in {"start", "retry-failed", "recover-oa"}:
            argv.append("--auto-zotero" if self.auto_zotero else "--no-auto-zotero")
        if self.action in {"start", "retry-failed", "recover-oa", "zotero"}:
            argv += ["--library-id", str(int(self.library_id))]
            argv += ["--wait-seconds", str(int(self.wait_seconds))]
        argv.extend(self.extra_args)
        return argv


@dataclass(frozen=True)
class BatchStatusSummary:
    schema_version: int
    run_dir: str
    total: int
    completed: int
    active: int
    expired: int
    waiting_zotero: int
    review: int
    retryable: int
    unresolved: int
    complete: bool
    next_action: str
    next_command: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    def to_text(self) -> str:
        lines = [
            f"批次：{self.run_dir}",
            f"已完成：{self.completed}/{self.total}",
            f"处理中：{self.active}",
            f"租约已过期：{self.expired}",
            f"等待 Zotero：{self.waiting_zotero}",
            f"需人工核对：{self.review}",
            f"可重试：{self.retryable}",
            f"未解决：{self.unresolved}",
        ]
        if self.next_command:
            lines.append(f"下一步：{self.next_command}")
        elif self.complete:
            lines.append("状态：批次已完成")
        return "\n".join(lines)


@dataclass(frozen=True)
class BatchCommandResult:
    exit_code: int
    status: str
    messages: tuple[str, ...] = ()
    batch_status: BatchStatusSummary | None = None
    payload: dict[str, object] = field(default_factory=dict)


def _parse_utc_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid_batch_state_active_attempts")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid_batch_state_active_attempts") from exc
    if parsed.tzinfo is None:
        raise ValueError("invalid_batch_state_active_attempts")
    return parsed.astimezone(timezone.utc)


def inspect_batch_status(
    run_dir: str | Path,
    *,
    now: datetime | None = None,
) -> BatchStatusSummary:
    """Return a validated, strictly read-only summary of one batch."""

    root = Path(run_dir).expanduser().resolve()
    state_path = root / "working" / "batch_state.json"
    with batch_state_lock(root):
        before = state_path.read_bytes()
        state = load_batch_state(root)
        paths = paths_from_run_dir(root)
        result = result_from_state(paths, state)
        after = state_path.read_bytes()
    if before != after:
        raise RuntimeError("status_read_modified_state")

    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    clock = clock.astimezone(timezone.utc)
    attempts = state.get("active_attempts") or {}
    active_ids: set[str] = set()
    expired_ids: set[str] = set()
    for task_id, record in attempts.items():
        expiry = _parse_utc_timestamp(record.get("lease_expires_at"))
        (active_ids if expiry > clock else expired_ids).add(str(task_id))

    review = 0
    retryable = 0
    waiting = 0
    for row in state.get("rows", []):
        task_id = str(row.get("task_id", ""))
        if task_id in active_ids or task_id in expired_ids:
            continue
        status = str(row.get("status", "") or "")
        if status in SUCCESS_STATUSES or status == "duplicate":
            continue
        hop = classify_failure_next_hop(
            status,
            row.get("reason", ""),
            doi=row.get("doi") or row.get("input_doi") or "",
        )
        if hop == "zotero":
            waiting += 1
        elif hop == "retry":
            retryable += 1
        else:
            review += 1

    complete = result.success_count == result.total_count or (
        result.failed_count == 0 and not active_ids and not expired_ids
    )
    if active_ids:
        next_action, next_command = "wait", "请等待当前处理完成后再次查看状态"
    elif expired_ids:
        next_action = "retry-failed"
        next_command = f'paper_batch.py retry-failed --run-dir "{root}"'
    elif result.manual_retry_count:
        next_action = "resume"
        next_command = f'paper_batch.py resume --run-dir "{root}"'
    elif waiting or result.zotero_fallback_count:
        next_action = "zotero"
        next_command = f'paper_batch.py zotero --run-dir "{root}"'
    elif retryable:
        next_action = "retry-failed"
        next_command = f'paper_batch.py retry-failed --run-dir "{root}"'
    elif review:
        next_action, next_command = "review", "请查看 下载清单.csv 中的失败原因"
    else:
        next_action, next_command = "complete", ""

    return BatchStatusSummary(
        schema_version=STATUS_SCHEMA_VERSION,
        run_dir=str(root),
        total=result.total_count,
        completed=result.success_count,
        active=len(active_ids),
        expired=len(expired_ids),
        waiting_zotero=max(waiting, result.zotero_fallback_count),
        review=review,
        retryable=retryable,
        unresolved=result.failed_count,
        complete=complete,
        next_action=next_action,
        next_command=next_command,
    )


def recover_oa_exit_code(
    recovered: Iterable[object],
    *,
    bridge_exit_code: int | None = None,
    batch_complete: bool = False,
) -> int:
    """Apply the public recover-oa exit-code contract."""

    if bridge_exit_code in {2, 3}:
        return int(bridge_exit_code)
    items = list(recovered)
    if batch_complete or not items:
        return 0
    statuses = {str(getattr(item, "status", "") or "") for item in items}
    if statuses and statuses <= {"oa_downloaded"}:
        return 0
    if statuses & RECOVER_TRANSIENT_STATUSES:
        return 5
    for item in items:
        attempts = getattr(item, "attempts", ()) or ()
        if any(str(getattr(attempt, "result", "")) == "publisher_unreachable" for attempt in attempts):
            return 5
    return 4
