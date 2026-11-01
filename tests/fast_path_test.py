"""
빠른 경로(fast_path.py) 테스트. OpenAI 키 없이 실행된다.

    python tests/fast_path_test.py

1) 정답 대조: 모든 선수·팀 조합에서 빠른 경로의 숫자를 "다른 방식의 SQL"로 다시 계산해 비교한다.
2) 가로채기 확인: 기존 정확도 테스트 문항(CASES·UNSEEN) 중 빠른 경로가 처리하는 것은 같은 채점 기준으로 채점한다.
3) 오인식 방지: 시즌·연도·홈/원정·상대팀 같은 추가 조건이 있는 질문은 반드시 None(기존 GPT 경로)이어야 한다.
"""
import itertools
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.aliases import PLAYERS, TEAMS  # noqa: E402
from fast_path import try_fast_path  # noqa: E402

DB = ROOT / "football_history.db"
fails = []


def check(ok, msg):
    if not ok:
        fails.append(msg)
        print("  FAIL:", msg)


conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)

# ---------------------------------------------------------------- 1) 정답 대조
print("[1] 선수 골·어시스트·프로필 정답 대조")
goal_map = dict(conn.execute("SELECT player, COUNT(*) FROM match_events WHERE event_type='goal' GROUP BY player"))
assist_map = dict(
    conn.execute(
        "SELECT assist_player, COUNT(*) FROM match_events WHERE event_type='goal' AND assist_player IS NOT NULL "
        "GROUP BY assist_player"
    )
)
n_checked = 0
for ko, _, db in PLAYERS:
    g, a = goal_map.get(db, 0), assist_map.get(db, 0)
    if g == 0 and a == 0:
        check(try_fast_path(f"{ko} 알려줘") is None, f"기록 없는 선수는 None이어야 함: {ko}")
        continue
    r = try_fast_path(f"{ko} 골 몇 개야?")
    check(r and r["rows"] == [(g,)], f"{ko} 골: {r and r['rows']} != {g}")
    r = try_fast_path(f"{ko} 어시스트 몇 개야?")
    check(r and r["rows"] == [(a,)], f"{ko} 어시스트: {r and r['rows']} != {a}")
    r = try_fast_path(f"{ko} 알려줘")
    ok = r and r["rows"] == [(g, a, r["rows"][0][2])] and r["card"]["by_season"]
    check(ok, f"{ko} 프로필 불일치")
    if r:
        season_sum = sum(x for _, x in r["card"]["by_season"])
        check(season_sum == g, f"{ko} 시즌별 합계 {season_sum} != 통산 {g}")
    n_checked += 1
print(f"  {n_checked}명 확인")

print("[2] 선수 비교 정답 대조")
pool = [(ko, db) for ko, _, db in PLAYERS if goal_map.get(db, 0) + assist_map.get(db, 0) > 0][:12]
for (ka, da), (kb, db_) in itertools.combinations(pool, 2):
    r = try_fast_path(f"{ka} {kb} 비교해줘")
    if r is None:  # 같은 DB 선수를 가리키는 중복 이름 등
        continue
    rows = r["rows"]
    check(rows[0][1] == goal_map.get(da, 0) and rows[1][1] == goal_map.get(db_, 0), f"비교 골 불일치 {ka}/{kb}")
    check(rows[0][2] == assist_map.get(da, 0) and rows[1][2] == assist_map.get(db_, 0), f"비교 어시스트 불일치 {ka}/{kb}")

print("[3] 팀 상대전적 정답 대조 (CASE 문으로 다시 계산)")
team_pool = [(ko, db) for ko, _, db in TEAMS][:10]
for (ka, da), (kb, db_) in itertools.combinations(team_pool, 2):
    r = try_fast_path(f"{ka} {kb} 상대전적")
    ref = conn.execute(
        "SELECT COUNT(*), "
        "SUM(CASE WHEN (home_team=:a AND home_score>away_score) OR (away_team=:a AND away_score>home_score) THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN home_score=away_score THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN home_team=:a THEN home_score ELSE away_score END), "
        "SUM(CASE WHEN home_team=:a THEN away_score ELSE home_score END) "
        "FROM matches WHERE ((home_team=:a AND away_team=:b) OR (home_team=:b AND away_team=:a)) AND home_score IS NOT NULL",
        {"a": da, "b": db_},
    ).fetchone()
    if not ref[0]:
        check(r is None, f"경기 없는 조합은 None이어야 함 {ka}/{kb}")
        continue
    c = r["card"]
    check(
        (c["total"], c["w"], c["d"], c["gf"], c["ga"]) == (ref[0], ref[1], ref[2], ref[3], ref[4]),
        f"상대전적 불일치 {ka}/{kb}: {(c['total'], c['w'], c['d'], c['gf'], c['ga'])} != {ref}",
    )
    check(c["w"] + c["d"] + c["l"] == c["total"], f"승무패 합 불일치 {ka}/{kb}")

# ---------------------------------------------------------------- 2) 기존 문항 채점
print("[4] 기존 정확도 문항 중 빠른 경로가 가로채는 것 채점")
from tests.accuracy_test import CASES, UNSEEN, judge  # noqa: E402

taken = 0
for label, cases in (("CASES", CASES), ("UNSEEN", UNSEEN)):
    for case in cases:
        q, kind, expected = case[1], case[2], case[3]
        r = try_fast_path(q)
        if r is None:
            continue
        taken += 1
        if kind != "value":
            check(False, f"{label} '{q}'는 {kind} 유형인데 빠른 경로가 처리함")
            continue
        ok, why = judge(kind, expected, r)
        print(f"  {'OK ' if ok else 'FAIL'} {q}  ({why})")
        check(ok, f"{label} '{q}' 채점 실패 {why}")
print(f"  가로챈 문항 {taken}개")

# ---------------------------------------------------------------- 3) 오인식 방지
print("[5] 추가 조건이 있으면 빠른 경로를 쓰지 않아야 함")
MUST_FALL_THROUGH = [
    "손흥민 21-22 시즌 골 몇 개야?",
    "손흥민 이번 시즌 골",
    "손흥민 작년 골 몇 개",
    "손흥민 2024년 골 몇 개야",
    "토트넘 상대로 손흥민 골 몇 개야?",
    "손흥민 홈에서 골 몇 개야?",
    "손흥민 원정 골",
    "손흥민 골이 가장 많이 나온 시간대는?",
    "손흥민 후반전 골",
    "손흥민 첫 골 언제야?",
    "손흥민 페널티 골 몇 개",
    "손흥민 경기당 골",
    "골을 가장 많이 넣은 선수",
    "프리미어리그 득점왕",
    "그럼 어시스트는?",
    "아스날 맨시티 경기 결과 보여줘",
    "아스날 맨시티 2024-25 상대전적",
    "아스날 맨시티 홈 상대전적",
    "손흥민 케인 누가 더 잘해",
    "손흥민 골",
    "손흥민 선수 골",
    "오늘 날씨 어때",
    "",
]
for q in MUST_FALL_THROUGH:
    check(try_fast_path(q) is None, f"None이어야 하는데 처리됨: '{q}'")
print(f"  {len(MUST_FALL_THROUGH)}개 확인")

print()
if fails:
    print(f"실패 {len(fails)}건")
    sys.exit(1)
print("모두 통과")
