"""
진행 중인 시즌(예: 2026-27)을 Understat에서 무료로 받아 DB에 반영합니다.

- 몇 번을 다시 실행해도 같은 경기·골이 중복 저장되지 않습니다 (해당 시즌의 Understat 골만 지우고 다시 넣음).
- API 키가 필요 없고, 새 경기가 끝날 때마다 다시 실행하면 최신으로 갱신됩니다.
- Understat가 점검 중이라 데이터를 못 받으면, 끝난 경기 스코어만 football-data.co.uk에서 채웁니다
  (득점자·어시스트는 Understat가 돌아온 뒤 다음 실행 때 반영).
- soccerdata는 받은 응답을 PC에 저장해 두고 다시 쓰는데, 점검 안내 페이지(HTML)가 저장되면
  Understat가 돌아와도 계속 실패한다. 그래서 실행할 때마다 JSON이 아닌 저장본을 지운다.

사용법 (프로젝트 폴더에서):
    python data_collection/update_current_season.py          # 현재 시즌 자동 판별 (8월부터 새 시즌)
    python data_collection/update_current_season.py 2627     # 시즌을 직접 지정
"""
import os
import sys
from datetime import date
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent))

from database.db_utils import get_connection, init_db  # noqa: E402

# soccerdata가 Understat 응답을 저장하는 폴더 (soccerdata/_config.py와 같은 규칙)
UNDERSTAT_CACHE = Path(os.environ.get("SOCCERDATA_DIR", Path.home() / "soccerdata")) / "data" / "Understat"


def clean_bad_cache(folder: Path = UNDERSTAT_CACHE) -> list[str]:
    """JSON이 아닌 저장본(점검 안내 HTML, 빈 파일)을 지우고 지운 파일 이름을 돌려준다."""
    removed = []
    if not folder.is_dir():
        return removed
    for f in folder.glob("*.json"):
        try:
            with f.open("rb") as fh:
                head = fh.read(64).lstrip(b"\xef\xbb\xbf \t\r\n")
            if not head or head[:1] not in (b"{", b"["):
                f.unlink()
                removed.append(f.name)
        except OSError:
            continue
    return removed


def understat_failure_reason(exc: Exception) -> str:
    """Understat 실패를 사람이 읽을 수 있는 한 줄로 바꾼다."""
    if type(exc).__name__ == "JSONDecodeError":
        return "Understat가 데이터 대신 안내 페이지(점검 중 'We will come back soon' 등)를 보냈습니다"
    return f"{type(exc).__name__}: {str(exc)[:200]}"


def current_season_code(today: date | None = None) -> str:
    """오늘 날짜로 현재 시즌 코드를 계산한다. 예: 2026-11 -> '2627', 2026-05 -> '2526'."""
    today = today or date.today()
    start = today.year if today.month >= 8 else today.year - 1
    return f"{start % 100:02d}{(start + 1) % 100:02d}"


def upsert_season(schedule, shots, season: str) -> tuple[int, int]:
    """경기와 골을 저장한다. 같은 시즌의 Understat 골은 먼저 지우고 새로 넣어 중복을 막는다."""
    from collect_understat import _clean

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


def main(season: str) -> int:
    print(f"현재 시즌 코드: {season}")
    init_db()
    removed = clean_bad_cache()
    if removed:
        print(f"잘못 저장된 Understat 응답 {len(removed)}개를 지웠습니다: {', '.join(removed[:5])}")

    try:
        from collect_understat import collect_season

        schedule, shots = collect_season(season)
    except Exception as exc:  # 점검·차단·네트워크 오류
        clean_bad_cache()  # 방금 저장된 안내 페이지가 다음 실행을 막지 않게 지운다
        print(f"⚠️ Understat 수집 실패: {understat_failure_reason(exc)}")
        print("→ 대신 football-data.co.uk에서 끝난 경기 스코어만 채웁니다. 득점자·어시스트는 Understat가 돌아오면 반영됩니다.")
        try:
            from fill_scores_football_data import main as fill_main

            fill_main(season)
        except Exception as exc2:
            print(f"❌ football-data.co.uk 보완도 실패: {type(exc2).__name__}: {str(exc2)[:200]}")
            return 1
        return 0

    n_matches, n_goals = upsert_season(schedule, shots, season)
    print(f"✅ {season} 시즌 반영 완료 (경기 {n_matches}개, 골 {n_goals}개)")

    # 새로 등장한 선수·팀 이름을 임베딩 캐시에 추가한다 (이미 있는 이름은 건너뛰어 비용이 거의 없다)
    try:
        from database.build_entity_embeddings import main as build_embeddings

        build_embeddings()
    except (Exception, SystemExit) as exc:
        print(f"⚠️ 이름 임베딩 갱신을 건너뜁니다: {exc}")
    print("챗봇은 다시 실행하지 않아도 다음 질문부터 새 데이터를 사용합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else current_season_code()))
