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
                conti
