"""
Understat가 멈췄을 때(점검 등) 이번 시즌 끝난 경기의 스코어만 football-data.co.uk 무료 CSV로 채운다.

- DB에 이미 있는 이번 시즌 일정(Understat 경기 행) 중 스코어가 비어 있는 경기만 채운다. 새 행은 만들지 않는다.
  (한 시즌에 같은 홈·원정 조합은 한 번뿐이라 팀 이름 두 개로 같은 경기를 찾는다)
- 득점자·어시스트·득점 시간은 이 출처에 없다. Understat가 돌아오면 update_current_season.py가
  같은 경기를 Understat 기록으로 덮어쓰고 골 기록도 넣는다.
- update_current_season.py가 Understat 실패 시 자동으로 부른다. 직접 실행해도 된다.

사용법 (프로젝트 폴더에서):
    python data_collection/fill_scores_football_data.py          # 이번 시즌
    python data_collection/fill_scores_football_data.py 2627     # 시즌 코드 지정
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
sys.path.append(str(Path(__file__).parent.parent))

from collect_history_results import fetch_season  # noqa: E402
from database.db_utils import get_connection, init_db  # noqa: E402


def fill_scores(conn, season: str, rows: list[dict]) -> tuple[int, list[str]]:
    """비어 있는 스코어를 채운다. (채운 경기 수, DB에서 찾지 못한 경기 목록)을 돌려준다."""
    filled, unmatched = 0, []
    with conn:
        for r in rows:
            cur = conn.execute(
                "UPDATE matches SET home_score = ?, away_score = ? "
                "WHERE season = ? AND home_team = ? AND away_team = ? AND home_score IS NULL",
                (r["hg"], r["ag"], season, r["home"], r["away"]),
            )
            if cur.rowcount:
                filled += cur.rowcount
                continue
            exists = conn.execute(
                "SELECT 1 FROM matches WHERE season = ? AND home_team = ? AND away_team = ?",
                (season, r["home"], r["away"]),
            ).fetchone()
            if not exists:  # 팀 이름 표기가 달라 못 찾은 경기 (TEAM_NAME_FIX에 추가할 것)
                unmatched.append(f"{r['date']} {r['home']} vs {r['away']}")
    return filled, unmatched


def main(season: str | None = None) -> int:
    if season is None:
        from update_current_season import current_season_code

        season = current_season_code()
    init_db()
    rows = fetch_season(season)
    conn = get_connection()
    try:
        filled, unmatched = fill_scores(conn, season, rows)
    finally:
        conn.close()
    print(f"football-data.co.uk {season} 시즌 끝난 경기 {len(rows)}개 확인 → 비어 있던 스코어 {filled}경기 채움")
    if unmatched:
        print("DB 일정에서 찾지 못한 경기(팀 이름 표기 확인 필요):", "; ".join(unmatched[:10]))
    return filled


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
