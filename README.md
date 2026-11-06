# Vendor report automation (demo)

Turns the weekly vendor reporting templates (Excel) into a clean dataset, pacing,
a Data Studio-style PDF report and a PowerPoint deck, with no copy-pasting.

```
python3 run_demo.py
```

Put vendor files in `data/vendor_files/` (and list them in `CONFIG` in `run_demo.py`).
Outputs land in `output/`:

| File | What it is |
|---|---|
| `master_dataset.csv / .xlsx` | One clean row per vendor / week / placement / creative / size. This is the Google Sheet feed Data Studio would read. |
| `validation_report.xlsx` | Submission tracker, row-level issues, template problems, auto-fixes, reconciliation vs. vendor summary tabs |
| `pacing.xlsx` | Delivered vs. planned (from each template's Resources tab) per placement |
| `campaign_report.pdf / .html` | Report in the Data Studio layout |
| `campaign_deck.pptx` | Deck in the monthly presentation layout |

## Pipeline
1. **Ingest** (`reporting/ingest.py`): finds the header row, maps columns by name (tolerates template variations), cleans `-`, `$ -`, non-breaking spaces, size formats (`300 X 250` → `300x250`), and reads the plan from the Resources tab.
2. **Validate** (`reporting/model.py`): required fields, week ranges, placement in IO, added-value vs. cost method, spend vs. impressions × CPM rate, clicks/completions over 100%, duplicates, missing weekly submissions, broken template dropdowns/formulas. Rows with errors are held back from KPIs.
3. **Model**: channel sections (Display, CTV, Audio streaming vs. companion banner by creative size, OOH), KPI targets parsed from the template, paid vs. blended metrics, pacing index = % delivered / % of flight elapsed.
4. **Render** (`reporting/report.py`, `reporting/deck.py`): PDF via headless Chromium; deck via python-pptx. Highlights are auto-drafted by rules in `reporting/narrative.py` for the team to edit.
