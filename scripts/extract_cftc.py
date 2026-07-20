#!/usr/bin/env python3
"""
extract_cftc.py — CFTC Disaggregated Ag Combined COT parser

Scans cftc-data/ for weekly .txt reports (the plain-text export of
https://www.cftc.gov/dea/options/ag_lof.htm), merges every week found into
cftc-history.json, and injects the merged dataset into cftc.html between
the // @@CFTC_DATA_START@@ / // @@CFTC_DATA_END@@ markers -- same pattern
used by extract_delivery.py / delivery.html in this repo.

Usage:
    python scripts/extract_cftc.py

Idempotent: re-running with the same files just re-parses and overwrites
matching dates, so it's safe to run on every push.
"""

import re
import json
import glob
import os
import sys

DATA_DIR = "cftc-data"
HISTORY_FILE = "cftc-history.json"
DASHBOARD = "cftc.html"

START_MARKER = "// @@CFTC_DATA_START@@"
END_MARKER = "// @@CFTC_DATA_END@@"

# CFTC market name (as printed in the report) -> (dashboard code, display name, sector)
NAME_MAP = {
    'WHEAT-SRW': ('00160', 'Wheat - SRW', 'Grains'),
    'WHEAT-HRW': ('00161', 'Wheat - HRW', 'Grains'),
    'WHEAT-HRSpring': ('00162', 'Wheat - HR Spring', 'Grains'),
    'CORN': ('00260', 'Corn', 'Grains'),
    'ROUGH RICE': ('03960', 'Rough Rice', 'Grains'),
    'SOYBEANS': ('00560', 'Soybeans', 'Oilseeds'),
    'MINI SOYBEANS': ('00560M', 'Mini Soybeans', 'Oilseeds'),
    'SOYBEAN OIL': ('00760', 'Soybean Oil', 'Oilseeds'),
    'SOYBEAN MEAL': ('02660', 'Soybean Meal', 'Oilseeds'),
    'USD Malaysian Crude Palm Oil C': ('03702', 'Malaysian Palm Oil (USD)', 'Oilseeds'),
    'CANOLA': ('13573', 'Canola', 'Oilseeds'),
    'LEAN HOGS': ('05464', 'Lean Hogs', 'Livestock'),
    'LIVE CATTLE': ('05764', 'Live Cattle', 'Livestock'),
    'FEEDER CATTLE': ('06164', 'Feeder Cattle', 'Livestock'),
    'BUTTER (CASH SETTLED)': ('05064', 'Butter', 'Dairy'),
    'MILK, Class III': ('05264A', 'Milk, Class III', 'Dairy'),
    'NON FAT DRY MILK': ('05264B', 'Non Fat Dry Milk', 'Dairy'),
    'CME MILK IV': ('05264C', 'CME Milk IV', 'Dairy'),
    'DRY WHEY': ('05264D', 'Dry Whey', 'Dairy'),
    'CHEESE (CASH-SETTLED)': ('06364', 'Cheese', 'Dairy'),
    'COTTON NO. 2': ('03366', 'Cotton No. 2', 'Softs'),
    'FRZN CONCENTRATED ORANGE JUICE': ('04070', 'FCOJ', 'Softs'),
    'COCOA': ('07373', 'Cocoa', 'Softs'),
    'SUGAR NO. 11': ('08073', 'Sugar No. 11', 'Softs'),
    'COFFEE CALENDAR SPREAD OPTIONS': ('08373S', 'Coffee Cal. Spread Opts', 'Softs'),
    'COFFEE C': ('08373', 'Coffee C', 'Softs'),
}
SORTED_KEYS = sorted(NAME_MAP.keys(), key=len, reverse=True)

MONTHS = {
    'January': 1, 'February': 2, 'March': 3, 'April': 4, 'May': 5, 'June': 6,
    'July': 7, 'August': 8, 'September': 9, 'October': 10, 'November': 11, 'December': 12
}
DATE_RE = re.compile(r'Combined,\s*([A-Za-z]+ \d{1,2}, \d{4})')


def num(s):
    s = s.strip().replace(',', '')
    if s in ('', '.'):
        return 0
    return float(s) if '.' in s else int(s)


def nums_from(line):
    segs = line.split(':')
    out = []
    for seg in segs[1:]:
        out.extend(seg.split())
    return [num(x) for x in out]


def crop_block(line):
    v = nums_from(line)
    oi = v[0]
    p_l, p_s, sw_l, sw_s, sw_spread, mm_l, mm_s, mm_spread, oth_l, oth_s, oth_spread = v[1:12]
    return {
        'oi': oi,
        'p': {'l': p_l, 's': p_s},
        'sw': {'l': sw_l, 's': sw_s},
        'mm': {'l': mm_l, 's': mm_s},
        'oth': {'l': oth_l, 's': oth_s},
    }


def conv_date(s):
    parts = s.replace(',', '').split()
    mon, day, year = parts[0], parts[1], parts[2]
    return f"{year}-{MONTHS[mon]:02d}-{int(day):02d}"


def parse_report_text(content):
    blocks = re.split(r'\n(?=[A-Za-z0-9][^\n]*?- [A-Z].*?Code-\d+)', content)
    markets = []
    date_str = None

    for b in blocks:
        header_match = re.match(r'([^\n]*?)\s*Code-(\d+)', b)
        if not header_match:
            continue
        full_name = header_match.group(1).strip()
        key = next((k for k in SORTED_KEYS if full_name.startswith(k)), None)
        if not key:
            continue
        code, disp, sector = NAME_MAP[key]

        lines = b.split('\n')
        all_idxs = [i for i, l in enumerate(lines) if l.strip().startswith('All')]
        old_idxs = [i for i, l in enumerate(lines) if l.strip().startswith('Old')]
        other_idxs = [i for i, l in enumerate(lines) if l.strip().startswith('Other')]
        if not all_idxs or not old_idxs or not other_idxs:
            print(f"  ! skipping {full_name}: unexpected block structure", file=sys.stderr)
            continue

        pos_line = lines[all_idxs[0]]
        old_pos_line = lines[old_idxs[0]]
        other_pos_line = lines[other_idxs[0]]
        traders_line = lines[all_idxs[2]] if len(all_idxs) > 2 else None
        conc_line = lines[all_idxs[3]] if len(all_idxs) > 3 else None

        chg_line = None
        for i, l in enumerate(lines):
            if 'Changes in Commitments from' in l:
                chg_line = lines[i + 1]
                break

        pvals = nums_from(pos_line)
        oi = pvals[0]
        (p_l, p_s, sw_l, sw_s, sw_spread, mm_l, mm_s, mm_spread,
         oth_l, oth_s, oth_spread, nr_l, nr_s) = pvals[1:14]

        if chg_line:
            cvals = nums_from(chg_line)
            oiChg = cvals[0]
            (p_lc, p_sc, sw_lc, sw_sc, sw_schg, mm_lc, mm_sc, mm_schg,
             oth_lc, oth_sc, oth_schg) = cvals[1:12]
        else:
            oiChg = p_lc = p_sc = sw_lc = sw_sc = mm_lc = mm_sc = oth_lc = oth_sc = 0

        if conc_line:
            cc = nums_from(conc_line)
            n4l, n4s, n8l, n8s = cc[4], cc[5], cc[6], cc[7]
        else:
            n4l = n4s = n8l = n8s = 0

        traders = nums_from(traders_line)[0] if traders_line else 0

        dm = DATE_RE.search(b)
        if dm:
            date_str = conv_date(dm.group(1))

        markets.append({
            'code': code, 'name': disp, 'sector': sector,
            'oi': oi, 'oiChg': oiChg,
            'p': {'l': p_l, 's': p_s, 'lc': p_lc, 'sc': p_sc},
            'sw': {'l': sw_l, 's': sw_s, 'lc': sw_lc, 'sc': sw_sc, 'spread': sw_spread},
            'mm': {'l': mm_l, 's': mm_s, 'lc': mm_lc, 'sc': mm_sc, 'spread': mm_spread},
            'oth': {'l': oth_l, 's': oth_s, 'lc': oth_lc, 'sc': oth_sc, 'spread': oth_spread},
            'conc': {'n4l': n4l, 'n4s': n4s, 'n8l': n8l, 'n8s': n8s},
            'traders': traders,
            'old': crop_block(old_pos_line),
            'other': crop_block(other_pos_line),
        })

    if not date_str or not markets:
        return None
    return {'date': date_str, 'markets': markets}


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, encoding='utf-8') as f:
            return json.load(f)
    return []


def inject_into_dashboard(merged_weeks):
    if not os.path.exists(DASHBOARD):
        print(f"  ! {DASHBOARD} not found, skipping HTML injection", file=sys.stderr)
        return
    with open(DASHBOARD, encoding='utf-8') as f:
        html = f.read()

    if START_MARKER not in html or END_MARKER not in html:
        print(f"  ! markers not found in {DASHBOARD}, skipping HTML injection", file=sys.stderr)
        return

    pre, rest = html.split(START_MARKER, 1)
    _, post = rest.split(END_MARKER, 1)
    data_js = json.dumps(merged_weeks, separators=(',', ':'))
    new_block = f"{START_MARKER}\nconst WEEKS = {data_js};\n{END_MARKER}"
    new_html = pre + new_block + post

    with open(DASHBOARD, 'w', encoding='utf-8') as f:
        f.write(new_html)
    print(f"  -> injected {len(merged_weeks)} weeks into {DASHBOARD}")


def main():
    combined = load_history()
    by_date = {w['date']: w for w in combined}

    txt_files = sorted(glob.glob(os.path.join(DATA_DIR, '*.txt')))
    if not txt_files:
        print(f"No .txt files found in {DATA_DIR}/ -- nothing to do.")
        return

    for path in txt_files:
        print(f"Parsing {os.path.basename(path)} ...")
        with open(path, encoding='utf-8', errors='replace') as f:
            content = f.read()
        week = parse_report_text(content)
        if week is None:
            print(f"  ! could not parse a valid report from {path}", file=sys.stderr)
            continue
        existed = week['date'] in by_date
        by_date[week['date']] = week
        print(f"  -> {'updated' if existed else 'added'} week {week['date']} ({len(week['markets'])} markets)")

    merged = sorted(by_date.values(), key=lambda w: w['date'])
    with open(HISTORY_FILE, 'w') as f:
        json.dump(merged, f, separators=(',', ':'))

    inject_into_dashboard(merged)

    print(f"\nDone. {len(merged)} total weeks "
          f"({merged[0]['date']} -> {merged[-1]['date']}).")


if __name__ == '__main__':
    main()
