"""
DB 연결 및 초기화를 위한 공용 유틸 함수 모음.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "football_history.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# DB에 담긴 기간. 경기 결과(matches)와 골·어시스트·카드 기록(match_events)의 시작 시즌이 다르다.
MATCH_SEASON_FROM = "2000-01"      # football-data.co.uk 경기 결과 + Understat
EVENT_SEASON_FROM = "2014-15"      # Understat 골·어시스트 기록
EVENT_SEASON_CODE_FROM = "1415"    # 위 시즌의 DB 시즌 코드


def get_connection():
    """DB 커넥션을 반환합니다."""
    return sqlite3.connect(DB_PATH)


def init_db():
    """schema.sql을 실행해 테이블이 없으면 생성합니다."""
    conn = get_connection()
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()
    print(f"✅ DB 초기화 완료: {DB_PATH}")


if __name__ == "__main__":
    init_db()
