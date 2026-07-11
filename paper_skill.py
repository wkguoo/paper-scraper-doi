from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from doi_batch_utils import TEXT_ENCODINGS
from paper_automation.workflow import run_workflow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Identify paper text, resolve metadata, and download publicly available open-access PDF candidates.",
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input", help="Text/CSV/Markdown file containing copied paper information")
    input_group.add_argument("--text", help="Paper text pasted directly on the command line")
    parser.add_argument("--out", required=True, help="Output directory for PDFs, metadata, logs, and failed rows")
    parser.add_argument("--email", default=os.environ.get("PAPER_SKILL_EMAIL", ""), help="Email for Unpaywall/Crossref polite API use")
    parser.add_argument("--dry-run", action="store_true", help="Resolve metadata and PDF URLs without downloading files")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing PDF files")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of parsed input rows for testing")

    args = parser.parse_args(argv)
    text = args.text if args.text is not None else _read_text_file(Path(args.input))
    result = run_workflow(
        input_text=text,
        output_dir=args.out,
        email=args.email,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
        limit=args.limit,
    )

    print("Paper automation finished")
    print(f"- Input rows: {result.total_input}")
    print(f"- Unique rows: {result.unique_count}")
    print(f"- Duplicates: {result.duplicate_count}")
    print(f"- Resolved metadata: {result.resolved_count}")
    print(f"- Downloaded PDFs: {result.downloaded_count}")
    print(f"- Failed / no accessible open-access PDF: {result.failed_count}")
    print(f"- Manifest CSV: {result.manifest_csv}")
    print(f"- Manifest JSON: {result.manifest_json}")
    print(f"- Duplicates CSV: {result.duplicates_csv}")
    return 0


def _read_text_file(path: Path) -> str:
    last_error: Exception | None = None
    for encoding in TEXT_ENCODINGS:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
        except OSError as exc:
            raise SystemExit(f"Cannot read input file: {exc}") from exc
    raise SystemExit(f"Cannot decode input file: {last_error}")


if __name__ == "__main__":
    sys.exit(main())
