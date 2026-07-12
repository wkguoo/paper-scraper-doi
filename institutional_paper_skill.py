from __future__ import annotations

import argparse
import os
import sys

from paper_automation.institutional import run_institutional_workflow


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    result = run_institutional_workflow(
        input_path=args.input,
        output_dir=args.out,
        doi_column=args.doi_column,
        sheet_name=args.sheet,
        email=args.email,
        browser_exe=args.browser_exe,
        debug_port=args.debug_port,
        login_wait_seconds=args.login_wait_seconds,
        throttle_seconds=args.throttle_seconds,
        overwrite=args.overwrite,
        merge_manifest_path=args.merge_manifest,
    )

    print("Non-Elsevier institutional download finished")
    print(f"- Output directory: {result.output_dir}")
    print(f"- PDF directory: {result.pdf_dir}")
    print(f"- Input rows: {result.total_input}")
    print(f"- Resolved DOI rows: {result.resolved_count}")
    print(f"- Downloaded PDFs: {result.downloaded_count}")
    print(f"- Failed / unresolved: {result.failed_count}")
    print(f"- Report CSV: {result.report_path}")
    print(f"- Run summary JSON: {result.run_summary_path}")
    if result.manifest_update_path:
        print(f"- Merged manifest CSV: {result.manifest_update_path}")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Non-Elsevier institutional adapter (internal / compatibility). "
            "For new literature jobs prefer: paper_batch.py start ..."
        ),
        epilog="Default product entry is paper_batch.py (unified batch), not this script alone.",
    )
    parser.add_argument("--input", required=True, help="CSV/XLSX/XLSM/TXT/Markdown input with DOI/title rows")
    parser.add_argument("--out", required=True, help="Output root directory")
    parser.add_argument("--doi-column", help="Optional DOI column override for tabular input")
    parser.add_argument("--sheet", help="Excel sheet name for XLSX/XLSM input")
    parser.add_argument("--email", default=os.environ.get("PAPER_SKILL_EMAIL", ""), help="Email for polite Crossref/OpenAlex API use")
    parser.add_argument("--browser-exe", help="Browser executable path for Edge/Chrome institutional session")
    parser.add_argument("--debug-port", type=int, default=9333, help="Remote debugging port for the browser session")
    parser.add_argument("--login-wait-seconds", type=int, default=0, help="Wait time after launching a fresh browser for manual login")
    parser.add_argument("--throttle-seconds", type=float, default=1.0, help="Pause between rows to reduce publisher rate pressure")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing PDF files")
    parser.add_argument("--merge-manifest", help="Existing final manifest CSV/XLSX/XLSM to enrich with institutional results")
    return parser


if __name__ == "__main__":
    sys.exit(main())
