
import sqlite3

conn = sqlite3.connect("football_history.db", timeout=10)

# 전체 경기 수
total_matches = conn.execute(
    "SELECT COUNT(*) FROM matches"
).fetchone()[0]

# 전체 이벤트 수
total_events = conn.execute(
    "SELECT COUNT(*) FROM match_events"
).fetchone()[0]

# API-Football에서 가져온 경기 수
api_matches = conn.execute(
    "SELECT COUNT(*) FROM matches WHERE source = ?",
    ("api_football",)
).fetchone()[0]

print("저장된 경기:", total_matches)
print("저장된 이벤트:", total_events)
print("API-Football 경기:", api_matches)

conn.close()
