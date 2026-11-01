"""
API-Football(공식 사이트 직접 가입, api-sports.io)에서 EPL 경기의 상세 이벤트
(득점자, 어시스트, 시간, 카드)를 수집해 match_events 테이블을 보강합니다.

⚠️ 무료 플랜은 하루 100회 요청 제한이 있습니다.
   - fixtures 조회: 시즌당 1회
   - events 조회: 경기당 1회 (한 시즌 380경기 = 380회 → 여러 날에 나눠 실행해야 함)
   아래 MAX_REQUESTS_PER_RUN으로 하루 호출량을 제한합니다.

사용법: python data_collection/collect_api_football.py
"""
import os
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import requests
from dotenv import load_dotenv
from database.db_utils import get_connection, init_db

load_dotenv()

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")
BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {
    "x-apisports-key": API_FOOTBALL_KEY,
}

EPL_LEAGUE_ID = 39      # API-Football 내부 EPL 리그 ID
SEASON = 2024           # 2024-2025 시즌
MAX_REQUESTS_PER_RUN = 90  # 무료 한도(100) 대비 여유를 둔 안전 마진


def get_fixtures(league_id: int, season: int):
    """해당 시즌의 전체 경기 목록을 가져옵니다 (요청 1회)."""
    resp = requests.get(
        f"{BASE_URL}/fixtures",
        headers=HEADERS,
        params={"league": league_id, "season": season},
    )
    resp.raise_for_status()
    return resp.json()["response"]


def get_events(fixture_id: int):
    """경기 하나의 상세 이벤트(골/카드 등)를 가져옵니다 (요청 1회)."""
    resp = requests.get(
        f"{BASE_URL}/fixtures/events",
        headers=HEADERS,
        params={"fixture": fixture_id},
    )
    resp.raise_for_status()
    return resp.json()["response"]


def already_collected(fixture_id: int) -> bool:
    """이미 DB에 저장된 경기인지 확인 (중복 요청 방지)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM match_events WHERE match_id = ? AND source = 'api_football' LIMIT 1",
        (f"apifootball_{fixture_id}",),
    )
    result = cur.fetchone()
    conn.close()
    return result is not None


def save_match(fixture: dict):
    conn = get_connection()
    cur = conn.cursor()
    match_id = f"apifootball_{fixture['fixture']['id']}"
    cur.execute(
        """
        INSERT OR REPLACE INTO matches
        (match_id, season, date, home_team, away_team, home_score, away_score, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'api_football')
        """,
        (
            match_id,
            f"{SEASON}-{SEASON+1}",
            fixture["fixture"]["date"][:10],
            fixture["teams"]["home"]["name"],
            fixture["teams"]["away"]["name"],
            fixture["goals"]["home"],
            fixture["goals"]["away"],
        ),
    )
    conn.commit()
    conn.close()
    return match_id


def save_events(match_id: str, events: list):
    conn = get_connection()
    cur = conn.cursor()
    for e in events:
        if e["type"] not in ("Goal", "Card"):
            continue
        event_type = "goal" if e["type"] == "Goal" else e["detail"].lower().replace(" ", "_")
        cur.execute(
            """
            INSERT INTO match_events
            (match_id, minute, team, event_type, player, assist_player, xg, source)
            VALUES (?, ?, ?, ?, ?, ?, NULL, 'api_football')
            """,
            (
                match_id,
                e["time"]["elapsed"],
                e["team"]["name"],
                event_type,
                e["player"]["name"],
                e.get("assist", {}).get("name"),
            ),
        )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    if not API_FOOTBALL_KEY:
        print("❌ .env 파일에 API_FOOTBALL_KEY를 설정해주세요.")
        sys.exit(1)

    init_db()
    fixtures = get_fixtures(EPL_LEAGUE_ID, SEASON)
    print(f"총 {len(fixtures)}경기 발견")

    request_count = 0
    for fixture in fixtures:
        fixture_id = fixture["fixture"]["id"]
        if already_collected(fixture_id):
            continue
        if request_count >= MAX_REQUESTS_PER_RUN:
            print(f"⏸ 오늘 요청 한도({MAX_REQUESTS_PER_RUN})에 도달해 중단합니다. 내일 다시 실행하세요.")
            break

        match_id = save_match(fixture)
        events = get_events(fixture_id)
        save_events(match_id, events)
        request_count += 1
        print(f"✅ {fixture['teams']['home']['name']} vs {fixture['teams']['away']['name']} 저장 완료")
        time.sleep(1)  # 초당 요청 제한 대비 여유

    print(f"\n🎉 이번 실행에서 {request_count}경기 처리 완료")
