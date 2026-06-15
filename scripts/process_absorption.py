#!/usr/bin/env python3
"""
scripts/process_absorption.py
Reads all Excel files from absorption-data/, merges with history,
and injects data into absorption.html before // @@END_DATA@@
Run from repo root: python scripts/process_absorption.py
"""

import pandas as pd
import json, os, glob, re
from datetime import datetime, date

# ── Paths (all relative to repo root) ────────────────────────────────────────
ROOT         = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR     = os.path.join(ROOT, "absorption-data")
HISTORY_FILE = os.path.join(ROOT, "absorption-history.json")
HTML_FILE    = os.path.join(ROOT, "absorption.html")

ALL_COLS = ["Instrument","Yesterday Volume","10D Avg Vol","Vol Ratio",
            "Yesterday Range","5D ATR","Max Volume Price","Date"]

PRODUCTS = {
    "Wheat":       ["W", "KW"],
    "Corn":        ["CN"],
    "Soybeans":    ["SB"],
    "Soy Meal":    ["SM"],
    "Soy Oil":     ["BO"],
    "Canola / RS": ["CRS","RS"],
    "Palm Oil":    ["FCPO"],
}

def prefix_of(inst):
    for key, prefixes in PRODUCTS.items():
        for p in prefixes:
            if str(inst).startswith(p):
                return key
    return "Other"

def load_excel_files():
    frames = []
    for fp in glob.glob(os.path.join(DATA_DIR, "*.xlsx")):
        try:
            df = pd.read_excel(fp)
            df.columns = [c.strip() for c in df.columns]
            df["Date"] = pd.to_datetime(df["Date"]).dt.date
            for col in ALL_COLS:
                if col not in df.columns:
                    df[col] = None
            frames.append(df[ALL_COLS])
            print(f"  Loaded: {os.path.basename(fp)} ({len(df)} rows)")
        except Exception as e:
            print(f"  SKIP {fp}: {e}")
    if not frames:
        return pd.DataFrame(columns=ALL_COLS)
    return pd.concat(frames, ignore_index=True).drop_duplicates(
        subset=["Instrument","Date"], keep="last")

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return pd.DataFrame(columns=ALL_COLS)
    with open(HISTORY_FILE) as f:
        df = pd.DataFrame(json.load(f))
    if df.empty:
        return df
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    for col in ALL_COLS:
        if col not in df.columns:
            df[col] = None
    return df

def save_history(df):
    out = df.copy()
    out["Date"] = out["Date"].astype(str)
    with open(HISTORY_FILE, "w") as f:
        json.dump(out.to_dict(orient="records"), f, indent=2)

def to_serialisable(val):
    if val is None:
        return None
    if isinstance(val, float) and (val != val):   # NaN
        return None
    if isinstance(val, (date, datetime)):
        return str(val)
    if str(val) in ("N/A", "nan", ""):
        return None
    return val

def main():
    print("=== Absorption Matrix Processor ===")

    df_new  = load_excel_files()
    df_hist = load_history()

    df_all = pd.concat([df_hist, df_new], ignore_index=True)
    df_all = df_all.drop_duplicates(subset=["Instrument","Date"], keep="last")
    df_all["Product"] = df_all["Instrument"].map(prefix_of)

    save_history(df_all)

    all_dates = sorted(df_all["Date"].unique(), reverse=True)
    print(f"History: {len(df_all)} rows across {len(all_dates)} dates")
    print(f"Latest 5 dates: {[str(d) for d in all_dates[:5]]}")

    records = []
    for _, row in df_all.iterrows():
        records.append({col: to_serialisable(row.get(col)) for col in ALL_COLS + ["Product"]})

    payload = {
        "generated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "all_dates": [str(d) for d in all_dates],
        "products":  list(PRODUCTS.keys()),
        "records":   records,
    }

    js_block = "const ABSORPTION_DATA = " + json.dumps(payload, indent=2) + ";\n"

    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    marker = "// @@END_DATA@@"
    if marker not in html:
        print(f"ERROR: marker '{marker}' not found in {HTML_FILE}")
        return 1

    new_html = re.sub(
        r'(// @@BEGIN_DATA@@\n).*?(' + re.escape(marker) + r')',
        r'\1' + js_block + r'\2',
        html, flags=re.DOTALL
    )

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(new_html)

    print(f"✓ Injected data into absorption.html")
    return 0

if __name__ == "__main__":
    exit(main())
