"""
진행 중인 시즌(예: 2026-27)을 Understat에서 무료로 받아 DB에 반영합니다.

- 몇 번을 다시 실행해도 같은 경기·골이 중복 저장되지 않습니다 (해당 시즌의 Understat 골만 지우고 다시 넣음).
- API 키가 필요 없고, 새 경기가 끝날 때마다 다시 실행하면 최신으로 갱신됩니다.

사용법 (프로젝트 폴더에서):
    python data_collection/update_current_season.py          # 현재 시즌 자동 판별 (8월부터 새 시즌)
    python data_collection/update_current_season.py 2627     # 시즌을 직접 지정
"""
import sys
from datetime import date
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent))

from collect_understat import _clean, collect_season  # noqa: E402
from database.db_utils import get_connection, init_db  # noqa: E402


def current_season_code(today: date | None = None) -> str:
    """오늘 날짜로 현재 시즌 코드를 계산한다. 예: 2026-11 -> '2627', 2026-05 -> '2526'."""
    today = today or date.today()
    start = today.year if today.month >= 8 else today.year - 1
    return f"{start % 100:02d}{(start + 1) % 100:02d}"


def upsert_season(schedule, shots, season: str) -> tuple[int, int]:
    """경기와 골을 저장한다. 같은 시즌의 Understat 골은 먼저 지우고 새로 넣어 중복을 막는다."""
    conn = get_connection()
    cur = conn.cursor()

    match_ids = []
    for idx, row in schedule.iterrows():
        match_id = f"understat_{_clean(row.get('game_id', idx))}"
        match_ids.append(match_id)
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

    # 이 시즌의 Understat 골만 지우고 다시 넣는다 (API-Football 카드 등은 그대로 둔다)
    cur.execute(
        "DELETE FROM match_events WHERE source='understat' AND match_id IN "
        "(SELECT match_id FROM matches WHERE season=?)",
        (season,),
    )

    goals = shots[shots["result"].isin(["Goal", "OwnGoal"])]
    for _, row in goals.iterrows():
        cur.execute(
            """
            INSERT INTO match_events
            (match_id, minute, team, event_type, player, assist_player, xg, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'understat')
            """,
            (
                f"understat_{_clean(row.get('game_id'))}",
                _clean(row.get("minute", None)),
                _clean(row.get("team", None)),
                "own_goal" if row.get("result") == "OwnGoal" else "goal",
                _clean(row.get("player", "")),
                _clean(row.get("assist_player", None)),
                _clean(row.get("xg", None)),
            ),
        )

    conn.commit()
    conn.close()
    return len(match_ids), len(goals)


if __name__ == "__main__":
    season = sys.argv[1] if len(sys.argv) > 1 else current_season_code()
    print(f"현재 시즌 코드: {season}")
    init_db()
    schedule, shots = collect_season(season)
    n_matches, n_goals = upsert_season(schedule, shots, season)
    print(f"✅ {season} 시즌 반영 완료 (경기 {n_matches}개, 골 {n_goals}개)")
    print("챗봇은 다시 실행하지 않아도 다음 질문부터 새 데이터를 사용합니다.")
