# api.py
# Final version — includes multi-user logic, auto DB migration, and APScheduler

import os
import time
import traceback
import hashlib
import psycopg2
import requests
from psycopg2.extras import RealDictCursor
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

# -----------------------------------------------------------------------------
# ENVIRONMENT SETUP
# -----------------------------------------------------------------------------
load_dotenv()

# -----------------------------------------------------------------------------
# DATABASE FUNCTIONS
# -----------------------------------------------------------------------------
def get_db_connection():
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set in environment")
    return psycopg2.connect(DATABASE_URL)

def create_schema():
    """Create table if missing and add user_key if not already present."""
    create_sql = """
    CREATE TABLE IF NOT EXISTS monitors (
        id SERIAL PRIMARY KEY,
        url TEXT NOT NULL,
        css_selector TEXT NOT NULL,
        user_email TEXT NOT NULL,
        last_content TEXT,
        last_checked_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """
    alter_sql = """
    ALTER TABLE monitors ADD COLUMN IF NOT EXISTS user_key TEXT;
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(create_sql)
        cur.execute(alter_sql)
        conn.commit()
        cur.close()
        conn.close()
        print("✅ Database schema up-to-date (user_key included).")
    except Exception as e:
        print("❌ Database setup error:", e)
        traceback.print_exc()

def get_monitors_by_user(user_key):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM monitors WHERE user_key = %s ORDER BY id DESC", (user_key,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def get_all_monitors():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM monitors")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def update_monitor_content(monitor_id, new_content):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE monitors SET last_content = %s, last_checked_at = NOW() WHERE id = %s",
        (new_content, monitor_id),
    )
    conn.commit()
    cur.close()
    conn.close()

# -----------------------------------------------------------------------------
# SCRAPING UTILS
# -----------------------------------------------------------------------------
def fetch_html(url, timeout=10):
    headers = {"User-Agent": "Niche-Notify/1.0 (+https://example.com)"}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text

def extract_with_selector(html, selector):
    soup = BeautifulSoup(html, "html.parser")
    el = soup.select_one(selector)
    return el.get_text(strip=True) if el else ""

def compute_hash(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()

def notify_placeholder(email, url, old, new):
    """Replace this with your real notification system."""
    print("\n🔔 CHANGE DETECTED 🔔")
    print(f"To: {email}")
    print(f"URL: {url}")
    print("Old:", (old or "<empty>")[:150])
    print("New:", (new or "<empty>")[:150])
    print("--------------------")

# -----------------------------------------------------------------------------
# BACKGROUND WORKER
# -----------------------------------------------------------------------------
def process_once():
    """Check all monitors for updates once."""
    monitors = get_all_monitors()
    if not monitors:
        print("🕒 Worker: No monitors found.")
        return

    print(f"🕒 Worker: Checking {len(monitors)} monitors...")

    for m in monitors:
        mid = m["id"]
        url = m["url"]
        selector = m["css_selector"]
        email = m["user_email"]
        last_content = m.get("last_content") or ""

        try:
            html = fetch_html(url)
            new_text = extract_with_selector(html, selector)

            if last_content.strip() == "":
                update_monitor_content(mid, new_text)
                print(f"Monitor {mid}: Initial snapshot saved.")
            elif compute_hash(new_text) != compute_hash(last_content):
                print(f"Monitor {mid}: Change detected!")
                notify_placeholder(email, url, last_content, new_text)
                update_monitor_content(mid, new_text)
            else:
                print(f"Monitor {mid}: No change.")
        except Exception as e:
            print(f"Monitor {mid}: Error - {e}")
            traceback.print_exc()

    print("✅ Worker: Cycle complete.\n")

# -----------------------------------------------------------------------------
# FASTAPI SETUP
# -----------------------------------------------------------------------------
app = FastAPI(title="Niche Notify API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class MonitorIn(BaseModel):
    url: str
    css_selector: str
    user_email: str
    user_key: str

# -----------------------------------------------------------------------------
# STARTUP LOGIC + SCHEDULER
# -----------------------------------------------------------------------------
@app.on_event("startup")
def startup_event():
    print("🚀 Server starting up...")
    create_schema()

    scheduler = BackgroundScheduler()
    scheduler.add_job(process_once, "interval", minutes=15, id="worker", replace_existing=True)
    scheduler.start()
    print("⏰ APScheduler started (every 15 minutes).")

@app.on_event("shutdown")
def shutdown_event():
    print("🛑 Server shutting down...")

# -----------------------------------------------------------------------------
# API ROUTES
# -----------------------------------------------------------------------------
@app.get("/")
def home():
    return {"message": "Welcome to Niche Notify API", "version": "2.0"}

@app.get("/monitors")
def list_monitors(user_key: str = Query(...)):
    try:
        data = get_monitors_by_user(user_key)
        return {"count": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/monitors")
def add_monitor(m: MonitorIn):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO monitors (url, css_selector, user_email, user_key)
            VALUES (%s, %s, %s, %s)
            RETURNING id;
            """,
            (m.url, m.css_selector, m.user_email, m.user_key),
        )
        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return {"message": "Monitor added successfully", "id": new_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/monitors/{monitor_id}")
def delete_monitor(monitor_id: int, user_key: str = Query(...)):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM monitors WHERE id = %s AND user_key = %s RETURNING id;", (monitor_id, user_key))
        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        if result:
            return {"message": "Monitor deleted", "id": result[0]}
        else:
            raise HTTPException(status_code=404, detail="Not found or unauthorized")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/worker/run")
def manual_run(secret: str):
    """Manually trigger the background job."""
    if secret != os.getenv("WORKER_SECRET"):
        raise HTTPException(status_code=403, detail="Invalid secret")
    try:
        process_once()
        return {"message": "Worker completed successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

