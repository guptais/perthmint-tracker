# Perth Mint Price Tracker

Scrapes gold and silver cast bar prices from [perthmint.com](https://www.perthmint.com/shop/bullion/cast-bars/) and appends them to a CSV log. A GitHub Actions workflow runs daily and commits updated prices. A GitHub Pages dashboard visualises the history.

**Live dashboard:** https://guptais.github.io/perthmint-tracker/

## How it works

| Component | Role |
|---|---|
| `perthmint_price_tracker.py` | Playwright scraper — fetches prices, appends to CSV |
| `perthmint_cast_bar_prices.csv` | Append-only price log |
| `.github/workflows/track_prices.yml` | Runs scraper daily at 9am UTC, commits updated CSV |
| `index.html` | GitHub Pages dashboard — fetches CSV, renders table + chart |

## Run locally

```bash
python3 -m venv perthmint-tracker
source perthmint-tracker/bin/activate
pip install -r requirements.txt
playwright install chromium
python perthmint_price_tracker.py
```

Optional flags:

```
--output FILE   write to a custom CSV path (default: perthmint_cast_bar_prices.csv)
--debug         print scraped HTML snippet for troubleshooting
```
