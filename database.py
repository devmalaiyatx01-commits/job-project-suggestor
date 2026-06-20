import sqlite3
import json
import hashlib
from datetime import datetime

DB_PATH = "jobs_cache.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS job_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cache_key TEXT UNIQUE,
            query TEXT,
            location TEXT,
            jobs_json TEXT,
            created_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS suggestion_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cache_key TEXT UNIQUE,
            query TEXT,
            suggestions TEXT,
            scores TEXT,
            created_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS search_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            query TEXT,
            location TEXT,
            job_count INTEGER,
            searched_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password_hash TEXT,
            security_question TEXT,
            security_answer_hash TEXT,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()

# ── Cache functions ───────────────────────────────────────────

def make_cache_key(query: str, location: str) -> str:
    raw = f"{query.lower().strip()}_{location.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()

def get_cached_jobs(query: str, location: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cache_key = make_cache_key(query, location)
    cursor.execute("SELECT jobs_json FROM job_cache WHERE cache_key = ?", (cache_key,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return None

def save_jobs_to_cache(query: str, location: str, jobs: list):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cache_key = make_cache_key(query, location)
    cursor.execute("""
        INSERT OR REPLACE INTO job_cache
        (cache_key, query, location, jobs_json, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (cache_key, query, location, json.dumps(jobs), datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_cached_suggestions(query: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cache_key = hashlib.md5(query.lower().strip().encode()).hexdigest()
    cursor.execute("SELECT suggestions, scores FROM suggestion_cache WHERE cache_key = ?", (cache_key,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0], json.loads(row[1])
    return None, None

def save_suggestions_to_cache(query: str, suggestions: str, scores: list):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cache_key = hashlib.md5(query.lower().strip().encode()).hexdigest()
    cursor.execute("""
        INSERT OR REPLACE INTO suggestion_cache
        (cache_key, query, suggestions, scores, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (cache_key, query, suggestions, json.dumps(scores), datetime.now().isoformat()))
    conn.commit()
    conn.close()

# ── User functions ────────────────────────────────────────────

def create_user(username: str, password_hash: str, security_question: str, security_answer_hash: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO users (username, password_hash, security_question, security_answer_hash, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (username, password_hash, security_question, security_answer_hash, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def get_user(username: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT username, password_hash FROM users WHERE username = ?",
        (username,)
    )
    row = cursor.fetchone()
    conn.close()
    return row

def get_user_security(username: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT security_question, security_answer_hash FROM users WHERE username = ?",
        (username,)
    )
    row = cursor.fetchone()
    conn.close()
    return row

def update_password(username: str, new_password_hash: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET password_hash = ? WHERE username = ?",
        (new_password_hash, username)
    )
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0

# ── Search history functions ──────────────────────────────────

def log_search(username: str, query: str, location: str, job_count: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO search_history (username, query, location, job_count, searched_at)
        VALUES (?, ?, ?, ?, ?)
    """, (username, query, location, job_count, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_user_search_history(username: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT query, location, job_count, searched_at
        FROM search_history
        WHERE username = ?
        ORDER BY searched_at DESC
        LIMIT 10
    """, (username,))
    rows = cursor.fetchall()
    conn.close()
    return rows

# ── Stats functions ───────────────────────────────────────────

def get_total_users() -> int:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_total_searches() -> int:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM search_history")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_top_searches(limit: int = 5) -> list:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT query, COUNT(*) as count
        FROM search_history
        GROUP BY LOWER(query)
        ORDER BY count DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return rows