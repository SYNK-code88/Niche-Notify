# api.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from db import get_all_monitors, get_db_connection
from dotenv import load_dotenv
import psycopg2
import os

# Load environment variables (like DATABASE_URL) from .env file
load_dotenv()

app = FastAPI(title="Niche-Notify API", version="1.0")

# --- This is the CORS middleware ---
origins = [
    "*",  # Allows all origins
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- This is the Pydantic Model ---
class MonitorIn(BaseModel):
    url: str
    css_selector: str
    user_email: str

@app.get("/")
def root():
    return {"message": "Welcome to Niche-Notify API (Phase 2)"}

@app.get("/monitors")
def get_monitors():
    """Fetch all monitors from the database"""
    try:
        monitors = get_all_monitors()
        return {"count": len(monitors), "data": monitors}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/monitors")
def add_monitor(monitor: MonitorIn):
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
        # --- THIS WAS THE FIRST BROKEN LINE ---
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/monitors/{monitor_id}")
def delete_monitor(monitor_id: int):
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
        # --- THIS WAS THE SECOND BROKEN LINE (from your log) ---
        raise HTTPException(status_code=500, detail=str(e))