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
    load_batch_state,
    paths_from_run_dir,
    result_from_state,
    resume_batch,
    retry_failed_batch,
    start_batch,
    user_delivery_dir,
    user_inventory_path,
    write_final_reports,
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
            "【推荐入口】统一批量 PDF 工作流：支持 TXT/MD/CSV/XLSX/XLSM；"
            "合法 OA → 机构访问 → 失败写入 Zotero 回退清单 zotero_fallback（默认跳过人工 resume）；"
            "下载前 DOI 预检；默认不自动排队 Zotero（可选 --auto-zotero）；"
            "同批次失败可 retry-failed 再跑机构。"
            "新任务请用本脚本，不要默认使用 paper_skill.py / sd_scraper.py 等兼容入口。"
        ),
        epilog=(
            "示例：paper_batch.py start --input papers.xlsx --out results --email you@example.com\n"
            "默认固定目录：results/<输入文件名>/（重复 start 会续跑同一目录，不再新建时间戳夹）\n"
            "强制新开一批：paper_batch.py start ... --fresh\n"
            "失败重试：paper_batch.py retry-failed --run-dir <run-dir>\n"
            "有界 OA 补救（非深挖）：paper_batch.py recover-oa --run-dir <run-dir>\n"
            "可选 Zotero：paper_batch.py zotero --run-dir <run-dir> 或 start --auto-zotero\n"
            "兼容入口（非默认）：sd_scraper.py、paper_skill.py、sd_institutional_skill.py、UI 其它页签。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser(
        "start",
        help="创建批次：OA/机构下载；默认跳过人工 resume；Zotero 需显式 --auto-zotero",
    )
    source = start.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="文献清单：TXT/MD/CSV/XLSX/XLSM")
    source.add_argument("--text", help="直接粘贴的 DOI 或文献文本")
    start.add_argument("--out", default="results", help="批次输出根目录（默认：results）")
    start.add_argument(
        "--run-name",
        help="批次文件夹名（默认取输入文件名；固定目录模式下不再加时间戳）",
    )
    start.add_argument(
        "--fixed-run",
        action="store_true",
        default=None,
        help="使用固定批次目录 out/run-name（默认开启，避免多次运行产生多文件夹）",
    )
    start.add_argument(
        "--no-fixed-run",
        action="store_true",
        help="每次新建带时间戳的批次目录（旧行为）",
    )
    start.add_argument(
        "--fresh",
        action="store_true",
        help="忽略已有固定目录，新建带时间戳的批次（仍保留旧目录）",
    )
    start.add_argument("--email", default="", help="用于合法 OA 查询的邮箱（可选）")
    start.add_argument("--cookies", default="", help="授权访问 Cookie 的 JSON 文件路径（可选）")
    start.add_argument(
        "--browser-exe",
        default="",
        help="显式指定外部浏览器路径（未指定时默认 Chrome，然后 Edge）",
    )
    start.add_argument("--login-wait-seconds", type=int, default=0, help="登录等待秒数")
    start.add_argument("--debug-port", type=int, default=9333, help="浏览器调试端口")
    start.add_argument("--throttle-seconds", type=float, default=1.0, help="请求间隔秒数")
    start.add_argument(
        "--enable-manual-retry",
        action="store_true",
        help="兼容：启用 manual_retry/resume 门禁（默认关闭，失败直接进 Zotero 清单）",
    )
    start.add_argument(
        "--auto-zotero",
        action="store_true",
        default=None,
        help="start 结束后若有 fallback 则自动排队 Zotero（默认开启）",
    )
    start.add_argument(
        "--no-auto-zotero",
        action="store_true",
        help="关闭自动 Zotero（仅机构/OA，失败写入 fallback 清单）",
    )
    start.add_argument(
        "--doi-preflight",
        action="store_true",
        default=None,
        help="启用下载前 DOI 校验/题名重匹配（默认开启）",
    )
    start.add_argument(
        "--no-doi-preflight",
        action="store_true",
        help="跳过 DOI 预检",
    )
    start.add_argument(
        "--download-supplements",
        action="store_true",
        default=None,
        help="同时下载 ScienceDirect 补充材料（默认开启）",
    )
    start.add_argument(
        "--no-download-supplements",
        action="store_true",
        help="不下载补充材料",
    )
    start.add_argument(
        "--api-only",
        action="store_true",
        help="仅使用 Elsevier API；禁止浏览器、OA 和 Zotero 兜底",
    )
    start.add_argument(
        "--no-smart-route",
        action="store_true",
        help="关闭智能路由，恢复「全部先 OA 再机构」旧路径",
    )
    start.add_argument(
        "--resolve-title-metadata",
        action="store_true",
        help="对无 DOI 题名做联网元数据增强（默认关闭）",
    )
    start.add_argument(
        "--session-break-seconds",
        type=float,
        default=60.0,
        help="ScienceDirect 每批成功下载后的固定歇息秒数（默认 60；旧版 150）",
    )
    start.add_argument(
        "--session-break-every",
        type=int,
        default=8,
        help="ScienceDirect 每成功下载 N 篇后歇息（默认 8，与旧版相同）",
    )
    start.add_argument("--library-id", type=int, default=1, help="自动 Zotero 时的文库 ID（默认：1）")
    start.add_argument(
        "--wait-seconds",
        type=int,
        default=600,
        help="自动 Zotero 时等待结果的秒数（默认 600；0=只排队）",
    )
    start.add_argument(
        "--no-iucr-short-try",
        action="store_true",
        help="关闭 IUCr 短试策略（默认：机构失败 1 次后熔断 → OA → Zotero）",
    )

    resume = subparsers.add_parser("resume", help="兼容：仅重试一次登录/验证码失败条目（默认批次已跳过）")
    resume.add_argument("--run-dir", required=True, help="已有批次目录")

    retry = subparsers.add_parser(
        "retry-failed",
        help="同批次再跑未成功项；结束后自动 OA 补救并默认排队 Zotero",
    )
    retry.add_argument("--run-dir", required=True, help="已有批次目录")
    retry.add_argument(
        "--include-oa",
        action="store_true",
        help="失败重试时也重跑 OA 阶段（默认只跑机构阶段；limited OA 补救仍会执行）",
    )
    retry.add_argument("--cookies", default="", help="覆盖 Cookie JSON 路径（可选）")
    retry.add_argument("--browser-exe", default="", help="覆盖浏览器路径（可选）")
    retry.add_argument("--email", default="", help="覆盖 OA 邮箱（可选）")
    retry.add_argument("--debug-port", type=int, default=0, help="覆盖调试端口（0=用批次原值）")
    retry.add_argument("--login-wait-seconds", type=int, default=-1, help="覆盖登录等待（-1=原值）")
    retry.add_argument(
        "--retry-all-failed",
        action="store_true",
        help="重试几乎所有非终态失败（默认仅网络/捕获类失败）",
    )
    retry.add_argument(
        "--no-auto-zotero",
        action="store_true",
        help="关闭重试后的自动 Zotero（默认开启）",
    )
    retry.add_argument("--library-id", type=int, default=1, help="自动 Zotero 文库 ID")
    retry.add_argument(
        "--wait-seconds",
        type=int,
        default=600,
        help="自动 Zotero 等待秒数（默认 600；0=只排队）",
    )

    finalize = subparsers.add_parser("finalize", help="归并 Zotero 附件并生成最终报告")
    finalize.add_argument("--run-dir", required=True, help="已有批次目录")
    finalize.add_argument("--zotero-results", required=True, help="Zotero 结果 CSV 文件")

    delivery = subparsers.add_parser(
        "delivery",
        help="仅生成用户交付物：结果/（输入清单、下载清单.csv、pdf、md及可选补充材料）",
    )
    delivery.add_argument("--run-dir", required=True, help="已有批次目录")

    refresh = subparsers.add_parser(
        "refresh-delivery",
        help="A3：扫描 结果/pdf/，重命名为 年份-作者-题名，映射失败 DOI，刷新结果/下载清单.csv",
    )
    refresh.add_argument("--run-dir", required=True, help="已有批次目录")
    refresh.add_argument("--email", default="", help="Crossref 礼貌邮箱（可选）")
    refresh.add_argument(
        "--no-rename",
        action="store_true",
        help="只刷新清单/映射，不改文件名",
    )

    zotero = subparsers.add_parser("zotero", help="把项目失败项交给 Zotero 9 本地桥接（可选）")
    zotero.add_argument("--run-dir", required=True, help="已有批次目录")
    zotero.add_argument("--library-id", type=int, default=1, help="目标 Zotero 文库 ID（默认：1）")
    zotero.add_argument(
        "--wait-seconds",
        type=int,
        default=600,
        help="等待 Zotero 结果的秒数（默认 600；0=只排队）",
    )

    recover = subparsers.add_parser(
        "recover-oa",
        help=(
            "有界 OA/仓储补救（非默认深挖）：元数据 + 至多 1 个标注 PDF URL + 至多 1 个仓储 PDF；"
            "每 DOI 默认 60s；不启浏览器。用于 unsupported_publisher 等失败项。"
        ),
    )
    recover.add_argument("--run-dir", required=True, help="已有批次目录")
    recover.add_argument("--email", default="", help="元数据 API 礼貌邮箱（可选）")
    recover.add_argument(
        "--budget-seconds",
        type=float,
        default=60.0,
        help="每篇 DOI 最长秒数（默认 60）",
    )
    recover.add_argument(
        "--max-workers",
        type=int,
        default=2,
        help="并行 DOI 数（默认 2）",
    )
    recover.add_argument(
        "--only-status",
        default="",
        help="仅处理这些 status（逗号分隔；默认 unsupported_publisher,pending_zotero 等）",
    )
    recover.add_argument(
        "--no-auto-zotero",
        action="store_true",
        help="补救后不自动排队 Zotero（默认：仍有失败则排队）",
    )
    recover.add_argument("--library-id", type=int, default=1, help="自动 Zotero 文库 ID")
    recover.add_argument(
        "--wait-seconds",
        type=int,
        default=600,
        help="自动 Zotero 等待秒数（默认 600；0=只排队）",
    )
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
        Path(result.paths.root).expanduser(),
        "--zotero-results",
        Path(results_path).expanduser(),
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
    inventory = user_inventory_path(result.paths)
    delivery = user_delivery_dir(result.paths)
    print(f"运行目录：{result.paths.root}")
    print(f"下载清单：{inventory}")
    print(f"结果文件夹：{delivery}")
    print(f"总计：{result.total_count}")
    print(f"成功：{result.success_count}")
    print(f"失败：{result.failed_count}")
    print(f"待人工重试：{result.manual_retry_count}")
    print(f"待 Zotero 回退：{result.zotero_fallback_count}")
    # Internal paths kept for recovery; normal use only needs 下载清单 + 结果.
    print(f"（内部）PDF 缓存：{result.paths.pdfs}")
    print(f"（内部）报告：{result.paths.reports}")
    print(f"（内部）Zotero 回退：{result.paths.zotero_fallback}")


def _print_zotero_next_step(result: BatchRunResult, *, queued: bool = False) -> None:
    run_dir = Path(result.paths.root).expanduser()
    if queued:
        print("已自动将失败项排队到 Zotero 本地桥接。")
        print(
            "请保持你要用的那个 Zotero 打开（桥接跟随当前打开的实例，不固定测试配置），"
            "并接受一次批次确认；确认后重新运行："
        )
    else:
        print("下一步：机构/OA 失败项已写入 Zotero 回退清单，请运行：")
    print(_powershell_command("zotero", "--run-dir", run_dir))
    print(f"Zotero 回退清单：{result.paths.zotero_fallback}")
    try:
        from paper_automation.zotero_bridge import (
            format_active_bridge_target,
            read_active_bridge_instance,
        )

        print(format_active_bridge_target(read_active_bridge_instance()))
    except Exception:
        pass


def _print_next_step(result: BatchRunResult) -> None:
    if result.manual_retry_count > 0:
        print("下一步：本批次启用了人工重试；完成登录或验证码后只能 resume 一次：")
        print(_powershell_command(
            "resume",
            "--run-dir",
            Path(result.paths.root).expanduser(),
        ))
        return
    if result.zotero_fallback_count > 0:
        _print_zotero_next_step(result, queued=False)
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


def _handle_bridge_run(bridge_run, *, rerun_command: str = "zotero") -> tuple[BatchRunResult | None, int | None]:
    """Return (result, early_exit_code). early_exit_code is set for awaiting_confirmation."""

    if bridge_run.status == "awaiting_confirmation":
        if bridge_run.bridge is None:
            raise RuntimeError("bridge_batch_result_missing")
        print(f"桥接任务：{len(bridge_run.bridge.jobs)} 个子作业")
        print(
            "Zotero 插件应自动确认批次（0.2.0+）。"
            "若仍在等待：请升级/启用「文献下载桥接」插件，或在 about:config 中确认"
            " extensions.zoteroPaperDownloadBridge.autoConfirm 为 true；"
            "然后重新运行同一条命令。"
        )
        if bridge_run.bridge.jobs:
            run_dir = Path(bridge_run.bridge.jobs[0].run_dir).expanduser()
            print(f"批次目录：{run_dir}")
            print(_powershell_command(rerun_command, "--run-dir", run_dir))
        return None, 3
    if bridge_run.batch_result is None:
        if bridge_run.status == "no_fallback":
            return None, None
        raise RuntimeError("bridge_batch_result_missing")
    return bridge_run.batch_result, None


def main(argv: Sequence[str] | None = None) -> int:
    """解析参数、调用批次工作流，并返回适合脚本使用的退出码。"""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            # A4: preflight on by default; disable with --no-doi-preflight.
            do_preflight = not bool(args.no_doi_preflight)
            # Fixed run folder by default (one delivery dir; resume if exists).
            use_fixed = not bool(args.no_fixed_run) and not bool(args.fresh)
            if args.fixed_run is True:
                use_fixed = True
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
                    skip_manual_retry=not args.enable_manual_retry,
                    download_supplements=(
                        False
                        if bool(getattr(args, "no_download_supplements", False))
                        else True
                        if args.download_supplements is None
                        else bool(args.download_supplements)
                    ),
                    smart_route=not bool(args.no_smart_route),
                    session_break_seconds=float(args.session_break_seconds),
                    session_break_every=int(args.session_break_every),
                    resolve_title_metadata=bool(args.resolve_title_metadata),
                    iucr_short_try=not bool(getattr(args, "no_iucr_short_try", False)),
                    api_only=bool(getattr(args, "api_only", False)),
                ),
                doi_preflight=do_preflight,
                fixed_run=use_fixed,
                fresh=bool(args.fresh),
            )
            _print_summary(result)
            print(f"交付目录：{result.paths.root}")
            print(f"  清单：{user_inventory_path(result.paths)}")
            print(f"  PDF：{user_delivery_dir(result.paths) / 'pdf'}")
            # Default: auto-queue Zotero and wait for results (less manual).
            auto_zotero = not bool(args.no_auto_zotero)
            if auto_zotero and result.zotero_fallback_count > 0:
                print("机构/OA 失败项将自动排队 Zotero 桥接…")
                bridge_run = run_zotero_bridge(
                    result.paths.root,
                    library_id=args.library_id,
                    wait_seconds=args.wait_seconds,
                )
                bridge_result, early = _handle_bridge_run(bridge_run, rerun_command="zotero")
                if early is not None:
                    _print_zotero_next_step(result, queued=True)
                    return early
                if bridge_result is not None:
                    result = bridge_result
                    _print_summary(result)
                    if result.failed_count == 0 and result.zotero_fallback_count == 0:
                        print(
                            f"批次已完成。结果文件夹："
                            f"{user_delivery_dir(result.paths)}"
                        )
                    else:
                        print("报告已更新。批次未完成且可恢复。")
                        print(f"未解决数量：{max(result.failed_count, result.zotero_fallback_count)}")
                    return 0
            if result.zotero_fallback_count > 0 and not auto_zotero:
                print(
                    "提示：有失败项可先同批次重试机构下载："
                    f" paper_batch.py retry-failed --run-dir \"{result.paths.root}\""
                )
                print("或显式排队 Zotero：paper_batch.py zotero --run-dir \"...\"")
            _print_next_step(result)
            return 0
        if args.command == "retry-failed":
            base = load_batch_state(Path(args.run_dir).expanduser().resolve())
            saved = base.get("options") or {}
            options = BatchOptions(
                email=args.email or str(saved.get("email", "") or ""),
                cookies=args.cookies or str(saved.get("cookies", "") or ""),
                browser_exe=args.browser_exe or str(saved.get("browser_exe", "") or ""),
                login_wait_seconds=(
                    args.login_wait_seconds
                    if args.login_wait_seconds >= 0
                    else int(saved.get("login_wait_seconds", 0) or 0)
                ),
                debug_port=(
                    args.debug_port
                    if args.debug_port > 0
                    else int(saved.get("debug_port", 9333) or 9333)
                ),
                throttle_seconds=float(saved.get("throttle_seconds", 1.0) or 1.0),
                skip_manual_retry=bool(saved.get("skip_manual_retry", True)),
                download_supplements=bool(saved.get("download_supplements", True)),
                smart_route=bool(saved.get("smart_route", True)),
                session_break_seconds=float(saved.get("session_break_seconds", 60.0) or 60.0),
                session_break_every=int(saved.get("session_break_every", 8) or 8),
                resolve_title_metadata=bool(saved.get("resolve_title_metadata", False)),
                circuit_breaker_threshold=int(saved.get("circuit_breaker_threshold", 3) or 3),
                auto_oa_recovery=bool(saved.get("auto_oa_recovery", True)),
                iucr_short_try=bool(saved.get("iucr_short_try", True)),
                api_only=bool(saved.get("api_only", False)),
            )
            result = retry_failed_batch(
                args.run_dir,
                options=options,
                skip_oa=not args.include_oa,
                retry_all=bool(args.retry_all_failed),
            )
            _print_summary(result)
            auto_zotero = not bool(getattr(args, "no_auto_zotero", False))
            if auto_zotero and result.zotero_fallback_count > 0:
                print("重试后失败项将自动排队 Zotero 桥接…")
                bridge_run = run_zotero_bridge(
                    result.paths.root,
                    library_id=int(getattr(args, "library_id", 1) or 1),
                    wait_seconds=int(getattr(args, "wait_seconds", 600) or 0),
                )
                bridge_result, early = _handle_bridge_run(bridge_run, rerun_command="zotero")
                if early is not None:
                    _print_zotero_next_step(result, queued=True)
                    return early
                if bridge_result is not None:
                    result = bridge_result
                    _print_summary(result)
            elif result.zotero_fallback_count > 0:
                print(
                    "仍有失败项。可再跑 retry-failed，或："
                    f" paper_batch.py zotero --run-dir \"{result.paths.root}\""
                )
            _print_next_step(result)
            return 0
        if args.command == "resume":
            result = resume_batch(args.run_dir)
        elif args.command == "finalize":
            result = finalize_batch(args.run_dir, args.zotero_results)
        elif args.command == "delivery":
            run_dir = Path(args.run_dir).expanduser().resolve()
            paths = paths_from_run_dir(run_dir)
            state = load_batch_state(run_dir)
            write_final_reports(paths, state["rows"])
            print(f"下载清单：{user_inventory_path(paths)}")
            print(f"结果文件夹：{user_delivery_dir(paths)}")
            result = result_from_state(paths, state)
            _print_summary(result)
            return 0
        elif args.command == "refresh-delivery":
            from paper_automation.delivery_refresh import refresh_delivery

            refresh_result = refresh_delivery(
                args.run_dir,
                email=str(getattr(args, "email", "") or ""),
                apply_rename=not bool(getattr(args, "no_rename", False)),
            )
            print(f"[refresh-delivery] 重命名 {refresh_result.renamed} 个")
            print(f"[refresh-delivery] 映射到失败 DOI {refresh_result.mapped_to_row} 条")
            print(f"[refresh-delivery] 外部保留约 {refresh_result.external_kept} 个")
            print(f"下载清单：{refresh_result.inventory_path}")
            print(f"对照表：{refresh_result.rename_map_path}")
            print(f"结果文件夹：{user_delivery_dir(paths_from_run_dir(refresh_result.run_dir))}")
            return 0
        elif args.command == "recover-oa":
            from paper_automation.oa_recovery import (
                DEFAULT_RECOVER_STATUSES,
                run_limited_oa_recovery_on_batch,
            )

            only = None
            if str(getattr(args, "only_status", "") or "").strip():
                only = {
                    part.strip().lower()
                    for part in str(args.only_status).split(",")
                    if part.strip()
                }
            recovered = run_limited_oa_recovery_on_batch(
                args.run_dir,
                email=str(args.email or ""),
                budget_seconds=float(args.budget_seconds),
                only_statuses=only or DEFAULT_RECOVER_STATUSES,
                max_workers=int(args.max_workers),
            )
            ok = sum(1 for item in recovered if item.status == "oa_downloaded")
            print(f"[recover-oa] 处理 {len(recovered)} 条；成功 {ok}；失败 {len(recovered) - ok}")
            for item in recovered:
                print(
                    f"  - {item.doi}: {item.status}"
                    + (f" -> {Path(item.file).name}" if item.file else f" ({item.reason})")
                    + f" [{item.elapsed_s:.1f}s]"
                )
            run_dir = Path(args.run_dir).expanduser().resolve()
            report = run_dir / "working" / "limited_oa_recovery_report.csv"
            if report.is_file():
                print(f"明细：{report}")
            paths = paths_from_run_dir(run_dir)
            result = result_from_state(paths, load_batch_state(run_dir))
            _print_summary(result)
            auto_zotero = not bool(getattr(args, "no_auto_zotero", False))
            if auto_zotero and result.zotero_fallback_count > 0:
                print("OA 补救后仍有失败项，自动排队 Zotero…")
                bridge_run = run_zotero_bridge(
                    result.paths.root,
                    library_id=int(getattr(args, "library_id", 1) or 1),
                    wait_seconds=int(getattr(args, "wait_seconds", 600) or 0),
                )
                bridge_result, early = _handle_bridge_run(bridge_run, rerun_command="zotero")
                if early is not None:
                    return early
                if bridge_result is not None:
                    result = bridge_result
                    _print_summary(result)
            elif result.zotero_fallback_count > 0:
                print(
                    "仍有失败项可排队 Zotero："
                    f" paper_batch.py zotero --run-dir \"{result.paths.root}\""
                )
            return 0 if ok == len(recovered) or len(recovered) == 0 else 0
        else:
            bridge_run = run_zotero_bridge(
                args.run_dir,
                library_id=args.library_id,
                wait_seconds=args.wait_seconds,
            )
            bridge_result, early = _handle_bridge_run(bridge_run, rerun_command="zotero")
            if early is not None:
                return early
            if bridge_result is None:
                paths = paths_from_run_dir(args.run_dir)
                result = result_from_state(paths, load_batch_state(paths.root))
            else:
                result = bridge_result

        _print_summary(result)
        if args.command in {"finalize", "zotero"}:
            delivery = user_delivery_dir(result.paths)
            if result.failed_count == 0 and result.zotero_fallback_count == 0:
                print(f"批次已完成。结果文件夹：{delivery}")
            else:
                unresolved_count = max(
                    result.failed_count,
                    result.zotero_fallback_count,
                )
                print("报告已更新。批次未完成且可恢复。")
                print(f"未解决数量：{unresolved_count}")
                print(f"结果文件夹：{delivery}")
        else:
            _print_next_step(result)
    except (ValueError, OSError, RuntimeError) as error:
        _print_error(error)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
