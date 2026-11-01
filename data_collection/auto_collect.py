
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
EPL 경기 자동 수집 프로그램

기능:
1. API-Football에서 EPL 경기 목록 조회
2. 종료된 경기만 수집
3. 경기 및 골/카드 이벤트를 SQLite DB에 저장
4. 중복 이벤트 방지
5. 처리한 경기 ID를 JSON 파일에 기록
6. 일정 시간마다 새로 종료된 경기 확인

실행:
    python data_collection/auto_collect.py

환경 변수:
    .env 파일의 API_FOOTBALL_KEY 사용
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

# 프로젝트 루트 경로
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from database.db_utils import get_connection, init_db
from database.match_dedupe import find_understat_match


# --------------------------------------------------
# 설정
# --------------------------------------------------

load_dotenv(PROJECT_ROOT / ".env")

API_KEY = os.getenv("API_FOOTBALL_KEY")
BASE_URL = "https://v3.football.api-sports.io"

LEAGUE_ID = 39  # EPL

# 현재 시즌 자동 선택
# EPL은 일반적으로 8월부터 다음 해 5~6월까지 진행됨

# 무료 API 요금제에서 접근 가능한 시즌으로 테스트
SEASON = 2024


# 한 번 실행할 때 이벤트 조회에 사용할 최대 요청 수
MAX_EVENT_REQUESTS_PER_RUN = 80

# 자동 확인 주기: 30분
POLL_INTERVAL_SECONDS = 30 * 60

# API 호출 사이 대기 시간
REQUEST_DELAY_SECONDS = 7

# 처리한 경기 ID를 기록할 파일
STATE_FILE = PROJECT_ROOT / "data_collection" / "auto_collect_state.json"

# 경기 종료 상태
FINISHED_STATUSES = {"FT", "AET", "PEN"}

HEADERS = {
    "x-apisports-key": API_KEY or ""
}


# --------------------------------------------------
# API 요청
# --------------------------------------------------


def api_get(endpoint, params=None, retries=3):
    """API 요청 및 오류 처리"""

    url = f"{BASE_URL}/{endpoint}"

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(
                url,
                headers=HEADERS,
                params=params,
                timeout=20
            )

            # HTTP 요청 제한: 즉시 중단
            if response.status_code == 429:
                raise RuntimeError(
                    "API_RATE_LIMIT: API 요청 제한 초과(429). "
                    "현재 수집 주기를 중단합니다."
                )

            response.raise_for_status()
            data = response.json()

            errors = data.get("errors")

            if errors:
                # API 요청 제한
                if "rateLimit" in errors:
                    raise RuntimeError(
                        f"API_RATE_LIMIT: 요청 제한 초과: {errors}"
                    )

                # 요금제 또는 시즌 접근 제한
                if "plan" in errors:
                    raise RuntimeError(
                        f"API_PLAN_ERROR: 요금제 또는 시즌 접근 제한: {errors}"
                    )

                # 그 밖의 API 오류
                raise RuntimeError(
                    f"API_ERROR: API 요청 실패: {errors}"
                )

            return data.get("response", [])

        except RuntimeError:
            # API 제한이나 설정 오류는 반복 요청하지 않는다.
            raise

        except (requests.RequestException, ValueError) as exc:
            print(
                f"[경고] API 요청 실패 "
                f"({attempt}/{retries}): {exc}"
            )

            if attempt < retries:
                wait_seconds = 5 * attempt

                print(
                    f"[대기] {wait_seconds}초 후 "
                    "재시도합니다."
                )

                time.sleep(wait_seconds)
            else:
                raise

    return []



def get_fixtures():
    """현재 EPL 시즌의 경기 목록을 조회한다."""

    return api_get(
        "fixtures",
        {
            "league": LEAGUE_ID,
            "season": SEASON
        }
    )


def get_events(fixture_id):
    """특정 경기의 골 및 카드 이벤트를 조회한다."""

    return api_get(
        "fixtures/events",
        {
            "fixture": fixture_id
        }
    )


# --------------------------------------------------
# 수집 상태 관리
# --------------------------------------------------

def load_state():
    """이전에 처리한 경기 ID를 읽는다."""

    if not STATE_FILE.exists():
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            state = json.load(file)

        if not isinstance(state, dict):
            raise ValueError("상태 파일 형식이 올바르지 않습니다.")

        return state

    except (OSError, json.JSONDecodeError, ValueError) as exc:
        # 손상된 상태 파일을 빈 상태로 처리하면
        # 기존 경기를 다시 수집할 수 있으므로 실행을 중단한다.
        raise RuntimeError(
            f"상태 파일을 읽을 수 없습니다: {STATE_FILE}\n"
            f"파일을 확인한 후 다시 실행하세요. 원인: {exc}"
        ) from exc


def save_state(state):
    """수집 상태를 JSON 파일에 안전하게 저장한다."""

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    temp_file = STATE_FILE.with_suffix(".tmp")

    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)

    os.replace(temp_file, STATE_FILE)


def state_key(fixture_id):
    """시즌별 경기 ID를 구분한다."""

    return f"{SEASON}_{fixture_id}"


# --------------------------------------------------
# 데이터베이스 저장
# --------------------------------------------------

def save_finished_fixture(fixture, events):
    """
    종료된 경기 정보와 이벤트를 하나의 DB 트랜잭션으로 저장한다.

    같은 경기의 api_football 이벤트가 기존에 있으면 삭제한 후
    새 이벤트 목록으로 교체하여 중복 저장을 방지한다.
    """

    fixture_info = fixture["fixture"]
    teams = fixture["teams"]
    goals = fixture["goals"]

    fixture_id = fixture_info["id"]
    match_id = f"apifootball_{fixture_id}"

    season_text = f"{SEASON}-{SEASON + 1}"
    match_date = fixture_info["date"][:10]

    conn = get_connection()

    try:
        cur = conn.cursor()

        # 같은 경기가 이미 Understat으로 저장되어 있는지 확인한다.
        # 있으면 경기 행을 새로 만들지 않고, Understat 경기에 카드 등만 붙인다.
        # (골·어시스트가 두 번 집계되는 것을 막기 위함)
        understat_id = find_understat_match(
            conn,
            match_date,
            teams["home"]["name"],
            teams["away"]["name"],
            goals["home"],
            goals["away"],
        )

        if understat_id:
            # 예전에 만들어진 중복 API-Football 경기 행이 있으면 정리
            cur.execute("DELETE FROM match_events WHERE match_id = ?", (match_id,))
            cur.execute("DELETE FROM matches WHERE match_id = ?", (match_id,))
            match_id = understat_id

        # 경기 기본 정보 저장 (Understat에 없는 경기만)
        if not understat_id:
            cur.execute(
                """
                INSERT OR REPLACE INTO matches
                (
                    match_id,
                    season,
                    date,
                    home_team,
                    away_team,
                    home_score,
                    away_score,
                    source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'api_football')
                """,
                (
                    match_id,
                    season_text,
                    match_date,
                    teams["home"]["name"],
                    teams["away"]["name"],
                    goals["home"],
                    goals["away"],
                )
            )

        # 기존 API-Football 이벤트만 교체한다.
        # Understat에서 수집한 이벤트는 삭제하지 않는다.
        cur.execute(
            """
            DELETE FROM match_events
            WHERE match_id = ?
              AND source = 'api_football'
            """,
            (match_id,)
        )

        saved_count = 0

        for event in events:
            event_category = event.get("type")
            detail = event.get("detail") or ""

            # 골과 카드만 저장
            if event_category not in ("Goal", "Card"):
                continue

            # 이벤트 종류 정리
            if event_category == "Goal":
                if detail.strip().lower() == "own goal":
                    event_type = "own_goal"
                else:
                    event_type = "goal"
                    # Understat 경기에는 득점·어시스트·xG가 이미 있으므로
                    # 일반 골은 다시 저장하지 않는다 (중복 집계 방지).
                    if understat_id:
                        continue
            else:
                event_type = detail.lower().replace(" ", "_")

            event_time = event.get("time") or {}
            team_info = event.get("team") or {}
            player_info = event.get("player") or {}
            assist_info = event.get("assist") or {}

            minute = event_time.get("elapsed")
            team_name = team_info.get("name")
            player_name = player_info.get("name")
            assist_name = assist_info.get("name")

            cur.execute(
                """
                INSERT INTO match_events
                (
                    match_id,
                    minute,
                    team,
                    event_type,
                    player,
                    assist_player,
                    xg,
                    source
                )
                VALUES (?, ?, ?, ?, ?, ?, NULL, 'api_football')
                """,
                (
                    match_id,
                    minute,
                    team_name,
                    event_type,
                    player_name,
                    assist_name,
                )
            )

            saved_count += 1

        conn.commit()

        return match_id, saved_count

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


# --------------------------------------------------
# 자동 수집
# --------------------------------------------------

def collect_once():
    """현재 시즌에서 아직 처리하지 않은 종료 경기를 수집한다."""

    print("\n" + "=" * 55)
    print(f"[시작] EPL {SEASON}-{SEASON + 1} 자동 수집")
    print(f"[시간] {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 55)

    state = load_state()

    fixtures = get_fixtures()

    print(f"[정보] 전체 경기 조회: {len(fixtures)}개")

    finished_count = 0
    processed_count = 0
    event_request_count = 0

    for fixture in fixtures:
        fixture_info = fixture.get("fixture") or {}
        fixture_id = fixture_info.get("id")

        if fixture_id is None:
            continue

        status_info = fixture_info.get("status") or {}
        status = status_info.get("short")

        # 종료된 경기만 처리
        if status not in FINISHED_STATUSES:
            continue

        finished_count += 1
        key = state_key(fixture_id)

        # 이미 정상적으로 처리한 경기는 건너뛴다.
        if state.get(key) == "done":
            continue

        # 이벤트 요청 한도 초과 방지
        if event_request_count >= MAX_EVENT_REQUESTS_PER_RUN:
            print(
                "[알림] 이번 실행의 이벤트 요청 한도에 도달했습니다. "
                "나머지 경기는 다음 실행에서 처리합니다."
            )
            break

        home = (fixture.get("teams") or {}).get("home") or {}
        away = (fixture.get("teams") or {}).get("away") or {}

        home_name = home.get("name", "홈팀")
        away_name = away.get("name", "원정팀")

        try:
            print(f"\n[수집] {home_name} vs {away_name}")

            events = get_events(fixture_id)
            event_request_count += 1

            match_id, saved_count = save_finished_fixture(
                fixture,
                events
            )

            # DB 저장 성공 후에만 완료 상태를 기록한다.
            state[key] = "done"
            save_state(state)

            processed_count += 1

            print(f"[완료] 경기 ID: {match_id}")
            print(f"[완료] 저장된 골/카드 이벤트: {saved_count}개")

            time.sleep(REQUEST_DELAY_SECONDS)

        
        except Exception as exc:
            error_message = str(exc)

            print(f"[오류] {home_name} vs {away_name}: {exc}")

            # API 요청 제한 발생 시 현재 수집 주기 중단
            if (
                "API_RATE_LIMIT:" in error_message
                or "429 Client Error" in error_message
            ):
                print(
                    "[중단] API 요청 제한에 도달했습니다. "
                    "현재 수집 주기의 나머지 경기는 처리하지 않습니다."
                )
                break

            # 시즌 접근 권한 오류는 반복 요청하지 않고 안내
            if "API_PLAN_ERROR:" in error_message:
                print(
                    "[중단] 현재 요금제에서 해당 데이터에 "
                    "접근할 수 없는 것으로 보입니다."
                )
                break

            # 기타 오류는 다음 경기로 진행하고 다음 주기에 재시도
            print(
                "[안내] 해당 경기는 완료 처리하지 않았습니다. "
                "다음 실행에서 다시 시도합니다."
            )


    print("\n" + "-" * 55)
    print(f"[결과] 종료된 경기: {finished_count}개")
    print(f"[결과] 이번 실행에서 처리한 경기: {processed_count}개")
    print(f"[결과] 이벤트 API 요청: {event_request_count}회")
    print("-" * 55)


def main():
    if not API_KEY:
        print(
            "[오류] .env 파일에 API_FOOTBALL_KEY가 설정되어 있는지 "
            "확인하세요."
        )
        sys.exit(1)

    init_db()

    print("[시작] EPL 자동 데이터 수집 프로그램")
    print(f"[설정] 리그 ID: {LEAGUE_ID}")
    print(f"[설정] 시즌 시작 연도: {SEASON}")
    print(f"[설정] 반복 간격: {POLL_INTERVAL_SECONDS // 60}분")
    print("[안내] 종료하려면 Ctrl+C를 누르세요.")

    while True:
        try:
            collect_once()

        except KeyboardInterrupt:
            print("\n[종료] 사용자가 프로그램을 종료했습니다.")
            break

        except Exception as exc:
            print(f"\n[오류] 이번 수집 주기를 완료하지 못했습니다: {exc}")
            print("[안내] 다음 주기에 다시 시도합니다.")

        try:
            print(
                f"\n[대기] {POLL_INTERVAL_SECONDS // 60}분 후 "
                "다음 경기를 확인합니다."
            )
            time.sleep(POLL_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            print("\n[종료] 사용자가 프로그램을 종료했습니다.")
            break


if __name__ == "__main__":
    main()
