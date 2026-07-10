"""面向初学者的项目优先文献批次命令行入口。"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from paper_automation.batch_stages import BatchOptions
from paper_automation.batch_workflow import BatchRunResult, finalize_batch, resume_batch, start_batch


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
    start.add_argument("--browser-exe", default="", help="浏览器可执行文件路径（可选）")
    start.add_argument("--login-wait-seconds", type=int, default=0, help="登录等待秒数")
    start.add_argument("--debug-port", type=int, default=9333, help="浏览器调试端口")
    start.add_argument("--throttle-seconds", type=float, default=1.0, help="请求间隔秒数")

    resume = subparsers.add_parser("resume", help="仅重试一次登录或验证码失败条目")
    resume.add_argument("--run-dir", required=True, help="已有批次目录")

    finalize = subparsers.add_parser("finalize", help="归并 Zotero 附件并生成最终报告")
    finalize.add_argument("--run-dir", required=True, help="已有批次目录")
    finalize.add_argument("--zotero-results", required=True, help="Zotero 结果 CSV 文件")
    return parser


def _quote_command_arg(value: object) -> str:
    """以 Windows 安全的双引号形式展示命令参数。"""

    return '"' + str(value).replace('"', r'\"') + '"'


def _finalize_command(result: BatchRunResult) -> str:
    return (
        f"{_quote_command_arg(sys.executable)} {_quote_command_arg('paper_batch.py')} finalize "
        f"--run-dir {_quote_command_arg(result.paths.root)} "
        f"--zotero-results {_quote_command_arg(result.paths.zotero_results)}"
    )


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
        print(
            f"{_quote_command_arg(sys.executable)} {_quote_command_arg('paper_batch.py')} resume "
            f"--run-dir {_quote_command_arg(result.paths.root)}"
        )
        return
    if result.zotero_fallback_count > 0:
        print("下一步：请在 Zotero 中处理回退条目；附件将以非破坏复制方式归并。")
        print(f"默认结果文件：{result.paths.zotero_results}")
        print("完成后运行：")
        print(_finalize_command(result))
        return
    print("下一步：请创建仅含表头的 Zotero 结果文件后运行：")
    print(_finalize_command(result))


def _print_error(error: Exception) -> None:
    print(
        f"错误码 2：批次工作流未完成（{type(error).__name__}）。请检查路径和批次状态后重试。",
        file=sys.stderr,
    )


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
        else:
            result = finalize_batch(args.run_dir, args.zotero_results)
    except (ValueError, OSError, RuntimeError) as error:
        _print_error(error)
        return 2

    _print_summary(result)
    if args.command == "finalize":
        print(f"批次已完成。最终 PDF 目录：{result.paths.pdfs}")
    else:
        _print_next_step(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
