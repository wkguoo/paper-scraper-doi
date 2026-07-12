"""面向初学者的项目优先文献批次命令行入口。"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence

from paper_automation.batch_stages import BatchOptions
from paper_automation.batch_workflow import (
    ZOTERO_RESULT_FIELDS,
    BatchRunResult,
    finalize_batch,
    resume_batch,
    start_batch,
)
from paper_automation.zotero_bridge import run_zotero_bridge


_BRIDGE_GENERIC_HINT = (
    "Zotero 本地桥接请求、清单或结果无效，请不要手工修改 JSON/CSV，"
    "并重新运行同一条命令。"
)
_BRIDGE_VALIDATION_CODES = frozenset({
    "bridge_batch_identity_invalid",
    "bridge_batch_jobs_invalid",
    "bridge_batch_manifest_conflict",
    "bridge_chunk_count_invalid",
    "bridge_chunk_index_invalid",
    "bridge_fallback_empty",
    "bridge_fallback_fields_invalid",
    "bridge_fallback_file_missing",
    "bridge_fallback_state_mismatch",
    "bridge_fallback_task_duplicate",
    "bridge_fallback_task_unknown",
    "bridge_item_count_invalid",
    "bridge_item_fields_invalid",
    "bridge_item_value_invalid",
    "bridge_job_count_invalid",
    "bridge_job_id_conflict",
    "bridge_job_id_duplicate",
    "bridge_job_id_invalid",
    "bridge_library_id_invalid",
    "bridge_localappdata_missing",
    "bridge_manifest_chunks_invalid",
    "bridge_manifest_fields_invalid",
    "bridge_manifest_hash_invalid",
    "bridge_manifest_invalid",
    "bridge_manifest_job_fields_invalid",
    "bridge_manifest_job_id_duplicate",
    "bridge_manifest_job_id_invalid",
    "bridge_manifest_jobs_invalid",
    "bridge_manifest_library_id_invalid",
    "bridge_manifest_payload_hash_invalid",
    "bridge_manifest_schema_version_invalid",
    "bridge_manifest_shared_values_invalid",
    "bridge_manifest_task_duplicate",
    "bridge_manifest_task_ids_invalid",
    "bridge_manifest_time_invalid",
    "bridge_manifest_value_invalid",
    "bridge_payload_hash_invalid",
    "bridge_poll_seconds_invalid",
    "bridge_request_fields_invalid",
    "bridge_request_identity_invalid",
    "bridge_request_invalid",
    "bridge_request_missing",
    "bridge_request_rows_invalid",
    "bridge_request_time_invalid",
    "bridge_request_value_invalid",
    "bridge_result_count_invalid",
    "bridge_result_expected_tasks_invalid",
    "bridge_result_fields_invalid",
    "bridge_result_filename_exhausted",
    "bridge_result_identity_invalid",
    "bridge_result_invalid",
    "bridge_result_item_id_missing",
    "bridge_result_missing",
    "bridge_result_row_fields_invalid",
    "bridge_result_row_value_invalid",
    "bridge_result_status_invalid",
    "bridge_result_task_duplicate",
    "bridge_result_task_unknown",
    "bridge_result_tasks_missing",
    "bridge_result_time_invalid",
    "bridge_result_value_invalid",
    "bridge_schema_version_invalid",
    "bridge_state_rows_invalid",
    "bridge_state_task_invalid",
    "bridge_task_id_duplicate",
    "bridge_task_id_missing",
    "bridge_wait_seconds_invalid",
    "bridge_working_missing",
})


ERROR_HINTS = {
    **dict.fromkeys(_BRIDGE_VALIDATION_CODES, _BRIDGE_GENERIC_HINT),
    "zotero_results_fields_invalid": (
        "请将 Zotero 结果 CSV 表头严格设置为 "
        "task_id,zotero_item_id,attachment_path,status,reason。"
    ),
    "zotero_results_file_missing": "请确认 Zotero 结果文件存在，并检查 --zotero-results 路径。",
    "file_missing": "请确认输入文件存在，并检查命令中的文件路径。",
    "zotero_result_status_invalid": "请检查 Zotero 结果 CSV 的 status 值是否属于允许范围。",
    "status_invalid": "请检查结果文件中的 status 值是否属于允许范围。",
    "invalid_batch_state": "请确认 --run-dir 指向完整且未损坏的批次状态目录。",
    "invalid_batch_state_options": "批次状态中的安全参数无效，请重新创建批次。",
    "invalid_batch_state_run_dir": "批次状态目录不匹配，请使用创建该批次时的 run_dir。",
    "cookies_must_be_path": "请为 --cookies 提供 Cookie JSON 文件路径，不要粘贴 Cookie 内容。",
    "empty_input": "请通过 --text 或 --input 提供至少一条文献记录。",
    "manual_retry_file_missing": "人工重试清单不存在，请检查批次目录是否完整。",
    "manual_retry_fields_invalid": "人工重试清单表头无效，请保留批次自动生成的 CSV。",
    "manual_retry_task_id_invalid": "人工重试清单包含无效任务编号，请使用原始清单。",
    "manual_retry_unknown_task_id": "人工重试清单包含未知任务，请使用原始清单。",
    "manual_retry_status_invalid": "人工重试清单包含不可重试状态，请使用原始清单。",
    "manual_retry_state_not_pending": "人工重试清单与当前批次状态不一致，请重新检查批次。",
    "manual_retry_status_mismatch": "人工重试清单状态不一致，请勿手工修改该 CSV。",
    "manual_retry_task_ids_mismatch": "人工重试清单任务集合不一致，请勿增删 CSV 行。",
    "bridge_wait_seconds_invalid": "--wait-seconds 必须是 0 到 86400 之间的整数。",
    "bridge_poll_seconds_invalid": "桥接轮询参数无效，请使用默认设置后重试。",
    "bridge_localappdata_missing": "未找到 Windows LOCALAPPDATA，无法建立 Zotero 本地桥接目录。",
    "bridge_fallback_file_missing": "Zotero 回退清单不存在，请确认 --run-dir 指向完整批次。",
    "bridge_fallback_fields_invalid": "Zotero 回退清单表头无效，请保留项目自动生成的 CSV。",
    "bridge_fallback_state_mismatch": "Zotero 回退清单与当前批次状态不一致，请不要手工修改它。",
    "bridge_batch_manifest_conflict": "桥接清单与当前回退条目不一致，请不要手工修改桥接文件。",
    "bridge_manifest_invalid": "桥接批次清单无效或不完整，请检查本地桥接文件后重新创建批次。",
    "bridge_job_id_conflict": "桥接作业编号冲突，请不要手工复制或覆盖桥接 JSON。",
    "bridge_result_missing": "Zotero 尚未返回全部子作业结果，请在 Zotero 中确认后重新运行同一条命令。",
    "bridge_result_fields_invalid": "Zotero 插件结果字段无效，请保留插件自动生成的结果文件。",
    "bridge_result_identity_invalid": "Zotero 插件结果不属于当前桥接作业，请不要混用结果文件。",
    "bridge_result_status_invalid": "Zotero 插件结果的 status 不属于允许范围。",
    "bridge_result_tasks_missing": "Zotero 插件结果未覆盖当前批次的全部条目。",
    "bridge_result_invalid": "Zotero 插件结果文件无效或尚未完整写入，请稍后重试。",
}

_SAFE_ERROR_CODE = re.compile(r"^\s*([a-z][a-z0-9_]{0,127})(?=\b|:)")


def build_parser() -> argparse.ArgumentParser:
    """创建中文命令行解析器，不在此处执行任何下载。"""

    parser = argparse.ArgumentParser(
        description=(
            "项目优先的批量 PDF 工作流：支持 TXT/MD/CSV/XLSX/XLSM；"
            "仅使用合法 OA/授权访问；登录或验证码项目只重试一次；"
            "Zotero 附件以非破坏复制方式归并。"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="创建批次并执行 OA/授权访问阶段")
    source = start.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="文献清单：TXT/MD/CSV/XLSX/XLSM")
    source.add_argument("--text", help="直接粘贴的 DOI 或文献文本")
    start.add_argument("--out", default="results", help="批次输出根目录（默认：results）")
    start.add_argument("--run-name", help="可选的批次名称")
    start.add_argument("--email", default="", help="用于合法 OA 查询的邮箱（可选）")
    start.add_argument("--cookies", default="", help="授权访问 Cookie 的 JSON 文件路径（可选）")
    start.add_argument(
        "--browser-exe",
        default="",
        help="显式指定外部浏览器路径（未指定时默认 Edge，然后 Chrome）",
    )
    start.add_argument("--login-wait-seconds", type=int, default=0, help="登录等待秒数")
    start.add_argument("--debug-port", type=int, default=9333, help="浏览器调试端口")
    start.add_argument("--throttle-seconds", type=float, default=1.0, help="请求间隔秒数")

    resume = subparsers.add_parser("resume", help="仅重试一次登录或验证码失败条目")
    resume.add_argument("--run-dir", required=True, help="已有批次目录")

    finalize = subparsers.add_parser("finalize", help="归并 Zotero 附件并生成最终报告")
    finalize.add_argument("--run-dir", required=True, help="已有批次目录")
    finalize.add_argument("--zotero-results", required=True, help="Zotero 结果 CSV 文件")

    zotero = subparsers.add_parser("zotero", help="把项目失败项交给 Zotero 9 本地桥接")
    zotero.add_argument("--run-dir", required=True, help="已有批次目录")
    zotero.add_argument("--library-id", type=int, default=1, help="目标 Zotero 文库 ID（默认：1）")
    zotero.add_argument("--wait-seconds", type=int, default=0, help="等待 Zotero 结果的秒数（0-86400）")
    return parser


def _quote_powershell(value: object) -> str:
    """使用 PowerShell 单引号，并把内部单引号转义为两个单引号。"""

    return "'" + str(value).replace("'", "''") + "'"


def _powershell_command(command: str, *arguments: object) -> str:
    """生成可从任意当前目录执行的 PowerShell 命令。"""

    parts = [
        "&",
        _quote_powershell(Path(sys.executable).resolve()),
        _quote_powershell(Path(__file__).resolve()),
        _quote_powershell(command),
    ]
    for argument in arguments:
        parts.append(_quote_powershell(argument))
    return " ".join(parts)


def _finalize_command(
    result: BatchRunResult,
    selected_results: Path | None = None,
) -> str:
    results_path = selected_results or result.paths.zotero_results
    return _powershell_command(
        "finalize",
        "--run-dir",
        Path(result.paths.root).expanduser().resolve(),
        "--zotero-results",
        Path(results_path).expanduser().resolve(),
    )


def _write_header_only_exclusive(path: Path) -> None:
    with path.open("x", newline="", encoding="utf-8-sig") as handle:
        csv.writer(handle).writerow(ZOTERO_RESULT_FIELDS)


def _is_exact_header_only_zotero_results(path: Path) -> bool:
    try:
        raw = path.read_bytes()
        if not raw.startswith(b"\xef\xbb\xbf"):
            return False
        text = raw[3:].decode("utf-8")
        records = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except (OSError, UnicodeDecodeError, csv.Error):
        return False
    return records == [ZOTERO_RESULT_FIELDS]


def _retry_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _create_header_only_retry(parent: Path) -> Path:
    stem = f"zotero_results_retry_{_retry_timestamp()}"
    sequence = 1
    while True:
        suffix = "" if sequence == 1 else f"_{sequence}"
        candidate = parent / f"{stem}{suffix}.csv"
        try:
            _write_header_only_exclusive(candidate)
        except FileExistsError:
            sequence += 1
            continue
        return candidate


def _ensure_header_only_zotero_results(result: BatchRunResult) -> tuple[Path, bool]:
    path = Path(result.paths.zotero_results).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _write_header_only_exclusive(path)
    except FileExistsError:
        if _is_exact_header_only_zotero_results(path):
            return path, False
        return _create_header_only_retry(path.parent), True
    return path, True


def _print_summary(result: BatchRunResult) -> None:
    print(f"运行目录：{result.paths.root}")
    print(f"最终 PDF 目录：{result.paths.pdfs}")
    print(f"总计：{result.total_count}")
    print(f"成功：{result.success_count}")
    print(f"失败：{result.failed_count}")
    print(f"待人工重试：{result.manual_retry_count}")
    print(f"待 Zotero 回退：{result.zotero_fallback_count}")
    print(f"人工重试清单：{result.paths.manual_retry}")
    print(f"Zotero 回退清单：{result.paths.zotero_fallback}")
    print(f"报告目录：{result.paths.reports}")


def _print_next_step(result: BatchRunResult) -> None:
    if result.manual_retry_count > 0:
        print("下一步：完成登录或验证码后，只能重试一次：")
        print(_powershell_command(
            "resume",
            "--run-dir",
            Path(result.paths.root).expanduser().resolve(),
        ))
        return
    if result.zotero_fallback_count > 0:
        print("下一步：请在 Zotero 中处理回退条目；附件将以非破坏复制方式归并。")
        print(f"默认结果文件：{result.paths.zotero_results}")
        print("完成后运行：")
        print(_finalize_command(result))
        return
    results_path, created = _ensure_header_only_zotero_results(result)
    if created:
        print("下一步：已自动创建 UTF-8-SIG 的仅表头 Zotero 结果文件。")
    else:
        print("下一步：Zotero 结果文件已存在，已保留且未覆盖。")
    print(f"Zotero 结果文件绝对路径：{results_path}")
    print(f"精确表头：{','.join(ZOTERO_RESULT_FIELDS)}")
    print("可直接执行：")
    print(_finalize_command(result, results_path))


def _known_error_code(error: Exception) -> str | None:
    match = _SAFE_ERROR_CODE.match(str(error))
    if match is None:
        return None
    code = match.group(1)
    return code if code in ERROR_HINTS else None


def _print_error(error: Exception) -> None:
    code = _known_error_code(error)
    if code is None:
        message = f"错误码 2：{type(error).__name__}。批次工作流未完成，请检查输入路径和批次状态。"
    else:
        message = f"错误码 2：{code}。{ERROR_HINTS[code]}"
    print(message, file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    """解析参数、调用批次工作流，并返回适合脚本使用的退出码。"""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            result = start_batch(
                input_text=args.text,
                input_path=args.input,
                output_root=args.out,
                run_name=args.run_name,
                options=BatchOptions(
                    email=args.email,
                    cookies=args.cookies,
                    browser_exe=args.browser_exe,
                    login_wait_seconds=args.login_wait_seconds,
                    debug_port=args.debug_port,
                    throttle_seconds=args.throttle_seconds,
                ),
            )
        elif args.command == "resume":
            result = resume_batch(args.run_dir)
        elif args.command == "finalize":
            result = finalize_batch(args.run_dir, args.zotero_results)
        else:
            bridge_run = run_zotero_bridge(
                args.run_dir,
                library_id=args.library_id,
                wait_seconds=args.wait_seconds,
            )
            if bridge_run.status == "awaiting_confirmation":
                if bridge_run.bridge is None:
                    raise RuntimeError("bridge_batch_result_missing")
                print(f"桥接任务：{len(bridge_run.bridge.jobs)} 个子作业")
                print("请在 Zotero 中确认一次；确认后重新运行同一条命令即可继续。")
                print(f"批次目录：{Path(args.run_dir).expanduser().resolve()}")
                return 3
            if bridge_run.batch_result is None:
                raise RuntimeError("bridge_batch_result_missing")
            result = bridge_run.batch_result

        _print_summary(result)
        if args.command in {"finalize", "zotero"}:
            if result.failed_count == 0 and result.zotero_fallback_count == 0:
                print(f"批次已完成。最终 PDF 目录：{result.paths.pdfs}")
            else:
                unresolved_count = max(
                    result.failed_count,
                    result.zotero_fallback_count,
                )
                print("报告已更新。批次未完成且可恢复。")
                print(f"未解决数量：{unresolved_count}")
                print(f"最终 PDF 目录：{result.paths.pdfs}")
        else:
            _print_next_step(result)
    except (ValueError, OSError, RuntimeError) as error:
        _print_error(error)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
