"""
2000-01 ~ 2013-14 시즌 프리미어리그 경기 결과(날짜·팀·스코어)를 football-data.co.uk 무료 CSV에서 받아
matches 테이블에 넣는다.

- 득점자·어시스트·득점 시간은 이 출처에 없다. 골·어시스트 기록(match_events)은 지금처럼 2014-15 시즌부터다.
- 2014-15 시즌부터는 Understat 데이터가 이미 있으므로 건드리지 않는다.
- 1990년대 시즌은 넣지 않는다. DB 시즌 코드('9900' 같은 4자리)가 '2627'보다 크게 정렬되어
  "가장 최근 시즌" 계산이 틀어지기 때문이다.
- 몇 번을 다시 실행해도 같은 경기가 중복 저장되지 않는다 (같은 match_id는 덮어쓴다).

사용법 (프로젝트 폴더에서):
    python data_collection/collect_history_results.py
"""
import csv
import io
import sys
from datetime import datetime
from pathlib import Path

import requests

sys.path.append(str(Path(__file__).parent.parent))
from database.db_utils import get_connection, init_db  # noqa: E402

URL = "https://www.football-data.co.uk/mmz4281/{code}/E0.csv"
FIRST_START_YEAR, LAST_START_YEAR = 2000, 2013  # 2000-01 ~ 2013-14

# football-data.co.uk 표기 -> 우리 DB(Understat) 표기. 목록에 없는 팀은 그대로 쓴다.
TEAM_NAME_FIX = {
    "Man City": "Manchester City",
    "Man United": "Manchester United",
    "Newcastle": "Newcastle United",
    "QPR": "Queens Park Rangers",
    "West Brom": "West Bromwich Albion",
    "Wolves": "Wolverhampton Wanderers",
    "Nott'm Forest": "Nottingham Forest",
}


def season_code(start_year: int) -> str:
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def parse_date(text: str) -> str:
    for fmt in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"날짜 형식을 알 수 없습니다: {text!r}")


def fetch_season(code: str) -> list[dict]:
    resp = requests.get(URL.format(code=code), timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    return parse_csv(resp.content.decode("latin-1"))


def parse_csv(text: str) -> list[dict]:
    """football-data.co.uk CSV에서 끝난 경기(스코어가 있는 행)만 골라 DB 팀 이름으로 바꿔 돌려준다."""
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        home, away = (r.get("HomeTeam") or "").strip(), (r.get("AwayTeam") or "").strip()
        if not home or not away or not (r.get("FTHG") or "").strip():
            continue
        rows.append({
            "date": parse_date(r["Date"]),
            "home": TEAM_NAME_FIX.get(home, home),
            "away": TEAM_NAME_FIX.get(away, away),
            "hg": int(float(r["FTHG"])),
            "ag": int(float(r["FTAG"])),
        })
    return rows


def main() -> None:
    init_db()
    conn = get_connection()
    known = {t for (t,) in conn.execute("SELECT home_team FROM matches UNION SELECT away_team FROM matches")}
    total, new_teams = 0, set()
    for start in range(FIRST_START_YEAR, LAST_START_YEAR + 1):
        code = season_code(start)
        rows = fetch_season(code)
        with conn:
            for r in rows:
                match_id = f"fd_{code}_{r['date']}_{r['home']}_{r['away']}".replace(" ", "_")
                conn.execute(
                    "INSERT OR REPLACE INTO matches "
                    "(match_id, season, date, home_team, away_team, home_score, away_score, source) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (match_id, code, r["date"], r["home"], r["away"], r["hg"], r["ag"], "football_data"),
                )
                for t in (r["home"], r["away"]):
                    if t not in known:
                        new_teams.add(t)
        teams = {r["home"] for r in rows}
        print(f"✅ 20{code[:2]}-{code[2:]} 시즌: 경기 {len(rows)}개, 팀 {len(teams)}개")
        total += len(rows)
    conn.close()
    print(f"\n총 {total}경기 반영")
    if new_teams:
        print("DB에 처음 들어온 팀(한글 이름·별명을 aliases.py에 추가할 것):", ", ".join(sorted(new_teams)))


if __name__ == "__main__":
    main()
