#!/usr/bin/env python3
"""
mjres_tool.py — extractor and inserter for .mjres <-> .xlsx

Usage:
  python mjres_tool.py extract file1.mjres [file2.mjres ...] -o output.xlsx
  python mjres_tool.py insert  input.xlsx  [-o outdir]

Xlsx columns: L | OrigName | Orig | NameTL | TL | TLE | Notes
  - Each .mjres file → one sheet (named after the file without extension)
  - Multiline CSV values (real newlines) are stored as \\n in the cell
  - On insert: TLE is used if non-empty, otherwise TL; if both empty — row skipped
"""

import sys
import os
import csv
import io
import re
import argparse

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# ---------------------------------------------------------------------------
# Styling constants
# ---------------------------------------------------------------------------
HEADERS = ["L", "OrigName", "Orig", "NameTL", "TL", "TLE", "Notes"]

HEADER_FILL = PatternFill("solid", fgColor="2F5496")
HEADER_FONT = Font(name="Arial", bold=True, color="FFFFFF", size=10)
CELL_FONT   = Font(name="Arial", size=10)
WRAP        = Alignment(wrap_text=True, vertical="top")
THIN        = Side(style="thin", color="CCCCCC")
BORDER      = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
COL_WIDTHS  = [8, 18, 45, 18, 45, 45, 25]

# ---------------------------------------------------------------------------
# .mjres parser
# ---------------------------------------------------------------------------
def parse_mjres(path: str) -> list[tuple[str, str]]:
    """
    Parse a .mjres CSV file.
    Returns list of (key, value) pairs.
    Multiline quoted values are joined with a real newline (csv module handles this).
    """
    with open(path, encoding="utf-8", newline="") as f:
        content = f.read()

    # .mjres uses \r\n; csv.reader handles universal newlines fine
    reader = csv.reader(io.StringIO(content))
    rows = []
    first = True
    for row in reader:
        if first:
            first = False
            continue  # skip header "Key,Value"
        if len(row) < 2:
            continue
        key   = row[0].strip()
        value = row[1]          # real newlines already embedded by csv module
        rows.append((key, value))
    return rows


def split_name(value: str) -> tuple[str, str]:
    """
    Extract the speaker name from a line like  槙野「text」
    Returns (name, full_value).  name is empty string if no 「 found.
    """
    idx = value.find("「")
    if idx == -1:
        return "", value
    return value[:idx], value


# ---------------------------------------------------------------------------
# EXTRACT: .mjres files → .xlsx
# ---------------------------------------------------------------------------
def expand_inputs(inputs: list[str]) -> list[str]:
    """Expand folders to .mjres files; keep plain paths as-is."""
    result = []
    for inp in inputs:
        if os.path.isdir(inp):
            found = sorted(
                os.path.join(inp, f)
                for f in os.listdir(inp)
                if f.lower().endswith(".mjres")
            )
            if not found:
                sys.exit(f"No .mjres files found in folder: {inp}")
            result.extend(found)
        else:
            result.append(inp)
    return result


def cmd_extract(files: list[str], output: str):
    files = expand_inputs(files)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # drop the default empty sheet

    for path in files:
        if not os.path.isfile(path):
            sys.exit(f"File not found: {path}")

        sheet_name = os.path.splitext(os.path.basename(path))[0][:31]
        ws = wb.create_sheet(title=sheet_name)

        # Header row
        for ci, h in enumerate(HEADERS, 1):
            c = ws.cell(row=1, column=ci, value=h)
            c.font      = HEADER_FONT
            c.fill      = HEADER_FILL
            c.alignment = WRAP
            c.border    = BORDER
        ws.row_dimensions[1].height = 18

        # Data rows
        for ri, (key, value) in enumerate(parse_mjres(path), 2):
            orig_name, _ = split_name(value)

            # Orig: text only, without the speaker name prefix
            if orig_name:
                # strip "Name「" from the start (and closing 」 from the end)
                orig_text = value[len(orig_name) + 1:]   # skip Name + 「
                if orig_text.endswith("」"):
                    orig_text = orig_text[:-1]
            else:
                orig_text = value

            # Store real newlines as \n escape
            orig_text_cell = orig_text.replace("\n", "\\n")

            def put(ci, v):
                c = ws.cell(row=ri, column=ci, value=v)
                c.font      = CELL_FONT
                c.alignment = WRAP
                c.border    = BORDER

            put(1, key)
            put(2, orig_name if orig_name else None)
            put(3, orig_text_cell)
            put(4, None)   # NameTL  — to be filled by translator
            put(5, None)   # TL      — to be filled by translator
            put(6, None)   # TLE     — to be filled by editor
            put(7, None)   # Notes

        # Column widths & freeze
        for ci, w in enumerate(COL_WIDTHS, 1):
            ws.column_dimensions[get_column_letter(ci)].width = w
        ws.freeze_panes = "A2"

        print(f"  Sheet '{sheet_name}': {ri - 1} rows")

    wb.save(output)
    print(f"Saved: {output}")


# ---------------------------------------------------------------------------
# INSERT: .xlsx → .mjres files
# ---------------------------------------------------------------------------
def cmd_insert(input_xlsx: str, outdir: str):
    if not os.path.isfile(input_xlsx):
        sys.exit(f"File not found: {input_xlsx}")

    os.makedirs(outdir, exist_ok=True)
    wb = openpyxl.load_workbook(input_xlsx)

    for ws in wb.worksheets:
        rows_out: list[str] = []
        has_translation = False

        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or row[0] is None:
                continue

            key     = str(row[0]).strip()
            name_tl = str(row[3]).strip() if len(row) > 3 and row[3] is not None else ""
            tl      = str(row[4]).strip() if len(row) > 4 and row[4] is not None else ""
            tle     = str(row[5]).strip() if len(row) > 5 and row[5] is not None else ""

            if name_tl or tl or tle:
                has_translation = True

            # TLE takes priority; then TL; fallback to Orig (column index 2)
            orig_text    = str(row[2]).strip() if len(row) > 2 and row[2] is not None else ""
            insert_value = tle if tle else (tl if tl else orig_text)
            if not insert_value and insert_value != "":
                continue

            # Convert \\n escape sequences back to real newlines
            insert_value = insert_value.replace("\\n", "\n")

            # Reconstruct "Name「text」" — NameTL takes priority over OrigName
            orig_name  = str(row[1]).strip() if len(row) > 1 and row[1] is not None else ""
            final_name = name_tl if name_tl else orig_name
            if final_name:
                full_value = final_name + "「" + insert_value + "」"
            else:
                full_value = insert_value

            # CSV-quote if value contains comma, newline, or double-quote
            if "," in full_value or "\n" in full_value or '"' in full_value:
                escaped  = full_value.replace('"', '""')
                csv_val  = f'"{escaped}"'
            else:
                csv_val  = full_value

            rows_out.append(f"{key},{csv_val}")

        if not rows_out or not has_translation:
            print(f"  Sheet '{ws.title}': no translated rows, skipped")
            continue

        # Sanitise sheet name for use as filename
        safe_name = re.sub(r'[\\/:*?"<>|]', "_", ws.title)
        outpath   = os.path.join(outdir, safe_name + ".mjres")

        with open(outpath, "w", encoding="utf-8", newline="") as f:
            f.write("Key,Value\r\n")
            for line in rows_out:
                f.write(line + "\r\n")

        print(f"  Written: {outpath} ({len(rows_out)} rows)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Convert .mjres files to/from .xlsx for translation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # extract
    p_ext = sub.add_parser("extract", help="Convert .mjres → .xlsx")
    p_ext.add_argument("files", nargs="+", metavar="FILE.mjres")
    p_ext.add_argument("-o", "--output", default="output.xlsx", metavar="OUTPUT.xlsx")

    # insert
    p_ins = sub.add_parser("insert", help="Convert .xlsx → .mjres")
    p_ins.add_argument("input", metavar="INPUT.xlsx")
    p_ins.add_argument("-o", "--outdir", default=".", metavar="OUTDIR")

    args = parser.parse_args()

    if args.command == "extract":
        print(f"Extracting {len(args.files)} file(s) → {args.output}")
        cmd_extract(args.files, args.output)
    elif args.command == "insert":
        print(f"Inserting {args.input} → {args.outdir}/")
        cmd_insert(args.input, args.outdir)


if __name__ == "__main__":
    main()