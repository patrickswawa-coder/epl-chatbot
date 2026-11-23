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
