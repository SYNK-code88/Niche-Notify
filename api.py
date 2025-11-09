# api.py
# Combines all logic from api.py, db.py, utils.py, and worker.py

import os
import time
import traceback
import hashlib
import psycopg2
import requests
from psycopg2.extras import RealDictCursor
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# --- Load .env file ---
# This loads DATABASE_URL and the new WORKER_SECRET
load_dotenv()

# ==============================================================================
# --- DB.PY FUNCTIONS ---
# ==============================================================================

def get_db_connection():
    """
    Returns a new psycopg2 connection using DATABASE_URL env variable.
    """
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set in environment")
    return psycopg2.connect(DATABASE_URL)

def create_schema():
    """
    Creates the monitors table if it doesn't exist.
    Run this once on startup.
    """
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

def get_all_monitors():
    """
    Returns a list of monitors as dicts:
    [{id, url, css_selector, user_email, last_content, last_checked_at}, ...]
    """
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM monitors")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def update_monitor_content(monitor_id, new_content):
    """
    Update last_content and last_checked_at for a monitor.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE monitors SET last_content = %s, last_checked_at = NOW() WHERE id = %s",
        (new_content, monitor_id)
    )
    conn.commit()
    cur.close()
    conn.close()

# ==============================================================================
# --- UTILS.PY FUNCTIONS ---
# ==============================================================================

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
    """
    print("=== ALERT ===")
    print(f"To: {email}")
    print(f"URL: {url}")
    print("Old snippet:", (old or "<empty>")[:200])
    print("New snippet:", (new or "<empty>")[:200])
    print("=============")

# ==============================================================================
# --- WORKER.PY FUNCTIONS ---
# ==============================================================================

def process_once():
    """
    This is the main worker logic, moved into a function.
    """
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
                # First run
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

# ==============================================================================
# --- API.PY LOGIC (FastAPI App) ---
# ==============================================================================

app = FastAPI(title="Niche-Notify API", version="1.0")

# --- CORS middleware ---
origins = ["*"]  # Allows all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Model ---
class MonitorIn(BaseModel):
    url: str
    css_selector: str
    user_email: str

# --- Startup Event ---
@app.on_event("startup")
def on_startup():
    """
    Run create_schema() when the API server starts.
    """
    print("Application starting up...")
    create_schema()

# --- API Endpoints ---

@app.get("/")
def root():
    return {"message": "Welcome to Niche-Notify API"}

@app.get("/monitors")
def get_monitors_endpoint():
    """Fetch all monitors from the database"""
    try:
        monitors = get_all_monitors()
        return {"count": len(monitors), "data": monitors}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/monitors")
def add_monitor_endpoint(monitor: MonitorIn):
    """Add a new monitor to the database"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute(
            "INSERT INTO monitors (url, css_selector, user_email, last_content) VALUES (%s, %s, %s, %s) RETURNING id;",
            (monitor.url, monitor.css_selector, monitor.user_email, None)
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
def delete_monitor_endpoint(monitor_id: int):
    """Delete a monitor from the database by its ID"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("DELETE FROM monitors WHERE id = %s RETURNING id;", (monitor_id,))
        
        deleted_id = cur.fetchone()
        conn.commit()
        
        cur.close()
        conn.close()
        
        if deleted_id:
            return {"message": "Monitor deleted successfully", "id": deleted_id[0]}
        else:
            raise HTTPException(status_code=404, detail="Monitor not found")
            
    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- NEW WORKER ENDPOINT ---

@app.post("/worker/run")
def run_worker_endpoint(secret: str):
    """
    Triggers the worker process (process_once) if the secret is valid.
    """
    WORKER_SECRET = os.getenv("WORKER_SECRET")
    
    if not WORKER_SECRET:
        print("WORKER_SECRET is not set in environment. Cannot run worker.")
        raise HTTPException(status_code=500, detail="Worker is not configured")

    if secret != WORKER_SECRET:
        print("Invalid secret provided for worker endpoint.")
        raise HTTPException(status_code=403, detail="Invalid secret")

    try:
        print("API: Worker process triggered via POST /worker/run")
        process_once()
        return {"message": "Worker process completed successfully."}
    except Exception as e:
        print(f"API: Error during triggered worker run: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Worker error: {str(e)}")