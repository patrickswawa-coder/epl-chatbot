"""
이미 DB에 들어간 'Understat + API-Football 중복 경기'를 한 번 정리하는 스크립트.

문제: 같은 경기가 두 번 저장되어 골/어시스트/경기 수가 부풀려졌습니다.
      (예: 손흥민 127골 + API-Football 4골 = 131골)
정리: Understat 경기를 기준으로 삼고,
      - API-Football의 'goal' 이벤트는 삭제 (Understat에 이미 있음)
      - 카드 등 나머지 이벤트는 Understat 경기로 옮김
      - 중복된 API-Football 경기 행은 삭제

사용법 (프로젝트 루트에서):
    python data_collection/dedupe_sources.py            # 미리보기만 (DB 변경 없음)
    python data_collection/dedupe_sources.py --apply    # 백업 후 실제 정리
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from database.db_utils import DB_PATH
from database.match_dedupe import find_understat_match


def main():
    apply = "--apply" in sys.argv

    conn = sqlite3.connect(DB_PATH)
    api_matches = conn.execute(
        "SELECT match_id, date, home_team, away_team, home_score, away_score "
        "FROM matches WHERE source = 'api_football'"
    ).fetchall()

    plan, unmatched = [], []
    for mid, date, home, away, hs, as_ in api_matches:
        um = find_understat_match(conn, date, home, away, hs, as_)
        (plan if um else unmatched).append((mid, um, home, away, date))

    goal_rows = 0
    for mid, _, _, _, _ in plan:
        goal_rows += conn.execute(
            "SELECT COUNT(*) FROM match_events "
            "WHERE match_id = ? AND source = 'api_football' AND event_type = 'goal'",
            (mid,),
        ).fetchone()[0]

    print(f"API-Football 경기: {len(api_matches)}개")
    print(f"  Understat과 중복: {len(plan)}개  -> 정리 대상")
    print(f"  Understat에 없음: {len(unmatched)}개  -> 그대로 유지")
    print(f"삭제될 중복 골 이벤트: {goal_rows}개")
    for mid, um, home, away, date in unmatched[:10]:
        print(f"  (유지) {date} {home} vs {away}")

    if not apply:
        print("\n미리보기입니다. 실제로 정리하려면 --apply 를 붙여 다시 실행하세요.")
        conn.close()
        return

    backup = DB_PATH.with_name(
        f"football_history_backup_{datetime.now():%Y%m%d_%H%M%S}.db"
    )
    dst = sqlite3.connect(backup)
    conn.backup(dst)
    dst.close()
    print(f"\n백업 완료: {backup}")

    try:
        for mid, um, _, _, _ in plan:
            conn.execute(
                "DELETE FROM match_events "
                "WHERE match_id = ? AND source = 'api_football' AND event_type = 'goal'",
                (mid,),
            )
            conn.execute(
                "UPDATE match_events SET match_id = ? WHERE match_id = ?", (um, mid)
            )
            conn.execute("DELETE FROM matches WHERE match_id = ?", (mid,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("정리 완료. 챗봇을 다시 실행해서 손흥민 골 수를 확인해 보세요.")


if __name__ == "__main__":
    main()
