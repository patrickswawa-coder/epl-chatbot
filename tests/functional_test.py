"""
기능·예외·통합 테스트 (OpenAI API 키 없이 실행 가능).

GPT가 SQL을 만드는 부분만 "미리 정해 둔 SQL을 돌려주는 대역"으로 바꿔 끼우고,
그 외 입력 검증 → SQL 검증 → 의미 검사 → 재생성 → 읽기 전용 조회 → 답변 생성·검증 →
오류 코드 → 호출 제한 → 처리 기록은 실제 코드 그대로 실행한다.

실행 (프로젝트 폴더에서):
    python tests/functional_test.py
결과는 화면에 출력하고 tests/functional_report.csv 에도 저장한다.
"""
from __future__ import annotations

import csv
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("ENABLE_INSIGHT", "0")

import text_to_sql as t  # noqa: E402
import rate_limiter  # noqa: E402
import query_logger  # noqa: E402

RESULTS: list[dict] = []


def check(area: str, name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append({"영역": area, "항목": name, "결과": "통과" if ok else "실패", "내용": detail})


def expect_raises(fn, exc_type=Exception) -> tuple[bool, str]:
    try:
        fn()
    except exc_type as exc:  # noqa: BLE001
        return True, str(exc)[:80]
    return False, "예외가 발생하지 않음"


# ------------------------------------------------------------
# GPT 대역: question_to_sql 이 차례대로 정해 둔 SQL(또는 예외)을 돌려준다
# ------------------------------------------------------------
class ScriptedLLM:
    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = 0

    def __call__(self, question, history=None, force_sql=False):
        self.calls += 1
        step = self.steps.pop(0) if self.steps else "SELECT 1"
        if isinstance(step, Exception):
            raise step
        return step


def run_pipeline(question: str, *steps, fallback=None):
    llm = ScriptedLLM(*steps)
    orig_q2s, orig_fb = t.question_to_sql, t.generate_gpt_fallback_answer
    t.question_to_sql = llm
    t.generate_gpt_fallback_answer = lambda q, h=None: fallback
    try:
        started = time.monotonic()
        result = t.answer_question(question)
        result["_ms"] = (time.monotonic() - started) * 1000
    finally:
        t.question_to_sql, t.generate_gpt_fallback_answer = orig_q2s, orig_fb
    return result, llm.calls


# ============================================================
# 1. 입력 검증 (E01)
# ============================================================
A = "1. 입력 검증"
for q, expect in [
    ("", "E01"), ("    ", "E01"), ("가" * 201, "E01"), ("ㅋㅋㅋㅋㅋ", "E01"), ("?!?!~~", "E01"),
    ("손흥민\x00골", "E01"), ("손흥민 골 몇 개야?", None), ("가" * 200, None),
]:
    got = t.validate_question(q)
    label = repr(q) if len(q) < 20 else f"{len(q)}자 입력"
    check(A, f"{label} → {expect or '정상'}", got == expect, f"결과={got}")

# ============================================================
# 2. SQL 안전 검증
# ============================================================
A = "2. SQL 안전 검증"
for sql, why in [
    ("DROP TABLE matches", "DROP 차단"),
    ("DELETE FROM matches", "DELETE 차단"),
    ("SELECT 1; DROP TABLE matches", "여러 문장 차단"),
    ("SELECT * FROM matches -- 주석", "주석 우회 차단"),
    ("PRAGMA table_info(matches)", "PRAGMA 차단"),
    ("SELECT * FROM sqlite_master", "허용 외 테이블 차단"),
    ("SELECT * FROM users", "없는 테이블 차단"),
]:
    ok, msg = expect_raises(lambda s=sql: t._validate_sql(s), ValueError)
    check(A, why, ok, msg)
ok = t._validate_sql("SELECT home_team FROM matches") == "SELECT home_team FROM matches"
check(A, "정상 SELECT 통과", ok)
check(A, "목록 조회에 LIMIT 20 자동 추가", t._add_default_limit("SELECT * FROM matches").endswith("LIMIT 20"))
check(A, "집계 조회에는 LIMIT 미추가", "LIMIT" not in t._add_default_limit("SELECT COUNT(*) FROM matches"))

# ============================================================
# 3. DB 조회 (읽기 전용, 5초 제한)
# ============================================================
A = "3. DB 조회"
cols, rows = t.run_sql("SELECT COUNT(*) FROM matches WHERE home_score IS NOT NULL")
check(A, "정상 조회", rows and rows[0][0] > 4000, f"치른 경기 {rows[0][0]}")
ok, msg = expect_raises(lambda: t._open_readonly_connection().execute("DELETE FROM matches"))
check(A, "읽기 전용 연결에서 쓰기 시도 차단", ok and "readonly" in msg.lower(), msg)
started = time.monotonic()
ok, msg = expect_raises(
    lambda: t.run_sql("SELECT COUNT(*) FROM match_events a, match_events b, match_events c"), t.QueryTimeout)
check(A, "오래 걸리는 조회 5초에 중단(E06)", ok, f"{time.monotonic() - started:.1f}초 후 중단")

# ============================================================
# 4. SQL 의미 검사 (문법은 맞지만 뜻이 틀린 SQL)
# ============================================================
A = "4. SQL 의미 검사"
chelsea_bad = ("SELECT SUM(home_score) AS goal_count FROM matches WHERE season = '2122' AND home_team = 'Chelsea' "
               "UNION ALL SELECT SUM(away_score) AS goal_count FROM matches WHERE season = '2122' AND away_team = 'Chelsea'")
chelsea_good = ("SELECT SUM(CASE WHEN home_team = 'Chelsea' THEN home_score ELSE away_score END) AS goal_count "
                "FROM matches WHERE season = '2122' AND (home_team = 'Chelsea' OR away_team = 'Chelsea') "
                "AND home_score IS NOT NULL")
cases = [
    ("2021-22 시즌 첼시가 넣은 총 골 수는?", chelsea_bad, True, "팀 총 골을 UNION으로 나눔 → 거부"),
    ("2021-22 시즌 첼시가 넣은 총 골 수는?", chelsea_good, False, "팀 총 골 한 줄 계산 → 통과"),
    ("2015-16 시즌 레스터가 이긴 경기는?",
     "SELECT COUNT(*) FROM matches WHERE season = '1516' AND home_team = 'Leicester' AND home_score > away_score "
     "OR away_team = 'Leicester' AND away_score > home_score", True, "AND/OR 괄호 누락 → 거부"),
    ("2020-21 시즌 손흥민 골 수", "SELECT COUNT(*) FROM match_events WHERE player = 'Son Heung-Min' "
     "AND match_id IN (SELECT match_id FROM matches WHERE season = '2121')", True, "시즌 코드 불일치 → 거부"),
    ("손흥민 득점 수", "SELECT COUNT(*) FROM match_events WHERE player = 'Son Heung-Min' AND event_type = 'goal' "
     "AND match_id IN (SELECT match_id FROM matches WHERE season = '2627')", True, "기간 없는 질문에 시즌 조건 → 거부"),
    ("아스날 경기 결과 보여줘", "SELECT date, home_team, away_team, home_score, away_score FROM matches "
     "WHERE (home_team = 'Arsenal' OR away_team = 'Arsenal') ORDER BY date DESC LIMIT 20", True,
     "예정 경기 포함 가능 → 거부"),
    ("어시스트 가장 많이 한 선수", "SELECT player, COUNT(*) AS assist_count FROM match_events "
     "WHERE assist_player IS NOT NULL GROUP BY player ORDER BY assist_count DESC LIMIT 1", True,
     "어시스트 순위를 득점자 기준으로 묶음 → 거부"),
]
for q, sql, should_reject, name in cases:
    issue = t.check_sql_semantics(q, sql)
    check(A, name, bool(issue) == should_reject, (issue or "문제 없음")[:80])

# ============================================================
# 5. 답변 생성·검증 (GPT 없이 만드는 한 줄 답변, 숫자 대조)
# ============================================================
A = "5. 답변 생성·검증"
simple = [
    ("2017-18 시즌 모하메드 살라는 몇 골 넣었어?", "goal_count", 32, "2017-18 시즌 모하메드 살라의 득점은 32골입니다."),
    ("아스널이 2023-24 시즌 홈에서 이긴 경기는 몇 번이야?", "win_count", 15,
     "2023-24 시즌 아스널의 홈 승리 경기는 15경기입니다."),
    ("리버풀이 2019-20 시즌에 진 경기는 몇 번이야?", "loss_count", 3, "2019-20 시즌 리버풀의 패배 경기는 3경기입니다."),
    ("2016-17 시즌 토트넘이 무승부한 경기는 몇 번이야?", "draw_count", 8,
     "2016-17 시즌 토트넘의 무승부 경기는 8경기입니다."),
    ("2014-15 시즌 EPL은 총 몇 경기야?", "total_matches", 380, "2014-15 시즌 전체 경기 수는 380경기입니다."),
    ("2024-25 시즌 EPL 전체 득점 수(스코어 합계)는?", "total_score", 1115,
     "2024-25 시즌 전체 득점 합계는 1,115골입니다."),
    ("2021-22 시즌 첼시가 넣은 총 골 수는?", "goal_count", 76, "2021-22 시즌 첼시의 득점은 76골입니다."),
    ("맨유와 맨시티의 2018-19 시즌 맞대결 경기는 몇 번 있었어?", "match_count", 2,
     "2018-19 시즌 맨체스터 유나이티드와 맨체스터 시티의 맞대결은 2경기입니다."),
    ("아스날 첼시 경기 몇 번 했어?", "match_count", 24, "아스널과 첼시의 맞대결은 24경기입니다."),
]
for q, col, val, want in simple:
    got = t._format_simple_result(q, [col], [(val,)])
    check(A, f"한 줄 답변: {want}", got == want, f"결과={got}")
    check(A, f"숫자 대조 통과: {val}", t.verify_answer(q, [col], [(val,)], got), "")
check(A, "답변에 없는 숫자(130골) 섞이면 거부",
      not t.verify_answer("손흥민 골 수", ["goal_count"], [(127,)], "손흥민은 130골을 넣었습니다."))
check(A, "'17-18 시즌' 질문에 '2017-18 시즌' 답변 허용",
      t.verify_answer("17-18 시즌 살라 골", ["goal_count"], [(32,)], "2017-18 시즌 모하메드 살라의 득점은 32골입니다."))
check(A, "무엇을 센 값인지 모르면 열 이름 대신 GPT 요약으로 넘김",
      t._format_simple_result("이거 몇 개야?", ["xyz"], [(5,)]) is None)

# ============================================================
# 6. 빠른 경로 (기존 테스트 재실행)
# ============================================================
A = "6. 빠른 경로"
proc = subprocess.run([sys.executable, "tests/fast_path_test.py"], capture_output=True, text=True, cwd=ROOT)
tail = [line for line in proc.stdout.strip().splitlines() if line.strip()][-2:]
check(A, "fast_path_test.py 전체", proc.returncode == 0 and "모두 통과" in proc.stdout, " / ".join(tail))

# ============================================================
# 7. 호출 제한 (E08)
# ============================================================
A = "7. 호출 제한"
sid = f"test-{time.time()}"
first5 = [rate_limiter.check_and_count(sid) for _ in range(5)]
check(A, "같은 사용자 1분 안 5회까지 허용", all(first5))
check(A, "6번째 요청 차단(E08)", rate_limiter.check_and_count(sid) is False)
check(A, "다른 사용자는 영향 없음", rate_limiter.check_and_count(sid + "-other") is True)

# ============================================================
# 8. 처리 기록
# ============================================================
A = "8. 처리 기록"
orig_db = query_logger.LOG_DB
with tempfile.TemporaryDirectory() as tmp:
    query_logger.LOG_DB = Path(tmp) / "log.db"
    query_logger.log_query("s1", "손흥민 골 수", {"sql": "SELECT 1", "answer_source": "db", "rows": [[127]],
                                              "answer": "127골"}, 12.3)
    query_logger.log_query("s1", "ㅋㅋ", {"error": "[E01]", "error_code": "E01"}, 1)
    cols, logs = query_logger.read_logs()
    rec = [dict(zip(cols, r)) for r in logs]
    check(A, "정상 질문·오류 질문 모두 기록", len(rec) == 2, f"{len(rec)}건")
    check(A, "오류 코드·행 수·응답 시간 저장", rec[0]["error_code"] == "E01" and rec[1]["row_count"] == 1
          and rec[1]["latency_ms"] == 12, "")
    query_logger.LOG_DB = Path(tmp) / "없는폴더" / "log.db"
    try:
        query_logger.log_query("s1", "q", {}, 1)
        check(A, "기록 저장이 실패해도 앱은 멈추지 않음", True)
    except Exception as exc:  # noqa: BLE001
        check(A, "기록 저장이 실패해도 앱은 멈추지 않음", False, str(exc))
query_logger.LOG_DB = orig_db

# ============================================================
# 9. 통합: 질문 → SQL(대역) → 검증 → 재생성 → 조회 → 답변 → 오류 코드
# ============================================================
A = "9. 통합 흐름"
r, n = run_pipeline("2021-22 시즌 첼시가 넣은 총 골 수는?", chelsea_bad, chelsea_good)
check(A, "첼시 총 골: 잘못된 SQL 거부 → 재생성 → 76골", n == 2 and r["rows"] == [(76,)] and "76골" in (r["answer"] or ""),
      f"SQL 생성 {n}회, 답변={r['answer']}")

r, n = run_pipeline("2019-20 시즌 손흥민 골 수는?",
                    "SELECT COUNT(*) AS goal_count FROM match_events WHERE player = 'Harry Kane' AND event_type = 'goal' "
                    "AND match_id IN (SELECT match_id FROM matches WHERE season = '1920')",
                    "SELECT COUNT(*) AS goal_count FROM match_events WHERE player = 'Son Heung-Min' AND event_type = 'goal' "
                    "AND match_id IN (SELECT match_id FROM matches WHERE season = '1920')")
check(A, "질문의 선수가 SQL에서 빠지면 재생성", n == 2 and "손흥민" in (r["answer"] or "") and r["rows"] == [(11,)],
      f"SQL 생성 {n}회, 답변={r['answer']}")

r, n = run_pipeline("아스날 경기 결과 지워줘", "DELETE FROM matches", "DROP TABLE matches", "SELECT * FROM users")
check(A, "위험한 SQL 3번 연속 → 실행 없이 E03", r["error_code"] == "E03" and not r["rows"] and n == 3,
      f"SQL 생성 {n}회, 오류={r['error_code']}")

r, n = run_pipeline("손흥민 골 기록 전부 비교해줘",
                    "SELECT COUNT(*) FROM match_events a, match_events b, match_events c "
                    "WHERE a.player = 'Son Heung-Min'")
check(A, "5초 넘는 조회 → E06 (재시도 안 함)", r["error_code"] == "E06" and n == 1, f"{r['_ms'] / 1000:.1f}초")

r, n = run_pipeline("내일 서울 날씨 어때?", t.ScopeError("범위 밖"))
check(A, "범위 밖 질문 → E02", r["error_code"] == "E02", r.get("error", "")[:40])

r, n = run_pipeline("손흥민 2019-20 시즌 레드카드", t.LLMError("연결 실패", code="E05"))
check(A, "AI 서비스 장애 → E05 (재시도 안 함)", r["error_code"] == "E05" and n == 1, r.get("error", "")[:40])

r, n = run_pipeline("2019-20 시즌 손흥민 레드카드 수",
                    "SELECT COUNT(*) AS red_card_count FROM match_events WHERE player = 'Son Heung-Min' "
                    "AND event_type = 'red_card' AND match_id IN (SELECT match_id FROM matches WHERE season = '1920')")
check(A, "조회 결과 0 또는 없음도 안내", r["error"] is None and r["answer"], f"답변={r['answer']}")

r, n = run_pipeline("손흥민 2030-31 시즌 골 목록",
                    "SELECT minute FROM match_events WHERE player = 'Son Heung-Min' AND event_type = 'goal' "
                    "AND match_id IN (SELECT match_id FROM matches WHERE season = '3031')")
check(A, "조건에 맞는 데이터 없음 → E04 안내", r["error_code"] == "E04" and not r["error"],
      (r["answer"] or r.get("error") or "")[:40])

r, n = run_pipeline("손흥민 프로필 보여줘")
check(A, "빠른 경로 질문은 GPT(대역)를 부르지 않음", n == 0 and r.get("card"), f"GPT 호출 {n}회, {r['_ms']:.0f}ms")

r, n = run_pipeline("어떤 질문이든 실패", "SELECT * FROM users", "SELECT * FROM users", "SELECT * FROM users",
                    fallback="일반 지식 답변")
check(A, "SQL 실패 시 경고 붙은 지식 답변으로 대체", r["answer_source"] == "gpt_fallback" and r["error_code"] == "E03", "")

# ============================================================
# 10. 일관성 (같은 질문 → 같은 답)
# ============================================================
A = "10. 일관성"
answers = {t.answer_question("살라 골 몇 개야?")["answer"] for _ in range(5)}
check(A, "빠른 경로: 같은 질문 5번 → 답 1가지", len(answers) == 1, list(answers)[0][:40])
answers = {run_pipeline("2021-22 시즌 첼시가 넣은 총 골 수는?", chelsea_good)[0]["answer"] for _ in range(5)}
check(A, "같은 SQL이면 답변 문장도 동일 (5번)", len(answers) == 1, list(answers)[0][:40])
answers = {run_pipeline("쏘니 골 몇 개야?")[0]["answer"] for _ in range(3)} | \
          {run_pipeline("손흥민 골 몇 개야?")[0]["answer"] for _ in range(3)}
check(A, "별명(쏘니)과 본명(손흥민) → 같은 답", len(answers) == 1, list(answers)[0][:40])

# ============================================================
# 11. 과거 시즌 경기 결과 (2000-01 ~ 2013-14)
# ============================================================
A = "11. 과거 시즌"
from database.aliases import mentioned_names  # noqa: E402

cols, rows = t.run_sql("SELECT COUNT(*), COUNT(DISTINCT season) FROM matches WHERE season < '1415'")
check(A, "2000-01~2013-14 경기 결과 14시즌 5,320경기", rows[0] == (5320, 14), f"{rows[0]}")
arsenal = ("SELECT SUM(CASE WHEN (home_team = 'Arsenal' AND home_score > away_score) OR (away_team = 'Arsenal' "
           "AND away_score > home_score) THEN 1 ELSE 0 END) AS win_count, "
           "SUM(CASE WHEN home_score = away_score THEN 1 ELSE 0 END) AS draw_count, "
           "SUM(CASE WHEN (home_team = 'Arsenal' AND home_score < away_score) OR (away_team = 'Arsenal' "
           "AND away_score < home_score) THEN 1 ELSE 0 END) AS loss_count FROM matches WHERE season = '0304' "
           "AND (home_team = 'Arsenal' OR away_team = 'Arsenal') AND home_score IS NOT NULL")
cols, rows = t.run_sql(arsenal)
check(A, "실제 기록과 일치: 아스널 2003-04 무패(26승 12무 0패)", rows[0] == (26, 12, 0), f"{rows[0]}")
check(A, "옛 시즌이 섞여도 '최신 시즌'은 2026-27", t.latest_season_code() == "2627", t.latest_season_code() or "")
for q, expect in [("2005-06 시즌 램파드 골 수", True), ("2003-04 시즌 득점왕은?", True), ("2001-02 시즌 앙리 어시스트", True),
                  ("2003-04 시즌 아스널 승리 경기 수", False), ("2005-06 시즌 첼시 골 수", False),
                  ("2008-09 시즌 총 골 수", False), ("손흥민 2019-20 시즌 골", False)]:
    got = bool(t.pre_event_season_note(q))
    check(A, f"'{q}' → {'선수 기록 없음 안내' if expect else '정상 조회'}", got == expect, "")
issue = t.check_sql_semantics("2005-06 시즌 가장 많은 골을 넣은 팀은?",
                              "SELECT team, COUNT(*) AS goal_count FROM match_events WHERE match_id IN "
                              "(SELECT match_id FROM matches WHERE season = '0506') GROUP BY team ORDER BY goal_count DESC LIMIT 1")
check(A, "옛 시즌에 골 이벤트 표 사용 → 거부(경기 스코어로 다시 계산)", bool(issue), (issue or "")[:60])
r, n = run_pipeline("2003-04 시즌 아스널 승리 경기 수",
                    "SELECT COUNT(*) AS win_count FROM matches WHERE season = '0304' AND ((home_team = 'Arsenal' "
                    "AND home_score > away_score) OR (away_team = 'Arsenal' AND away_score > home_score))")
check(A, "옛 시즌 경기 결과 질문 → 정답(26승)", "26경기" in (r["answer"] or ""), r["answer"] or "")
r, n = run_pipeline("2005-06 시즌 램파드 골 수")
check(A, "옛 시즌 선수 기록 질문 → GPT 호출 없이 안내", n == 0 and r["error_code"] == "E04", (r["answer"] or "")[:50])
r, n = run_pipeline("아스날 맨시티 상대전적")
check(A, "상대전적 카드가 2000-01 시즌부터 집계", "2000-01" in (r["answer"] or "") and r["card"]["total"] > 24,
      f"{r['card']['total']}경기")
check(A, "'맨체스터 더비'의 '더비'를 더비 카운티로 오인하지 않음", mentioned_names("맨체스터 더비 결과") == [], "")
check(A, "옛 팀 별명 인식(볼튼 → 볼턴 원더러스)", mentioned_names("볼튼 2006-07 승리") == [("team", "볼턴 원더러스")], "")

# ============================================================
# 12. 진행 중 경기 (실시간 스코어)
# ============================================================
A = "12. 실시간 경기"
import live_scores as live  # noqa: E402

SAMPLE = {"errors": [], "response": [
    {"league": {"id": 39}, "fixture": {"status": {"short": "2H", "elapsed": 67}},
     "teams": {"home": {"name": "Arsenal"}, "away": {"name": "Newcastle"}}, "goals": {"home": 2, "away": 1}},
    {"league": {"id": 39}, "fixture": {"status": {"short": "HT", "elapsed": 45}},
     "teams": {"home": {"name": "Wolves"}, "away": {"name": "Chelsea"}}, "goals": {"home": 0, "away": 0}},
    {"league": {"id": 262}, "fixture": {"status": {"short": "1H", "elapsed": 12}},
     "teams": {"home": {"name": "Club Queretaro"}, "away": {"name": "Necaxa"}}, "goals": {"home": 0, "away": 0}},
]}
parsed = live.parse_live(SAMPLE)
check(A, "여러 리그 중 EPL 경기만 골라냄", len(parsed) == 2, f"{len(parsed)}경기")
check(A, "API 팀 이름을 DB 이름으로 맞춤(Newcastle → Newcastle United)", parsed[0]["away"] == "Newcastle United"
      and parsed[1]["home"] == "Wolverhampton Wanderers", "")
html = live.live_html(parsed, __import__("views").ko_name)
check(A, "카드에 한글 팀명·시간·스코어 표시", all(x in html for x in ("아스널", "뉴캐슬", "67'", "2 - 1", ">HT<")), "")

orig_key = os.environ.pop("API_FOOTBALL_KEY", None)
live._state.update(matches=[], fetched=0.0, calls=0, error=None)
check(A, "키가 없으면 요청 없이 빈 목록(앱은 그대로)", live.get_live_matches(fetch=lambda: SAMPLE) == [] and live._state["calls"] == 0)
os.environ["API_FOOTBALL_KEY"] = "test-key"
calls = []
fake = lambda: (calls.append(1), SAMPLE)[1]  # noqa: E731
t0 = 1_000_000.0
live.get_live_matches(now=t0, fetch=fake)
live.get_live_matches(now=t0 + 60, fetch=fake)
check(A, "경기 중에는 3분 안에 다시 요청하지 않음", len(calls) == 1, f"요청 {len(calls)}회")
live.get_live_matches(now=t0 + 200, fetch=fake)
check(A, "3분이 지나면 새로 요청", len(calls) == 2, f"요청 {len(calls)}회")
live._state.update(matches=[], fetched=t0, calls=0)
live.get_live_matches(now=t0 + 600, fetch=fake)
check(A, "진행 중 경기가 없으면 30분 간격", len(calls) == 2, f"요청 {len(calls)}회")
live._state.update(matches=[], fetched=0.0, calls=live.DAILY_BUDGET)
before = len(calls)
live.get_live_matches(now=t0 + 99999, fetch=fake)
check(A, "하루 90회를 넘으면 더 요청하지 않음(무료 한도 보호)", len(calls) == before, "")
live._state.update(matches=parsed, fetched=0.0, calls=0)
kept = live.get_live_matches(now=t0, fetch=lambda: {"errors": {"requests": "limit"}, "response": []})
check(A, "API 오류가 나도 앱은 계속 동작(직전 결과 유지)", kept == parsed and live._state["error"], live._state["error"] or "")
os.environ["API_FOOTBALL_KEY"] = "test-key"
st_ok = live.check_key(fetch=lambda: {"errors": [], "response": {"subscription": {"plan": "Free"},
                                                                 "requests": {"current": 7, "limit_day": 100}}})
st_bad = live.check_key(fetch=lambda: {"errors": {"token": "Error/Missing application key"}, "response": []})
check(A, "관리자 키 확인: 정상 키면 사용량 표시", st_ok["ok"] and (st_ok["used"], st_ok["limit"]) == (7, 100), st_ok["message"])
check(A, "관리자 키 확인: 틀린 키면 오류 문구(키 값은 노출 안 함)", not st_bad["ok"] and "키 오류" in st_bad["message"]
      and "test-key" not in str(st_bad), st_bad["message"][:40])
os.environ.pop("API_FOOTBALL_KEY", None)
st_none = live.check_key(fetch=lambda: (_ for _ in ()).throw(AssertionError("요청하면 안 됨")))
check(A, "관리자 키 확인: 키가 없으면 요청 없이 안내", not st_none["has_key"] and "설정되어 있지 않습니다" in st_none["message"])
if orig_key is None:
    os.environ.pop("API_FOOTBALL_KEY", None)
else:
    os.environ["API_FOOTBALL_KEY"] = orig_key

# ============================================================
# 13. Understat 점검 대비 (football-data.co.uk 스코어 보완)
# ============================================================
A = "13. 수집 장애 대비"
import json as _json  # noqa: E402
import sqlite3 as _sqlite3  # noqa: E402
import types as _types  # noqa: E402

sys.path.insert(0, str(ROOT / "data_collection"))
import update_current_season as ucs  # noqa: E402
from collect_history_results import parse_csv  # noqa: E402
from fill_scores_football_data import fill_scores  # noqa: E402

with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    (d / "leagues.json").write_text("<!DOCTYPE html><title>Understat.com</title>We will come back soon", encoding="utf-8")
    (d / "match_1.json").write_text('{"shots": []}', encoding="utf-8")
    (d / "match_2.json").write_bytes(b"")
    removed = ucs.clean_bad_cache(d)
    check(A, "점검 안내 페이지·빈 파일로 저장된 응답만 지움", sorted(removed) == ["leagues.json", "match_2.json"]
          and (d / "match_1.json").exists(), ", ".join(sorted(removed)))

try:
    _json.loads("<!DOCTYPE html>")
except ValueError as exc:
    reason = ucs.understat_failure_reason(exc)
check(A, "JSON 오류를 '안내 페이지를 보냄'으로 설명", "안내 페이지" in reason, reason[:40])

CSV = (
    "﻿Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG\n"
    "E0,21/08/2026,20:00,Arsenal,Coventry,3,0\n"
    "E0,01/11/2026,15:00,Man City,Newcastle,2,2\n"
    "E0,08/11/2026,15:00,Nott'm Forest,Leeds,1,0\n"
    "E0,09/11/2026,15:00,Fake FC,Leeds,1,0\n"
    "E0,22/11/2026,15:00,Chelsea,Leeds,,\n"
)
rows = parse_csv(CSV)
check(A, "CSV에서 끝난 경기만 읽고 팀 이름을 DB 표기로 바꿈",
      len(rows) == 4 and rows[1]["home"] == "Manchester City" and rows[1]["away"] == "Newcastle United"
      and rows[2]["home"] == "Nottingham Forest" and rows[0]["date"] == "2026-08-21", f"{len(rows)}경기")

mem = _sqlite3.connect(":memory:")
mem.execute("CREATE TABLE matches (match_id TEXT PRIMARY KEY, season TEXT, date TEXT, home_team TEXT, "
            "away_team TEXT, home_score INTEGER, away_score INTEGER, source TEXT)")
mem.executemany("INSERT INTO matches VALUES (?,?,?,?,?,?,?,'understat')", [
    ("u1", "2627", "2026-08-21 19:00:00", "Arsenal", "Coventry", 3, 0),
    ("u2", "2627", "2026-11-01 15:00:00", "Manchester City", "Newcastle United", None, None),
    ("u3", "2627", "2026-11-08 15:00:00", "Nottingham Forest", "Leeds", None, None),
    ("u4", "2627", "2026-11-22 15:00:00", "Chelsea", "Leeds", None, None),
])
filled, unmatched = fill_scores(mem, "2627", rows)
got = dict((m, (h, a)) for m, h, a in mem.execute("SELECT match_id, home_score, away_score FROM matches"))
check(A, "비어 있던 스코어만 채움(이미 있는 경기·예정 경기는 그대로)",
      filled == 2 and got == {"u1": (3, 0), "u2": (2, 2), "u3": (1, 0), "u4": (None, None)}, f"채움 {filled}경기")
check(A, "DB 일정에 없는 팀 이름은 따로 알려줌", unmatched == ["2026-11-09 Fake FC vs Leeds"], "; ".join(unmatched))
check(A, "다시 실행해도 중복·변경 없음", fill_scores(mem, "2627", rows)[0] == 0)
check(A, "새 행을 만들지 않음", mem.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 4)

# Understat 실패 → football-data 보완으로 넘어가는지 (실제 네트워크·DB는 건드리지 않는다)
calls = []
fake_cu = _types.ModuleType("collect_understat")
def _boom(season):
    raise _json.JSONDecodeError("Expecting value", "<html>", 0)
fake_cu.collect_season = _boom
fake_fill = _types.ModuleType("fill_scores_football_data")
fake_fill.main = lambda season: calls.append(season) or 3
saved = {k: sys.modules.get(k) for k in ("collect_understat", "fill_scores_football_data")}
orig_init, orig_clean = ucs.init_db, ucs.clean_bad_cache
sys.modules.update(collect_understat=fake_cu, fill_scores_football_data=fake_fill)
ucs.init_db, ucs.clean_bad_cache = (lambda: None), (lambda *a: [])
try:
    import contextlib as _cl
    import io as _io
    buf = _io.StringIO()
    with _cl.redirect_stdout(buf):
        code_ok = ucs.main("2627")
    out_ok = buf.getvalue()
    def _fail(season):
        raise RuntimeError("network down")
    fake_fill.main = _fail
    with _cl.redirect_stdout(_io.StringIO()):
        code_fail = ucs.main("2627")
finally:
    ucs.init_db, ucs.clean_bad_cache = orig_init, orig_clean
    for k, v in saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v
check(A, "Understat 점검 중이면 football-data 스코어 보완으로 진행", code_ok == 0 and calls == ["2627"]
      and "football-data" in out_ok, "종료 코드 0")
check(A, "보완까지 실패하면 실패로 끝남(로그에 [실패])", code_fail == 1, f"종료 코드 {code_fail}")

# ============================================================
# 14. AI 해설 (DB 기록 → GPT 해설 → 숫자 검증)
# ============================================================
A = "14. AI 해설"
import ai_commentary as ac  # noqa: E402
from fast_path import try_fast_path as _fp  # noqa: E402

cards = {k: _fp(q)["card"] for k, q in (("profile", "손흥민 알려줘"), ("seasons", "케인 시즌별 골 수"),
                                         ("compare", "손흥민이랑 케인 비교해줘"), ("h2h", "아스날 맨시티 상대전적"))}
facts = {k: ac.build_facts(c) for k, c in cards.items()}
check(A, "카드 4종(프로필·시즌별·비교·상대전적)에서 기록을 모음", all(f and f["text"] for f in facts.values()),
      ", ".join(facts))
check(A, "기록의 골 수가 빠른 경로 카드 값과 같음", "통산 골: 127" in facts["profile"]["text"]
      and "통산 골: 210" in facts["seasons"]["text"], "손흥민 127 / 케인 210")
check(A, "상대전적 기록에 승·무·패와 최근 경기 포함",
      f"승리 {cards['h2h']['w']}, 무승부 {cards['h2h']['d']}" in facts["h2h"]["text"] and "최근 맞대결" in facts["h2h"]["text"])
check(A, "해설을 지원하지 않는 결과는 건너뜀", ac.build_facts({"type": "goals"}) is None)


class FakeChat:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), 0

    def __call__(self, messages):
        self.calls += 1
        return self.replies.pop(0) if self.replies else ""


ac._cache.clear()
good = "2014-15 시즌 이후 기록 기준으로 손흥민은 통산 127골 71어시스트를 남겼습니다. 2021-22 시즌 23골이 최고 기록입니다."
fc = FakeChat(good)
r = ac.generate_commentary(cards["profile"], chat=fc)
check(A, "기록 속 숫자만 쓴 해설은 통과", r["ok"] and fc.calls == 1, r["text"][:30])
fc2 = FakeChat("x")
r2 = ac.generate_commentary(cards["profile"], chat=fc2)
check(A, "같은 기록이면 저장해 둔 해설을 다시 씀(GPT 호출 없음)", r2["ok"] and fc2.calls == 0)
ac._cache.clear()
fc = FakeChat("손흥민은 통산 130골을 넣었습니다.", good)
r = ac.generate_commentary(cards["profile"], chat=fc)
check(A, "기록에 없는 숫자(130골)가 나오면 다시 쓰게 함", r["ok"] and fc.calls == 2, f"GPT 호출 {fc.calls}회")
ac._cache.clear()
fc = FakeChat("손흥민은 통산 130골.", "손흥민은 통산 131골.")
r = ac.generate_commentary(cards["profile"], chat=fc)
check(A, "두 번 다 틀리면 해설을 보여주지 않음", not r["ok"] and ("130" in r["error"] or "131" in r["error"]), r["error"][:40])
ac._cache.clear()
fc = FakeChat("아스널과 맨체스터 시티는 2000-01 시즌 이후 50경기에서 맞붙었습니다. 아스널이 19승, 맨체스터 시티가 20승을 거뒀습니다.")
r = ac.generate_commentary(cards["h2h"], chat=fc)
check(A, "상대전적 해설도 같은 방식으로 검증", r["ok"], r["text"][:30])
_orig_default = ac._default_chat
ac._default_chat = lambda: None
ac._cache.clear()
r = ac.generate_commentary(cards["compare"])
ac._default_chat = _orig_default
check(A, "OpenAI 키가 없으면 해설 없이 안내", not r["ok"] and "키" in r["error"], r["error"])

# ============================================================
# 15. 문서 근거 답변 (RAG)
# ============================================================
A = "15. 문서 근거 답변(RAG)"
import rag  # noqa: E402

chunks = rag.load_chunks()
docs = sorted({c["doc"] for c in chunks})
check(A, "문서 4개를 문단으로 나눠 읽음", len(docs) == 4 and len(chunks) >= 40, f"{len(docs)}개 문서, {len(chunks)}개 문단")
EXPECT = [
    ("오프사이드 규칙을 간단히 설명해줘", "오프사이드"),
    ("토트넘의 홈구장 이름이 뭐야?", "토트넘 홋스퍼"),
    ("프리미어리그에서 승점은 어떻게 계산해?", "승점 계산"),
    ("승점 같으면 순위 어떻게 정해?", "승점이 같을 때 순위"),
    ("강등은 몇 팀이야?", "강등과 승격"),
    ("VAR은 언제 개입해?", "VAR"),
    ("맨유 별명이 뭐야?", "맨체스터 유나이티드"),
    ("xG가 뭐야?", "xG"),
    ("경고 누적 몇 장이면 결장해?", "경고 누적 징계"),
]
hits = [(q, rag.retrieve(q, use_embeddings=False)) for q, _ in EXPECT]
ok = all(r and r[0]["title"].startswith(t) for (q, r), (_, t) in zip(hits, EXPECT))
miss = [q for (q, r), (_, t) in zip(hits, EXPECT) if not (r and r[0]["title"].startswith(t))]
check(A, f"질문 {len(EXPECT)}개 모두 맞는 문단을 1위로 찾음(키워드 검색)", ok, ", ".join(miss) or "별명(맨유·토트넘)도 인식")
check(A, "축구와 무관한 질문은 문서를 찾지 않음", rag.retrieve("오늘 점심 뭐 먹지?", use_embeddings=False) == [])

fc = FakeChat("토트넘 홋스퍼의 홈구장은 토트넘 홋스퍼 스타디움으로, 2019년 4월에 문을 열었습니다.")
r = rag.answer_from_docs("토트넘의 홈구장 이름이 뭐야?", chat=fc, use_embeddings=False)
check(A, "찾은 문서로만 답하고 출처를 함께 돌려줌", r and "스타디움" in r["answer"] and r["sources"][0]["title"].startswith("토트넘"),
      r and r["sources"][0]["title"][:12])
fc = FakeChat("NO_ANSWER")
check(A, "문서에 답이 없으면(NO_ANSWER) 넘김 → GPT 지식 답변으로", rag.answer_from_docs("리버풀 감독 누구야?", chat=fc, use_embeddings=False) is None and fc.calls == 1)
fc = FakeChat("토트넘 홋스퍼 스타디움은 6만 2천 명이 들어갑니다. 수용 인원은 62850명입니다.")
check(A, "문서에 없는 숫자(수용 인원)를 지어내면 쓰지 않음", rag.answer_from_docs("토트넘 홈구장 몇 명 들어가?", chat=fc, use_embeddings=False) is None)
fc = FakeChat("x")
check(A, "선수 질문(덕베가 누구야?)은 문서를 찾지 않고 바로 넘김", rag.answer_from_docs("덕베가 누구야?", chat=fc, use_embeddings=False) is None and fc.calls == 0)

_orig_rag = rag.answer_from_docs
rag.answer_from_docs = lambda q, h=None: {"answer": "토트넘의 홈구장은 토트넘 홋스퍼 스타디움입니다.",
                                          "sources": [{"doc": "구단 정보", "title": "토트넘 홋스퍼", "text": "", "score": 0.5}]}
try:
    r, n = run_pipeline("토트넘의 홈구장 이름이 뭐야?", t.NotInDBError("NOT_IN_DB"), fallback="GPT 지식 답변")
finally:
    rag.answer_from_docs = _orig_rag
check(A, "DB에 없는 질문 → 문서 근거 답변(rag)이 GPT 지식 답변보다 먼저", r["answer_source"] == "rag" and r["sources"]
      and not r.get("error"), f"출처={r['answer_source']}")
rag.answer_from_docs = lambda q, h=None: None
try:
    r, n = run_pipeline("리버풀 감독 누구야?", t.NotInDBError("NOT_IN_DB"), fallback="GPT 지식 답변")
finally:
    rag.answer_from_docs = _orig_rag
check(A, "문서에도 없으면 기존처럼 GPT 지식 답변(경고 표시)", r["answer_source"] == "gpt_fallback", f"출처={r['answer_source']}")

# ============================================================
# 결과 출력·저장
# ============================================================
out = ROOT / "tests" / "functional_report.csv"
with open(out, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=["영역", "항목", "결과", "내용"])
    w.writeheader()
    w.writerows(RESULTS)

area = None
for r in RESULTS:
    if r["영역"] != area:
        area = r["영역"]
        print(f"\n[{area}]")
    mark = "O" if r["결과"] == "통과" else "X"
    print(f"  {mark} {r['항목']}" + (f"  ({r['내용']})" if r["내용"] else ""))

passed = sum(r["결과"] == "통과" for r in RESULTS)
print(f"\n총 {len(RESULTS)}개 중 {passed}개 통과 → {out.name}")
sys.exit(0 if passed == len(RESULTS) else 1)
