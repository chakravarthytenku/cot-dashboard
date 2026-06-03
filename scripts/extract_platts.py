#!/usr/bin/env python3
"""
extract_platts.py
-----------------
Reads the newest DG_YYYYMMDD.pdf from the platts-data/ folder,
extracts the 44 Platts assessment values, and appends a new row
to the DATA array inside platts.html.

Triggered automatically by GitHub Actions on every push that adds
a file to platts-data/.
"""

import os
import re
import sys
import glob
import json
from datetime import datetime

# ── PDF parsing ──────────────────────────────────────────────────────────────
try:
    import pdfplumber
except ImportError:
    print("Installing pdfplumber…")
    os.system("pip install pdfplumber --quiet")
    import pdfplumber

# ── Symbols to extract and the regex patterns that find them ─────────────────
# Each entry: (symbol, regex_pattern)
# Patterns match "SYMBOL  VALUE" lines in the PDF text.
# Values may be prefixed with N, U, or Q (basis quotes) — we strip those.
SYMBOLS = [
    # Wheat
    ("WAUSA00",  r"WAUSA00\s+([\d.]+)"),
    ("WASWA00",  r"WASWA00\s+([\d.]+)"),
    ("WRBSD00",  r"WRBSD00\s+([\d.]+)"),
    ("WUBSA00",  r"WUBSA00\s+([\d.]+)"),
    ("ACVBA00",  r"ACVBA00\s+([\d.]+)"),
    ("ACVBB00",  r"ACVBB00\s+([\d.]+)"),
    ("AMARA00",  r"AMARA00\s+([\d.]+)"),
    ("ACPTA00",  r"ACPTA00\s+([\d.]+)"),
    ("ACQTB00",  r"ACQTB00\s+([\d.]+)"),
    ("AWHCD00",  r"AWHCD00\s+([\d.]+)"),
    # Corn
    ("WCINV00",  r"WCINV00\s+([\d.]+)"),
    ("CNEBA00",  r"CNEBA00\s+[NUQ]?([\d.]+)"),
    ("CUBSU00",  r"CUBSU00\s+([\d.]+)"),
    ("ACVBC00",  r"ACVBC00\s+([\d.]+)"),
    ("CESEV00",  r"CESEV00\s+([\d.]+)"),
    ("ARGCA00",  r"ARGCA00\s+([\d.]+)"),
    ("ARGCB00",  r"ARGCB00\s+[NUQ]?([\d.]+)"),
    ("ABCSA00",  r"ABCSA00\s+([\d.]+)"),
    ("ABCSB00",  r"ABCSB00\s+[NUQ]?([\d.]+)"),
    ("WCNOA00",  r"WCNOA00\s+([\d.]+)"),
    ("WCNOE00",  r"WCNOE00\s+[NUQ]?([\d.]+)"),
    # Oilseeds
    ("SYBAB00",  r"SYBAB00\s+([\d.]+)"),
    ("SYBAA00",  r"SYBAA00\s+[NUQ]?([\d.]+)"),
    ("SYBBB00",  r"SYBBB00\s+([\d.]+)"),
    ("SYBBA00",  r"SYBBA00\s+[NUQ]?([\d.]+)"),
    ("SYBBD00",  r"SYBBD00\s+([\d.]+)"),
    ("SYBBC00",  r"SYBBC00\s+[NUQ]?([\d.]+)"),
    ("SYBBI00",  r"SYBBI00\s+([\d.]+)"),
    ("SYBBJ00",  r"SYBBJ00\s+[NUQ]?([\d.]+)"),
    ("CSGCD00",  r"CSGCD00\s+([\d.]+)"),
    ("ABSCA00",  r"ABSCA00\s+([\d.]+)"),
    # Animal Feed
    ("EUPMR00",  r"EUPMR00\s+([\d.]+)"),
    ("SMESD00",  r"SMESD00\s+([\d.]+)"),
    ("SYMAA00",  r"SYMAA00\s+([\d.]+)"),
    ("SYMAB00",  r"SYMAB00\s+[NUQ]?(-?[\d.]+)"),
    ("SYMBA00",  r"SYMBA00\s+([\d.]+)"),
    ("SYMBB00",  r"SYMBB00\s+[NUQ]?(-?[\d.]+)"),
    # Vegetable Oils
    ("ACPOD00",  r"ACPOD00\s+([\d.]+)"),
    ("SFWBL00",  r"SFWBL00\s+([\d.]+)"),
    ("ASEEG00",  r"ASEEG00\s+([\d.]+)"),
    ("SYOAA00",  r"SYOAA00\s+([\d.]+)"),
    ("SYOAB00",  r"SYOAB00\s*[NUQ]?(-?[\d.]+)"),
    ("SYOBA00",  r"SYOBA00\s+([\d.]+)"),
    ("SYOBB00",  r"SYOBB00\s*[NUQ]?(-?[\d.]+)"),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def find_latest_pdf(folder="platts-data"):
    """Return path to the most-recently-modified PDF in folder."""
    pdfs = glob.glob(os.path.join(folder, "*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"No PDFs found in {folder}/")
    return max(pdfs, key=os.path.getmtime)


def extract_text(pdf_path):
    """Extract all text from PDF, concatenating pages."""
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text += t + "\n"
    return text


def parse_date_from_filename(pdf_path):
    """DG_YYYYMMDD.pdf  →  DD-Mon  e.g. '03-Jun'"""
    name = os.path.basename(pdf_path)
    m = re.search(r"(\d{4})(\d{2})(\d{2})", name)
    if not m:
        raise ValueError(f"Cannot parse date from filename: {name}")
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return datetime(y, mo, d).strftime("%-d-%b")   # e.g. "3-Jun"


def parse_date_from_text(text):
    """Fallback: find 'May 28, 2026' style header in PDF text."""
    m = re.search(r"(January|February|March|April|May|June|July|August|"
                  r"September|October|November|December)\s+(\d{1,2}),?\s+\d{4}", text)
    if m:
        month_str = m.group(1)[:3]   # 'May'
        day = int(m.group(2))
        return f"{day}-{month_str}"
    return None


def extract_values(text):
    """
    Walk through each symbol pattern and return a dict of {sym: float|None}.
    Strips N/U/Q prefixes; negatives (basis) handled by pattern capturing '-'.
    """
    results = {}
    for sym, pattern in SYMBOLS:
        match = re.search(pattern, text)
        if match:
            try:
                results[sym] = float(match.group(1))
            except ValueError:
                results[sym] = None
        else:
            results[sym] = None
    return results


def build_row(date_str, values):
    """Format one JS object row for the DATA array."""
    parts = [f'  {{ date:"{date_str}"']
    for sym, _ in SYMBOLS:
        v = values.get(sym)
        parts.append(f'{sym}:{json.dumps(v)}')
    return ", ".join(parts) + " },"


def already_loaded(html_path, date_str):
    """Return True if this date already exists in platts.html DATA."""
    with open(html_path, "r", encoding="utf-8") as f:
        return f'date:"{date_str}"' in f.read()


def inject_row(html_path, new_row):
    """Insert new_row before the closing '// @@END_DATA@@' marker."""
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    marker = "// @@END_DATA@@"
    if marker not in content:
        raise RuntimeError(
            f"Marker '{marker}' not found in {html_path}. "
            "Make sure platts.html contains that comment just before the closing ];"
        )

    updated = content.replace(marker, new_row + "\n  " + marker)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(updated)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    pdf_path  = find_latest_pdf("platts-data")
    html_path = "platts.html"

    print(f"Processing: {pdf_path}")

    # Parse date
    try:
        date_str = parse_date_from_filename(pdf_path)
    except ValueError:
        text_preview = extract_text(pdf_path)
        date_str = parse_date_from_text(text_preview)
        if not date_str:
            raise RuntimeError("Could not determine date from filename or PDF text.")

    print(f"Date: {date_str}")

    # Guard: don't double-add
    if already_loaded(html_path, date_str):
        print(f"Date {date_str} already in platts.html — skipping.")
        sys.exit(0)

    # Extract
    text   = extract_text(pdf_path)
    values = extract_values(text)

    found  = sum(1 for v in values.values() if v is not None)
    total  = len(SYMBOLS)
    print(f"Extracted {found}/{total} values")

    if found == 0:
        raise RuntimeError("Zero values extracted — check PDF format or symbol patterns.")

    # Build and inject row
    new_row = build_row(date_str, values)
    inject_row(html_path, new_row)
    print(f"✓ Injected row for {date_str} into platts.html")

    # Print summary
    for sym, v in values.items():
        status = f"{v:.2f}" if v is not None else "NULL"
        print(f"  {sym}: {status}")


if __name__ == "__main__":
    main()
