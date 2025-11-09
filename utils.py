# utils.py
import requests
from bs4 import BeautifulSoup
import hashlib
import os

def fetch_html(url, timeout=10):
    """
    Returns the response text for a given URL or raises requests exceptions.
    """
    headers = {
        "User-Agent": "Niche-Notify/1.0 (+https://example.com)"
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text

def extract_with_selector(html, selector):
    """
    Parse HTML and return the text inside the first matched CSS selector.
    If selector not found, returns an empty string.
    """
    soup = BeautifulSoup(html, "html.parser")
    el = soup.select_one(selector)
    if not el:
        return ""
    return el.get_text(strip=True)

def compute_hash(text):
    """
    Return a short hash for the text (useful to compare changes).
    """
    if text is None:
        text = ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def notify_placeholder(email, url, old, new):
    """
    Phase-1 notifier: just prints to console.
    Replace this with SendGrid in Phase 5.
    """
    print("=== ALERT ===")
    print(f"To: {email}")
    print(f"URL: {url}")
    print("Old snippet:", (old or "<empty>")[:200])
    print("New snippet:", (new or "<empty>")[:200])
    print("=============")
