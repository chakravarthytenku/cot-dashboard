#!/usr/bin/env python3
"""
extract_delivery.py — CME Deliverable Commodities Under Registration parser
Scans delivery-data/ for .xls/.xlsx files, extracts Total Outstanding per product,
merges with delivery-history.json, and injects into delivery.html.

Note: Rough Rice uses a 'Totals' row instead of 'Total Outstanding'.
      The script handles this automatically.
"""

import os, json, re, glob
from datetime import datetime

try:
    import xlrd
except ImportError:
    os.system("pip install xlrd --break-system-packages -q")
    import xlrd

DATA_DIR     = "delivery-data"
HISTORY_FILE = "delivery-history.json"
DASHBOARD    = "delivery.html"

PRODUCT_MAP = {
    "WHEAT FUTURES":        "Wheat",
    "CORN FUTURES":         "Corn",
    "OATS FUTURES":         "Oats",
    "SOYBEAN FUTURES":      "Soybeans",
    "SOYBEAN OIL FUTURES":  "Soybean Oil",
    "SOYBEAN MEAL FUTURES": "Soybean Meal",
    "ROUGH RICE FUTURES":   "Rough Rice",
    "KC WHEAT FUTURES":     "KC Wheat",
    "ETHANOL FUTURES":      "Ethanol",
}

# Products that use 'Totals' row instead of 'Total Outstanding'
USES_TOTALS_ROW = {"Rough Rice"}


def parse_xls(path):
    """Return (date_str YYYY-MM-DD, {product: total_outstanding}) from one XLS."""
    wb = xlrd.open_workbook(path)
    ws = wb.sheet_by_name("CBOT")

    # Date is in row 3, col 5 — either float serial or string "MM/DD/YYYY"
    raw_date = ws.cell_value(3, 5)
    if isinstance(raw_date, float):
        dt = xlrd.xldate_as_datetime(raw_date, wb.datemode)
        date_str = dt.strftime("%Y-%m-%d")
    else:
        dt = datetime.strptime(str(raw_date).strip(), "%m/%d/%Y")
        date_str = dt.strftime("%Y-%m-%d")

    products = {}
    current_product = None

    for r in range(ws.nrows):
        col0 = str(ws.cell_value(r, 0)).strip()
        col2 = str(ws.cell_value(r, 2)).strip()
        col3 = ws.cell_value(r, 3)

        # Detect product header
        if col0 and col0.upper() in PRODUCT_MAP:
            current_product = PRODUCT_MAP[col0.upper()]

        if current_product is None:
            continue

        # 'Total Outstanding' row — used by most products
        if col2 == "Total Outstanding":
            try:
                products[current_product] = int(float(col3)) if col3 != "" else 0
            except (ValueError, TypeError):
                products[current_product] = 0

        # 'Totals' row — used by Rough Rice (and any future products without Total Outstanding)
        elif col2 == "Totals" and current_product in USES_TOTALS_ROW:
            try:
                products[current_product] = int(float(col3)) if col3 != "" else 0
            except (ValueError, TypeError):
                products[current_product] = 0

    return date_str, products


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return {}


def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)
    print(f"  History saved ({len(history)} dates)")


def inject_into_html(history):
    if not os.path.exists(DASHBOARD):
        print(f"  ERROR: {DASHBOARD} not found")
        return

    with open(DASHBOARD) as f:
        html = f.read()

    sorted_history = dict(sorted(history.items()))
    json_blob = json.dumps(sorted_history, indent=2)

    marker_start = "// @@DELIVERY_DATA_START@@"
    marker_end   = "// @@DELIVERY_DATA_END@@"

    if marker_start not in html:
        print(f"  ERROR: markers not found in {DASHBOARD}")
        return

    pattern = re.compile(
        re.escape(marker_start) + r".*?" + re.escape(marker_end),
        re.DOTALL
    )
    replacement = f"{marker_start}\nconst DELIVERY_DATA = {json_blob};\n{marker_end}"
    html = pattern.sub(replacement, html)

    with open(DASHBOARD, "w") as f:
        f.write(html)

    print(f"  Injected {len(sorted_history)} dates into {DASHBOARD}")


def main():
    print("=== extract_delivery.py ===")
    os.makedirs(DATA_DIR, exist_ok=True)

    history = load_history()
    print(f"  Existing history: {len(history)} dates")

    files = sorted(
        glob.glob(os.path.join(DATA_DIR, "*.xls")) +
        glob.glob(os.path.join(DATA_DIR, "*.xlsx"))
    )
    added = 0

    for path in files:
        try:
            date_str, products = parse_xls(path)
            if date_str in history:
                print(f"  SKIP {os.path.basename(path)} → date {date_str} already in history")
                continue
            history[date_str] = products
            print(f"  ADDED {os.path.basename(path)} → {date_str}: {products}")
            added += 1
        except Exception as e:
            print(f"  ERROR {os.path.basename(path)}: {e}")

    save_history(history)
    inject_into_html(history)
    print(f"  Done. Added {added} new date(s).")


if __name__ == "__main__":
    main()
