"""처리 기록: 질문마다 app_log.db(query_logs)에 한 줄씩 남긴다. 실패해도 앱은 멈추지 않는다."""
import sqlite3
from datetime import datetime
from pathlib import Path

LOG_DB = Path(__file__).resolve().parent / "app_log.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS query_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    session_id TEXT,
    question TEXT,
    sql_text TEXT,
    answer_source TEXT,
    error_code TEXT,
    row_count INTEGER,
    latency_ms INTEGER,
    answer_preview TEXT
)
"""


def _connect():
    conn = sqlite3.connect(LOG_DB)
    conn.execute(_SCHEMA)
    return conn


def log_query(session_id, question, result, latency_ms, error_code=None):
    try:
        conn = _connect()
        with conn:
            conn.execute(
                "INSERT INTO query_logs (created_at, session_id, question, sql_text, answer_source,"
                " error_code, row_count, latency_ms, answer_preview) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    session_id,
                    (question or "")[:500],
                    (result.get("sql") or "")[:2000],
                    result.get("answer_source"),
                    error_code or result.get("error_code"),
                    len(result.get("rows") or []),
                    int(latency_ms),
                    (result.get("answer") or result.get("error") or "")[:300],
                ),
            )
        conn.close()
    except Exception:
        pass


def read_logs(limit=200):
    conn = _connect()
    try:
        cur = conn.execute("SELECT * FROM query_logs ORDER BY id DESC LIMIT ?", (limit,))
        cols = [d[0] for d in cur.description]
        return cols, cur.fetchall()
    finally:
        conn.close()


def error_counts():
    conn = _connect()
    try:
        return conn.execute(
            "SELECT COALESCE(error_code,'정상') AS code, COUNT(*) FROM query_logs GROUP BY code ORDER BY 2 DESC"
        ).fetchall()
    finally:
        conn.close()
