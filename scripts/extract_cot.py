#!/usr/bin/env python3
"""
COT Dashboard Auto-Updater
--------------------------
Parses the latest RJO O'Brien COT PDF from the data/ folder,
extracts positioning data for all tracked commodities,
and injects the new week's rows into index.html.

Usage:
    python scripts/extract_cot.py

The script:
1. Finds the most recently modified PDF in data/
2. Extracts text from ALL pages using pdftotext
3. Parses the commodity rows for grains, softs
4. Appends new data rows to the RAW array in index.html
5. Writes the updated index.html
"""

import re
import os
import sys
import glob
import subprocess
from datetime import datetime
from pathlib import Path

# ── Commodities we track and their exact names in the PDF ──────────────────
COMMODITY_MAP = {
    "Corn":         "Corn",
    "Wheat":        "Wheat",
    "Soybeans":     "Soybeans",
    "KC Wheat":     "KC Wheat",
    "MN Wheat":     "MN Wheat",
    "Soybean Oil":  "Soybean Oil",
    "Soybean Meal": "Soybean Meal",
    "Canola":       "Canola",
    "Rough Rice":   "Rough Rice",
    "Coffee":       "Coffee",
    "Sugar":        "Sugar",
    "Cocoa":        "Cocoa",
    "Cotton":       "Cotton",
}

# Root of the repo
REPO_ROOT = Path(__file__).parent.parent
DATA_DIR  = REPO_ROOT / "data"
HTML_FILE = REPO_ROOT / "index.html"


def find_latest_pdf():
    """Return the most recently modified PDF in data/"""
    pdfs = list(DATA_DIR.glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"No PDF files found in {DATA_DIR}")
    return max(pdfs, key=lambda p: p.stat().st_mtime)


def extract_text(pdf_path: Path) -> str:
    """Use pdftotext to extract ALL pages with layout preservation"""
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"pdftotext failed: {result.stderr}")
    return result.stdout


def parse_date(text: str) -> str:
    """
    Extract the week-ending date from the header line.
    Header format: '05/19/2026 - 05/26/26'
    We want the second date (week ending date).
    """
    # Match the full range: MM/DD/YYYY - MM/DD/YY capturing both dates
    match = re.search(
        r'(\d{2})/(\d{2})/(\d{4})\s*-\s*(\d{2})/(\d{2})/(\d{2,4})',
        text
    )
    if not match:
        raise ValueError("Could not find date range in PDF header")
    # Groups 4,5,6 are the second date (week-ending)
    month, day, year = match.group(4), match.group(5), match.group(6)
    if len(year) == 2:
        year = "20" + year
    print(f"  Date range found: {match.group(1)}/{match.group(2)}/{match.group(3)} -> week ending {month}/{day}/{year}")
    return f"{year}-{month}-{day}"


def parse_number(s: str) -> int:
    """Parse a number string like '-663,170' or '337,396' to int"""
    s = s.replace(",", "").replace(" ", "")
    if not s or s == "-":
        return 0
    return int(float(s))


def parse_commodity_row(line: str, commodity_name: str):
    """
    Parse a single commodity data row.
    
    Column layout (from pdftotext -layout output):
    CommodityName  prod_net  prod_chg  swap_net  swap_chg  mm_net  mm_chg  rec_long  rec_short  other_net  other_chg  oi  oi_chg
    
    We need: prod_net, prod_chg, mm_net, mm_chg, oi
    """
    # Strip the commodity name prefix
    data_part = line[len(commodity_name):].strip()
    
    # Extract all numbers (including negatives with commas)
    # Pattern: optional minus, digits, optional comma-separated groups
    numbers = re.findall(r'-?[\d,]+', data_part)
    
    if len(numbers) < 10:
        return None
    
    try:
        prod_net  = parse_number(numbers[0])
        prod_chg  = parse_number(numbers[1])
        # numbers[2] = swap_net, numbers[3] = swap_chg (skip)
        mm_net    = parse_number(numbers[4])
        mm_chg    = parse_number(numbers[5])
        # numbers[6] = rec_long, numbers[7] = rec_short (skip)
        # numbers[8] = other_net, numbers[9] = other_chg (skip)
        oi        = parse_number(numbers[10])
        return {
            "prod_net": prod_net,
            "prod_chg": prod_chg,
            "mm_net":   mm_net,
            "mm_chg":   mm_chg,
            "oi":       oi,
        }
    except (IndexError, ValueError) as e:
        print(f"  Warning: Could not parse {commodity_name}: {e} — raw: {numbers}")
        return None


def extract_data(text: str) -> dict:
    """Parse all commodity rows from the extracted text"""
    results = {}
    lines = text.split('\n')
    
    for line in lines:
        stripped = line.strip()
        for key, pdf_name in COMMODITY_MAP.items():
            # Match line starting exactly with the commodity name
            if stripped.startswith(pdf_name) and (
                len(stripped) == len(pdf_name) or
                not stripped[len(pdf_name)].isalpha()
            ):
                row = parse_commodity_row(stripped, pdf_name)
                if row:
                    results[key] = row
                    print(f"  ✓ {key:15s}  prod={row['prod_net']:>10,}  mm={row['mm_net']:>10,}  oi={row['oi']:>12,}")
                break
    return results


def build_js_rows(date: str, data: dict) -> str:
    """Build the JavaScript data rows to inject into index.html"""
    lines = [f"  // ── Week ending {date} ──"]
    for commodity, row in data.items():
        line = (
            f"  {{date:\"{date}\","
            f"commodity:\"{commodity}\","
            f"prod_net:{row['prod_net']},"
            f"prod_chg:{row['prod_chg']},"
            f"mm_net:{row['mm_net']},"
            f"mm_chg:{row['mm_chg']},"
            f"oi:{row['oi']}}}"
        )
        lines.append(line)
    return ",\n".join(lines)


def remove_existing_week(html: str, date: str) -> tuple[str, bool]:
    """
    Remove any existing rows for this date from the RAW array,
    including the comment header line. Returns (updated_html, was_found).
    """
    if f'date:"{date}"' not in html:
        return html, False

    lines = html.split('\n')
    filtered = []
    skip_next_comma = False

    for i, line in enumerate(lines):
        # Skip the comment header for this week
        if f'// ── Week ending {date} ──' in line:
            skip_next_comma = False
            continue
        # Skip any data row for this date
        if f'date:"{date}"' in line:
            # Also remove a trailing comma on the previous kept line if present
            if filtered and filtered[-1].rstrip().endswith(','):
                filtered[-1] = filtered[-1].rstrip()[:-1]
            continue
        filtered.append(line)

    return '\n'.join(filtered), True


def inject_into_html(html: str, new_rows: str) -> str:
    """
    Inject new JS rows before the closing ]; of the RAW array.
    """
    raw_end = html.rfind("\n];")
    if raw_end == -1:
        raise ValueError("Could not find end of RAW array (];) in index.html")

    updated = html[:raw_end] + ",\n" + new_rows + html[raw_end:]
    return updated


def main():
    print("=" * 60)
    print("COT Dashboard Auto-Updater")
    print("=" * 60)

    # 1. Find PDF
    pdf_path = find_latest_pdf()
    print(f"\n📄 PDF found: {pdf_path.name}")

    # 2. Extract text
    print("\n📝 Extracting text from ALL pages of PDF...")
    text = extract_text(pdf_path)

    # 3. Parse date
    week_date = parse_date(text)
    print(f"\n📅 Week ending date: {week_date}")

    # 4. Read current index.html
    if not HTML_FILE.exists():
        raise FileNotFoundError(f"index.html not found at {HTML_FILE}")
    html = HTML_FILE.read_text(encoding="utf-8")

    # 5. Remove existing rows for this week if present (allows re-import)
    html, was_existing = remove_existing_week(html, week_date)
    if was_existing:
        print(f"\n♻️  Existing rows for {week_date} removed — will re-import fresh.")
    else:
        print(f"\n✨ No existing entry for {week_date} — fresh import.")

    # 6. Parse commodity data
    print(f"\n📊 Parsing commodity data...")
    data = extract_data(text)

    if not data:
        raise ValueError("No commodity data extracted — check PDF format")

    missing = [c for c in COMMODITY_MAP if c not in data]
    if missing:
        print(f"\n⚠️  Missing commodities (will skip): {', '.join(missing)}")

    print(f"\n✅ Extracted {len(data)} commodities")

    # 7. Build JS rows
    new_rows = build_js_rows(week_date, data)

    # 8. Inject into HTML
    print(f"\n💉 Injecting into index.html...")
    updated_html = inject_into_html(html, new_rows)

    # 9. Write output
    HTML_FILE.write_text(updated_html, encoding="utf-8")
    print(f"\n✅ index.html updated successfully!")
    print(f"   Added {len(data)} commodity rows for week {week_date}")
    print(f"   File size: {HTML_FILE.stat().st_size / 1024:.1f} KB")
    print("\n🚀 Dashboard ready — push to GitHub to go live.")


if __name__ == "__main__":
    main()
