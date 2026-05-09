# COT Positioning Dashboard

Live dashboard: https://chakravarthytenku.github.io/cot-dashboard/

**Login:** username `trader` / password `cot2026`

---

## Weekly Update — How It Works

Every Friday when you receive your RJO O'Brien COT PDF:

1. Go to your GitHub repo
2. Navigate to the `data/` folder
3. Click **Add file → Upload files**
4. Drop in the new PDF
5. Click **Commit changes**

That's it. GitHub automatically:
- Detects the new PDF
- Runs the extraction script
- Updates `index.html` with the new week's data
- Publishes the updated dashboard

The whole process takes about **2 minutes** after you commit the PDF.

---

## Repository Structure

```
cot-dashboard/
├── index.html                    ← The dashboard (auto-updated)
├── data/                         ← Drop weekly PDFs here
│   └── RJOCOTRecap2026-05-08.pdf
├── scripts/
│   └── extract_cot.py            ← Parses PDF, updates index.html
└── .github/
    └── workflows/
        └── update.yml            ← GitHub Actions automation
```

---

## Commodities Tracked

**Grains:** Corn, Wheat (SRW), Soybeans, KC Wheat (HRW), MN Wheat (Spring), Soybean Oil, Soybean Meal, Canola, Rough Rice

**Softs:** Coffee, Sugar No.11, Cocoa, Cotton No.2

---

## Dashboard Features

- **Net positioning** — Producer and Managed Money net over time
- **Weekly change** — WoW bar chart coloured by direction
- **Percentile rank** — where current positioning sits vs history
- **Calendar spread signal** — traffic light for spread traders based on producer short momentum and MM divergence
- **Extremes scanner** — all 13 commodities ranked by conviction score across three trigger types
- **MM spread view** — compare two commodities' MM positioning side by side
- **All commodities** — latest week snapshot across entire universe

---

## Manual Script Usage

If you want to run the extraction locally:

```bash
# Install dependencies
pip install pdfplumber pypdf
sudo apt-get install poppler-utils

# Drop PDF into data/ folder, then:
python scripts/extract_cot.py
```

---

## Changing Login Credentials

Open `index.html` in a text editor, find this section near the top:

```javascript
const USERS = {
  'trader':  'cot2026',
  'admin':   'admin123'
};
```

Edit the usernames and passwords, save, and commit to GitHub.

---

## Troubleshooting

**Workflow not triggering?**
- Check Actions tab in GitHub — confirm the workflow is enabled
- Make sure the PDF is in the `data/` folder (not the root)

**Commodity missing from update?**
- The script matches commodity names exactly as they appear in the RJO PDF
- If RJO changes their format, the `COMMODITY_MAP` in `scripts/extract_cot.py` may need updating

**Wrong date parsed?**
- The script reads the date from the PDF header line `MM/DD/YYYY - MM/DD/YY`
- If the PDF header format changes, update the `parse_date()` function

---

*Source: RJ O'Brien & Associates / CFTC Disaggregated Futures & Options Combined Report*
