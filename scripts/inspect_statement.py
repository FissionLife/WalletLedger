#!/usr/bin/env python3
"""Show exactly how WalletLedger reads a statement: detected format, parsed rows, skipped lines.

    uv run python scripts/inspect_statement.py statement.pdf            # rows + skipped lines
    uv run python scripts/inspect_statement.py statement.pdf --text     # also the raw PDF text
    uv run python scripts/inspect_statement.py statement.pdf --format bank_table   # force a parser
    uv run python scripts/inspect_statement.py sms.txt                  # a .txt of SMS lines

Runs fully offline and never writes to the database. If a real statement parses badly, run it
with --text and share the output (mask names/account numbers first): that is all a developer
needs to add the missing layout to app/services_ai/transaction_parser.py.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services_ai.transaction_parser import (  # noqa: E402
    FORMATS,
    detect_statement_format,
    parse_statement_text,
    statement_text_from_file,
    summarize_statement,
)


def _cut(value: object, width: int) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= width else text[: width - 1] + "~"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("file", help="statement .pdf, or a .txt with SMS lines / extracted text")
    parser.add_argument("--text", action="store_true", help="print the extracted raw text")
    parser.add_argument("--format", choices=FORMATS, help="force a parser instead of detecting")
    parser.add_argument("--no-skipped", action="store_true", help="hide the skipped-lines list")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    path = Path(args.file)
    kind = "pdf" if path.suffix.lower() == ".pdf" else "text"
    try:
        text, source = statement_text_from_file(path.read_bytes(), kind)
    except (OSError, ValueError) as exc:
        print(f"Could not read {path}: {exc}")
        return 2

    detected = detect_statement_format(text)
    print(f"File:     {path.name}  ({len(text.splitlines())} text lines)")
    print(f"Detected: {detected}" + (f"  (forced: {args.format})" if args.format else ""))
    if args.text:
        print("\n--- extracted text " + "-" * 60)
        for number, line in enumerate(text.splitlines(), start=1):
            print(f"{number:4d} | {line}")
        print("-" * 79)

    result = parse_statement_text(text, source=source, fmt=args.format)
    print(f"\nParsed {len(result.rows)} transactions with the '{result.format}' parser:\n")
    header = f"{'#':>3} {'date':10} {'type':3} {'amount':>12}  {'merchant':24} {'category':18} note"
    print(header)
    print("-" * len(header))
    for index, row in enumerate(result.rows, start=1):
        sign = "-" if row["type"] == "expense" else "+"
        print(
            f"{index:>3} {row['date'] or '?':10} {'out' if sign == '-' else 'in':3} "
            f"{sign}{row['amount']:>11,.2f}  {_cut(row['merchant'], 24):24} "
            f"{_cut(row['category'], 18):18} {row.get('note') or ''}"
        )
        if row.get("vpa") or row.get("reference"):
            extras = "  ".join(
                f"{key}={row[key]}" for key in ("vpa", "reference", "balance") if row.get(key)
            )
            print(f"{'':4}{_cut(extras, 90)}")

    summary = summarize_statement(result.rows)
    print(
        f"\nSummary: {summary['count']} rows | out ₹{summary['total_debit']:,.2f} "
        f"({summary['expense_count']}) | in ₹{summary['total_credit']:,.2f} "
        f"({summary['income_count']}) | {summary['period'] or 'no dates'} | "
        f"{summary['uncategorized']} uncategorized"
    )
    if summary["categories"]:
        print(
            "By category: "
            + ", ".join(f"{name} ₹{total:,.0f}" for name, total in summary["categories"])
        )

    if not args.no_skipped and result.skipped:
        print(f"\nSkipped {len(result.skipped)} lines (line no. | reason | text):")
        for number, reason, line in sorted(result.skipped):
            print(f"{number:4d} | {reason:32} | {_cut(line, 80)}")
    return 0 if result.rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
