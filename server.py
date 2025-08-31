import json
import re
from typing import Optional
from urllib.parse import urlparse

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

app = FastAPI()

_price_re = re.compile(r"(?:\$|CAD\s*\$?)\s*([0-9]{1,3}(?:[, ][0-9]{3})*(?:\.[0-9]{2})?)", re.I)

DOMAIN_RULES = {
    "ebgames.ca": {
        "positives": ["add to cart", "buy now", "in stock", "available online",
                      "ship to home", "pick up today", "online availability: in stock"],
        "negatives": ["out of stock", "sold out", "unavailable", "not available",
                      "no longer available", "coming soon",
                      "pre-order", "preorder", "pre order",
                      "online availability: out of stock"],
    },
    "gamestop.ca": {
        "positives": ["add to cart", "buy now", "in stock", "available online"],
        "negatives": ["out of stock", "sold out", "unavailable", "not available", "coming soon",
                      "pre-order", "preorder", "pre order"],
    },
    "amazon.ca": {
        "positives": ["in stock", "add to cart", "buy now"],
        "negatives": ["currently unavailable", "temporarily out of stock", "out of stock"],
    },
}

def _jsonld_blocks(soup: BeautifulSoup):
    for tag in soup.find_all("script", type=lambda t: t and "ld+json" in t.lower()):
        try:
            txt = tag.string or tag.get_text() or ""
            yield json.loads(txt)
        except Exception:
            continue

def _walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for it in o:
            yield from _walk(it)

def availability_from_structured_data(soup: BeautifulSoup) -> Optional[str]:
    for block in _jsonld_blocks(soup):
        for node in _walk(block):
            if not isinstance(node, dict):
                continue
            if any(k in node for k in ("offers", "offer", "availability", "itemAvailability")):
                offers = []
                if "offers" in node:
                    offers = node["offers"] if isinstance(node["offers"], list) else [node["offers"]]
                elif "offer" in node:
                    offers = node["offer"] if isinstance(node["offer"], list) else [node["offer"]]
                else:
                    offers = [node]
                for off in offers:
                    if not isinstance(off, dict): continue
                    av = off.get("availability") or off.get("itemAvailability")
                    if not av: continue
                    low = str(av).lower()
                    if "instock" in low: return "Available"
                    if "outofstock" in low or "out_of_stock" in low: return "Out of stock"
                    if "preorder" in low or "pre order" in low: return "Preorder"
                    if "discontinued" in low: return "Discontinued"
    link = soup.find(attrs={"itemprop": "availability"})
    if link:
        href = (link.get("href") or "").lower()
        if "instock" in href: return "Available"
        if "outofstock" in href: return "Out of stock"
    return None

def extract_price(html: str, soup: Optional[BeautifulSoup] = None) -> Optional[float]:
    if soup is None:
        soup = BeautifulSoup(html, "html.parser")
    try:
        for block in _jsonld_blocks(soup):
            for node in _walk(block):
                if not isinstance(node, dict): continue
                if any(k in node for k in ("offers", "offer", "price", "lowPrice", "highPrice")):
                    offers = []
                    if "offers" in node:
                        offers = node["offers"] if isinstance(node["offers"], list) else [node["offers"]]
                    elif "offer" in node:
                        offers = node["offer"] if isinstance(node["offer"], list) else [node["offer"]]
                    else:
                        offers = [node]
                    for off in offers:
                        if not isinstance(off, dict): continue
                        price = off.get("price") or off.get("lowPrice") or off.get("highPrice")
                        if price is not None:
                            try:
                                return float(str(price).replace(",", "").strip())
                            except ValueError:
                                continue
    except Exception:
        pass
    m = _price_re.search(html)
    if not m: return None
    raw = m.group(1).replace(",", "").replace(" ", "")
    try:
        return float(raw)
    except ValueError:
        return None

def check_availability(html: str, url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    av = availability_from_structured_data(soup)
    if av:
        low = av.lower()
        if "out" in low: return "Out of stock"
        if "in" in low: return "Available"
        if "pre" in low: return "Preorder"
        if "discont" in low: return "Discontinued"

    # Button semantics
    for btn in soup.find_all(["button", "a"], string=True):
        t = " ".join(btn.get_text(" ", strip=True).lower().split())
        if "add to cart" in t or "buy now" in t:
            if btn.has_attr("disabled") or btn.get("aria-disabled") == "true":
                return "Out of stock"
            return "Available"

    host = (urlparse(url).netloc or "").lower().split(":")[0]
    text = " ".join(soup.get_text(' ', strip=True).lower().split())
    if host in DOMAIN_RULES:
        pos = DOMAIN_RULES[host]["positives"]
        neg = DOMAIN_RULES[host]["negatives"]
        if any(k in text for k in neg): return "Out of stock"
        if any(k in text for k in pos): return "Available"

    negatives = ["out of stock","sold out","currently unavailable","unavailable",
                 "not available","no longer available","coming soon","backordered",
                 "pre-order","preorder","pre order"]
    positives = ["in stock","available","add to cart","buy now","add to basket","add to bag",
                 "ship to home","pickup available","pick up today"]
    if any(k in text for k in negatives): return "Out of stock"
    if any(k in text for k in positives): return "Available"
    if "captcha" in text or "robot check" in text: return "Blocked"
    return "Unknown"

def browser_get_html(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--no-sandbox","--disable-gpu","--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled"
        ])
        ctx = browser.new_context(locale="en-CA")
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(800)
        html = page.content()
        browser.close()
        return html

@app.get("/probe")
def probe(url: str = Query(..., description="Product URL")):
    try:
        html = browser_get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        availability = check_availability(html, url)
        price = extract_price(html, soup)
        return {"ok": True, "availability": availability, "price": price}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
