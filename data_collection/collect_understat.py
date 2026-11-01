"""
Understat(soccerdata)에서 EPL 경기 스코어 + 골/어시스트/시간 이벤트를 수집해
football_history.db 에 저장합니다.

실행 전: pip install soccerdata (requirements.txt에 포함됨)
사용법: python data_collection/collect_understat.py
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import pandas as pd
import soccerdata as sd
from database.db_utils import get_connection, init_db

SEASONS = ["1415","1516","1617","1718","1819", "1920", "2021","2122","2223","2324","2425","2526"]  # 필요에 맞게 시즌 추가 (soccerdata 포맷: "2223" = 2022-2023)


def _clean(value):
    """
    pandas의 결측값(NaN, pd.NA, pd.NaT)을 SQLite가 이해할 수 있는
    파이썬 None으로 변환합니다. SQLite는 pd.NA 타입을 직접 바인딩하지 못해
    'type NAType is not supported' 에러를 냅니다.
    """
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        # 배열 등 스칼라가 아닌 값은 그대로 반환 (여기선 발생하지 않음)
        pass
    return value


def collect_season(season: str):
    print(f"\n▶ {season} 시즌 수집 중...")
    understat = sd.Understat(leagues="ENG-Premier League", seasons=season)

    # 1. 경기 일정/스코어
    schedule = understat.read_schedule().reset_index()
    # ⚠️ 실제 컬럼명은 soccerdata 버전에 따라 다를 수 있습니다.
    #    아래 print로 먼저 확인 후 컬럼명이 다르면 맞춰서 수정하세요.
    print("schedule 컬럼:", schedule.columns.tolist())

    # 2. 슛/골 이벤트 (득점자, 어시스트, 분, xG 포함)
    shots = understat.read_shot_events().reset_index()
    print("shots 컬럼:", shots.columns.tolist())

    return schedule, shots


def save_to_db(schedule, shots, season):
    conn = get_connection()
    cur = conn.cursor()

    # --- matches 테이블 저장 ---
    for _, row in schedule.iterrows():
        match_id = f"understat_{_clean(row.get('game_id', row.name))}"
        cur.execute(
            """
            INSERT OR REPLACE INTO matches
            (match_id, season, date, home_team, away_team, home_score, away_score, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'understat')
            """,
            (
                match_id,
                season,
                str(_clean(row.get("date", ""))),
                _clean(row.get("home_team", "")),
                _clean(row.get("away_team", "")),
                _clean(row.get("home_goals", None)),
                _clean(row.get("away_goals", None)),
            ),
        )

    # --- match_events 테이블 저장 (골만 우선) ---
    goals = shots[shots["result"].isin(["Goal", "OwnGoal"])]
    for _, row in goals.iterrows():
        # shots 데이터프레임의 실제 경기 식별 컬럼은 'match_id'가 아니라 'game_id' 입니다.
        match_id = f"understat_{_clean(row.get('game_id'))}"
        cur.execute(
            """
            INSERT INTO match_events
            (match_id, minute, team, event_type, player, assist_player, xg, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'understat')
            """,
            (
                match_id,
                _clean(row.get("minute", None)),
                # shots 데이터프레임에는 h_team/a_team/h_a 컬럼이 없고,
                # 이벤트를 일으킨 팀명이 담긴 'team' 컬럼 하나만 있습니다.
                _clean(row.get("team", None)),
                "own_goal" if row.get("result") == "OwnGoal" else "goal",
                _clean(row.get("player", "")),
                # 실제 컬럼명은 'player_assisted'가 아니라 'assist_player' 입니다.
                _clean(row.get("assist_player", None)),
                # 실제 컬럼명은 'xG'가 아니라 소문자 'xg' 입니다.
                _clean(row.get("xg", None)),
            ),
        )

    conn.commit()
    conn.close()
    print(f"✅ {season} 시즌 저장 완료 (경기 {len(schedule)}개, 골 이벤트 {len(goals)}개)")


if __name__ == "__main__":
    init_db()
    for season in SEASONS:
        try:
            schedule, shots = collect_season(season)
            save_to_db(schedule, shots, season)
        except Exception as e:
            print(f"❌ {season} 시즌 에러: {e}")