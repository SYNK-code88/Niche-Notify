# api.py
# Combines all logic + per-user isolation using secret_key

import os
import time
import traceback
import hashlib
import psycopg2
import requests
from psycopg2.extras import RealDictCursor
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# --- Load .env file ---
load_dotenv()

# ======================================================================
# --- DB FUNCTIONS ---
# ======================================================================

def get_db_connection():
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set in environment")
    return psycopg2.connect(DATABASE_URL)

def create_schema():
    """
    Creates the monitors table if it doesn't exist.
    Added a new column: user_key (text)
    """
    create_sql = """
    CREATE TABLE IF NOT EXISTS monitors (
        id SERIAL PRIMARY KEY,
        url TEXT NOT NULL,
        css_selector TEXT NOT NULL,
        user_email TEXT NOT NULL,
        user_key TEXT NOT NULL,
        last_content TEXT,
        last_checked_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(create_sql)
        conn.commit()
        cur.close()
        conn.close()
        print("Database schema check complete. Table 'monitors' is ready.")
    except Exception as e:
        print(f"Error creating schema: {e}")
        traceback.print_exc()

def get_monitors_by_user(user_key):
    """Fetch monitors for a specific user_key"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM monitors WHERE user_key = %s ORDER BY id DESC", (user_key,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def get_all_monitors():
    """(Used by worker) Fetch all monitors"""
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
        (new_content, monitor_id)
    )
    conn.commit()
    cur.close()
    conn.close()

# ======================================================================
# --- UTILS ---
# ======================================================================

def fetch_html(url, timeout=10):
    headers = {"User-Agent": "Niche-Notify/1.0 (+https://example.com)"}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text

def extract_with_selector(html, selector):
    soup = BeautifulSoup(html, "html.parser")
    el = soup.select_one(selector)
    if not el:
        return ""
    return el.get_text(strip=True)

def compute_hash(text):
    if text is None:
        text = ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def notify_placeholder(email, url, old, new):
    print("=== ALERT ===")
    print(f"To: {email}")
    print(f"URL: {url}")
    print("Old snippet:", (old or "<empty>")[:200])
    print("New snippet:", (new or "<empty>")[:200])
    print("=============")

# ======================================================================
# --- WORKER ---
# ======================================================================

def process_once():
    monitors = get_all_monitors()
    if not monitors:
        print("Worker: No monitors found in DB.")
        return

    print(f"Worker: Processing {len(monitors)} monitor(s)...")
    
    for m in monitors:
        mid = m["id"]
        url = m["url"]
        selector = m["css_selector"]
        email = m["user_email"]
        last_content = m.get("last_content") or ""

        print(f"Worker: Checking monitor id={mid} url={url}")

        try:
            html = fetch_html(url)
            new_text = extract_with_selector(html, selector)
            if new_text is None:
                new_text = ""
            
            # Compare
            if last_content.strip() == "":
                print(f"Worker: Monitor {mid}: first snapshot recorded.")
                update_monitor_content(mid, new_text)
            else:
                if compute_hash(new_text) != compute_hash(last_content):
                    print(f"Worker: Change detected for monitor id={mid}!")
                    notify_placeholder(email, url, last_content, new_text)
                    update_monitor_content(mid, new_text)
                else:
                    print(f"Worker: No change for monitor id={mid}.")
        except Exception as exc:
            print(f"Worker: Error checking monitor id={mid} url={url}: {exc}")
            traceback.print_exc()
    
    print("Worker: Process complete.")

# ======================================================================
# --- FASTAPI APP ---
# ======================================================================

app = FastAPI(title="Niche-Notify API", version="1.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class MonitorIn(BaseModel):
    url: str
    css_selector: str
    user_email: str
    user_key: str  # NEW FIELD

@app.on_event("startup")
def on_startup():
    print("Application starting up...")
    create_schema()

@app.get("/")
def root():
    return {"message": "Welcome to Niche-Notify API"}

@app.get("/monitors")
def get_monitors_endpoint(user_key: str = Query(...)):
    """Fetch monitors belonging to a specific user_key"""
    try:
        monitors = get_monitors_by_user(user_key)
        return {"count": len(monitors), "data": monitors}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/monitors")
def add_monitor_endpoint(monitor: MonitorIn):
    """Add a new monitor"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute(
            "INSERT INTO monitors (url, css_selector, user_email, user_key, last_content) VALUES (%s, %s, %s, %s, %s) RETURNING id;",
            (monitor.url, monitor.css_selector, monitor.user_email, monitor.user_key, None)
        )
        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return {"message": "Monitor added successfully", "id": new_id}
    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/monitors/{monitor_id}")
def delete_monitor_endpoint(monitor_id: int, user_key: str = Query(...)):
    """Delete a monitor by ID only if it belongs to this user_key"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("DELETE FROM monitors WHERE id = %s AND user_key = %s RETURNING id;", (monitor_id, user_key))
        deleted_id = cur.fetchone()
        conn.commit()
        
        cur.close()
        conn.close()
        
        if deleted_id:
            return {"message": "Monitor deleted successfully", "id": deleted_id[0]}
        else:
            raise HTTPException(status_code=404, detail="Monitor not found or unauthorized")
    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/worker/run")
def run_worker_endpoint(secret: str):
    WORKER_SECRET = os.getenv("WORKER_SECRET")
    if not WORKER_SECRET:
        raise HTTPException(status_code=500, detail="Worker secret not set")
    if secret != WORKER_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")
    try:
        process_once()
        return {"message": "Worker completed successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Worker error: {str(e)}")
