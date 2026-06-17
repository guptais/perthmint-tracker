#!/usr/bin/env python3
"""
Perth Mint Cast Bar Price Tracker
==================================
Scrapes https://www.perthmint.com/shop/bullion/cast-bars/ and appends
prices to a CSV log. Run manually or schedule via cron/Task Scheduler.

Requirements:
    1. Create and activate venv
    ```
    python3 -m venv perthmint-tracker
    source perthmint-tracker/bin/activate        # Mac/Linux
    perthmint-tracker\\Scripts\\activate         # Windows

    # 2. Install dependencies
    pip install playwright beautifulsoup4
    playwright install chromium

    # 3. Run the tracker
    python perthmint_price_tracker.py

    # 4. Deactivate when done
    deactivate
    ```

Usage:
    python perthmint_price_tracker.py
    python perthmint_price_tracker.py --output my_prices.csv
    python perthmint_price_tracker.py --debug   # prints scraped HTML snippet

Schedule (cron example — every day at 9am):
    0 9 * * * /usr/bin/python3 /path/to/perthmint_price_tracker.py

Schedule (Windows Task Scheduler):
    Action: python C:\\path\\to\\perthmint_price_tracker.py
"""

import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup

URL = "https://www.perthmint.com/shop/bullion/cast-bars/"
DEFAULT_OUTPUT = "perthmint_cast_bar_prices.csv"
CSV_HEADERS = ["timestamp", "name", "price_aud", "price_raw", "url"]


# ── Scraping ──────────────────────────────────────────────────────────────────

def fetch_page(url: str) -> str:
    """Fetch page HTML using Playwright (handles JS-rendered content)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page.goto(url, wait_until="networkidle", timeout=30_000)
        # Extra wait for price elements to load
        try:
            page.wait_for_selector("[class*='price'], [class*='product']", timeout=10_000)
        except Exception:
            pass  # Continue even if selector never appears
        html = page.content()
        browser.close()
    return html


def parse_products(html: str) -> list[dict]:
    """
    Extract product name + price from Perth Mint product cards.

    Perth Mint uses Umbraco CMS. Product cards typically have:
      - A title element: h2, h3, or [class*='title'] / [class*='name']
      - A price element: [class*='price']

    This parser tries multiple selector strategies and picks whichever
    finds both a name and a price. Adjust SELECTORS if the site changes.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Strategy 1: explicit product card containers
    CARD_SELECTORS = [
        "article",
        "[class*='product-card']",
        "[class*='product-tile']",
        "[class*='product-item']",
        "[class*='ProductCard']",
        "[class*='item-card']",
    ]

    PRICE_SELECTORS = [
        "[class*='price']",
        "[class*='Price']",
        "[data-price]",
    ]

    NAME_SELECTORS = [
        "h2", "h3",
        "[class*='title']",
        "[class*='name']",
        "[class*='Title']",
    ]

    products = []
    seen = set()
    timestamp = datetime.now().isoformat(timespec="seconds")

    def add_product(name: str, price_raw: str, price_aud: str) -> None:
        key = (name, price_aud)
        if key in seen:
            return
        seen.add(key)
        products.append({
            "timestamp": timestamp,
            "name": name,
            "price_aud": price_aud,
            "price_raw": price_raw,
            "url": URL,
        })

    for card_sel in CARD_SELECTORS:
        cards = soup.select(card_sel)
        if not cards:
            continue

        for card in cards:
            name = _extract_text(card, NAME_SELECTORS)
            price_raw, price_aud = _extract_price(card, PRICE_SELECTORS)

            if name and price_aud:
                add_product(name, price_raw, price_aud)

        if products:
            return products  # Found results with this card selector

    # Strategy 2: flat scan — find all price elements and work outward
    for price_el in soup.select(", ".join(PRICE_SELECTORS)):
        price_raw, price_aud = _extract_price_from_element(price_el)
        if not price_aud:
            continue

        # Walk up the DOM to find a sibling/parent name
        name = ""
        parent = price_el.parent
        for _ in range(5):  # up to 5 levels up
            if not parent:
                break
            name = _extract_text(parent, NAME_SELECTORS, exclude=price_el)
            if name:
                break
            parent = parent.parent

        if name:
            add_product(name, price_raw, price_aud)

    return products


def _extract_text(container, selectors: list[str], exclude=None) -> str:
    for sel in selectors:
        el = container.select_one(sel)
        if el and el != exclude:
            text = el.get_text(strip=True)
            if text and len(text) > 2:
                return text
    return ""


def _extract_price(container, selectors: list[str]) -> tuple[str, str]:
    for sel in selectors:
        el = container.select_one(sel)
        if el:
            raw, numeric = _extract_price_from_element(el)
            if numeric:
                return raw, numeric
    return "", ""


def _extract_price_from_element(el) -> tuple[str, str]:
    """Return (raw_text, numeric_string) e.g. ('AUD $3,456.78', '3456.78')."""
    # Check data-price attribute first
    data_price = el.get("data-price", "")
    if data_price:
        cleaned = re.sub(r"[^\d.]", "", data_price)
        if cleaned:
            return data_price, cleaned

    text = el.get_text(strip=True)
    # Match patterns like $3,456.78 or AUD 3456.78 or 3,456.78
    match = re.search(r"[\d]{1,3}(?:,\d{3})*(?:\.\d{1,2})?", text.replace(" ", ""))
    if match:
        numeric = re.sub(r"[^\d.]", "", match.group())
        return text, numeric
    return "", ""


# ── CSV output ─────────────────────────────────────────────────────────────────

def append_to_csv(products: list[dict], output_path: Path) -> None:
    """Append rows to CSV, creating with header if it doesn't exist."""
    is_new = not output_path.exists()
    with open(output_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        if is_new:
            writer.writeheader()
        writer.writerows(products)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Track Perth Mint cast bar prices")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="CSV output file path")
    parser.add_argument("--debug", action="store_true", help="Print first 2000 chars of fetched HTML")
    args = parser.parse_args()

    output_path = Path(args.output)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Fetching {URL} ...")
    html = fetch_page(URL)

    if args.debug:
        print("\n── HTML SNIPPET (first 2000 chars) ──")
        print(html[:2000])
        print("──────────────────────────────────────\n")

    products = parse_products(html)

    if not products:
        print("⚠️  No products found. The site structure may have changed.")
        print("   Run with --debug to inspect the fetched HTML.")
        print("   You may need to update CARD_SELECTORS or NAME_SELECTORS in this script.")
        sys.exit(1)

    append_to_csv(products, output_path)

    print(f"✅ Logged {len(products)} products to: {output_path.resolve()}")
    for p in products:
        print(f"   {p['name']:<45} AUD {p['price_aud']}")


if __name__ == "__main__":
    main()
