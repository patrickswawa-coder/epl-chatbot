"""
정확도 테스트: 질문 30개를 챗봇에 던지고 정답과 비교해 점수를 낸다.

실행 방법 (프로젝트 폴더에서, 가상환경을 켠 상태로):
    python tests/accuracy_test.py            # 전체 30문항 (OpenAI 호출 약 100회)
    python tests/accuracy_test.py --limit 5  # 앞 5문항만 시험
    python tests/accuracy_test.py --set unseen  # 처음 보는 질문 20개 (일반화 확인)

정답은 "손으로 쓴 기준 SQL"을 DB에 실행해 매번 새로 계산한다.
(DB가 바뀌어도 정답이 같이 따라간다.)

채점 규칙
  value   : 기준 SQL의 결과값(숫자·이름)이 챗봇의 답변 문장 또는 조회 결과 표에 들어 있으면 정답
  error   : 챗봇이 지정한 오류 코드(E01·E02 등)를 돌려주면 정답
  fallback: 오류 없이 GPT 지식 답변(gpt_fallback)으로 처리하고, 필수 단어가 들어 있으면 정답
결과는 tests/accuracy_report.csv 에 저장된다.
"""
import argparse
import csv
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from text_to_sql import answer_question  # noqa: E402

DB = ROOT / "football_history.db"


def goals(player, season=None):
    w = f"event_type='goal' AND player='{player}'"
    if season:
        w += f" AND match_id IN (SELECT match_id FROM matches WHERE season='{season}')"
    return f"SELECT COUNT(*) FROM match_events WHERE {w}"


def assists(player, season=None):
    w = f"event_type='goal' AND assist_player='{player}'"
    if season:
        w += f" AND match_id IN (SELECT match_id FROM matches WHERE season='{season}')"
    return f"SELECT COUNT(*) FROM match_events WHERE {w}"


def top_scorer(season=None):
    w = "event_type='goal'"
    if season:
        w += f" AND match_id IN (SELECT match_id FROM matches WHERE season='{season}')"
    return f"SELECT player, COUNT(*) FROM match_events WHERE {w} GROUP BY player ORDER BY COUNT(*) DESC LIMIT 1"


# (분류, 질문, 종류, 기준 SQL 또는 기대 오류코드 또는 필수 단어)
CASES = [
    # --- 선수 득점·어시스트 (이름 그대로) ---
    ("득점", "손흥민이 넣은 골의 개수는?", "value", goals("Son Heung-Min")),
    ("득점", "해리 케인은 EPL에서 몇 골을 넣었어?", "value", goals("Harry Kane")),
    ("득점", "모하메드 살라의 통산 골 수를 알려줘", "value", goals("Mohamed Salah")),
    ("득점", "엘링 홀란드의 EPL 득점 수는?", "value", goals("Erling Haaland")),
    ("어시스트", "손흥민의 어시스트 개수는?", "value", assists("Son Heung-Min")),
    ("어시스트", "케빈 데브라위너의 어시스트는 몇 개야?", "value", assists("Kevin De Bruyne")),
    # --- 별명·표기 ---
    ("별명", "쏘니 골 몇 개야?", "value", goals("Son Heung-Min")),
    ("별명", "덕배 어시스트 몇 개야?", "value", assists("Kevin De Bruyne")),
    ("별명", "홀란 골 몇 개야?", "value", goals("Erling Haaland")),
    ("별명", "브루노 페르난데스 골 수는?", "value", goals("Bruno Fernandes")),
    ("별명", "살라 어시스트는 몇 개?", "value", assists("Mohamed Salah")),
    ("별명", "사카가 넣은 골은 총 몇 개야?", "value", goals("Bukayo Saka")),
    # --- 시즌 지정 ---
    ("시즌", "2017-18 시즌 모하메드 살라는 몇 골 넣었어?", "value", goals("Mohamed Salah", "1718")),
    ("시즌", "2015-16 시즌 해리 케인의 골 수는?", "value", goals("Harry Kane", "1516")),
    ("시즌", "2022-23 시즌 엘링 홀란드는 몇 골이야?", "value", goals("Erling Haaland", "2223")),
    ("시즌", "2019-20 시즌 손흥민 골 수는?", "value", goals("Son Heung-Min", "1920")),
    # --- 순위·집계 ---
    ("순위", "EPL 통산 득점 1위 선수는 누구야?", "value", top_scorer()),
    ("순위", "2022-23 시즌 득점왕은 누구야?", "value", top_scorer("2223")),
    ("순위", "2017-18 시즌 가장 많은 골을 넣은 선수는?", "value", top_scorer("1718")),
    ("순위", "통산 어시스트가 가장 많은 선수는?",
     "value", "SELECT assist_player, COUNT(*) FROM match_events WHERE event_type='goal' AND assist_player IS NOT NULL GROUP BY assist_player ORDER BY COUNT(*) DESC LIMIT 1"),
    # --- 경기·팀 ---
    ("경기", "2014-15 시즌 EPL은 총 몇 경기야?", "value", "SELECT COUNT(*) FROM matches WHERE season='1415'"),
    ("경기", "2022-23 시즌 맨체스터 시티 홈 경기에서 몇 번 이겼어?", "value",
     "SELECT COUNT(*) FROM matches WHERE season='2223' AND home_team='Manchester City' AND home_score>away_score"),
    ("경기", "맨유와 맨시티의 2018-19 시즌 맞대결 경기는 몇 번 있었어?", "value",
     "SELECT COUNT(*) FROM matches WHERE season='1819' AND ((home_team='Manchester United' AND away_team='Manchester City') OR (home_team='Manchester City' AND away_team='Manchester United'))"),
    ("경기", "2016-17 시즌 토트넘이 무승부한 경기는 몇 번이야?", "value",
     "SELECT COUNT(*) FROM matches WHERE season='1617' AND (home_team='Tottenham' OR away_team='Tottenham') AND home_score=away_score"),
    # --- 오류 처리 ---
    ("오류처리", "ㅁㄴㅇㄹㅁㄴㅇㄹ", "error", "E01"),
    ("오류처리", "오늘 점심 뭐 먹지?", "error", "E02"),
    ("오류처리", "비트코인 가격 알려줘", "error", "E02"),
    # --- DB 밖 축구 지식 (GPT 지식 답변 + 경고 표시) ---
    ("지식답변", "덕베가 누구야?", "fallback", "데브라위너"),
    ("지식답변", "오프사이드 규칙을 간단히 설명해줘", "fallback", "오프사이드"),
    ("지식답변", "쏘니가 누구야?", "fallback", "손흥민"),
]


def team_wins(team, season, where="any"):
    home = f"(home_team='{team}' AND home_score>away_score)"
    away = f"(away_team='{team}' AND away_score>home_score)"
    cond = {"any": f"{home} OR {away}", "home": home, "away": away}[where]
    return f"SELECT COUNT(*) FROM matches WHERE season='{season}' AND ({cond})"


def team_losses(team, season, where="any"):
    home = f"(home_team='{team}' AND home_score<away_score)"
    away = f"(away_team='{team}' AND away_score<home_score)"
    cond = {"any": f"{home} OR {away}", "home": home, "away": away}[where]
    return f"SELECT COUNT(*) FROM matches WHERE season='{season}' AND ({cond})"


def team_goals(team, season):
    return (f"SELECT SUM(CASE WHEN home_team='{team}' THEN home_score ELSE away_score END) "
            f"FROM matches WHERE season='{season}' AND (home_team='{team}' OR away_team='{team}')")


# 처음 보는 질문 세트: 위 CASES를 보고 고치지 않은 새 질문으로 일반화 능력을 확인한다.
UNSEEN = [
    ("득점", "해리 케인이 2016-17 시즌에 넣은 골 수는?", "value", goals("Harry Kane", "1617")),
    ("득점", "데브라위너가 넣은 골은 몇 개야?", "value", goals("Kevin De Bruyne")),
    ("득점", "홀란이 2023-24 시즌에 넣은 골은 몇 개야?", "value", goals("Erling Haaland", "2324")),
    ("어시스트", "2020-21 시즌 손흥민의 어시스트는 몇 개야?", "value", assists("Son Heung-Min", "2021")),
    ("비교", "살라와 케인 중 통산 골이 더 많은 선수는 누구야?", "value",
     "SELECT player, COUNT(*) FROM match_events WHERE event_type='goal' AND player IN ('Mohamed Salah','Harry Kane') GROUP BY player ORDER BY COUNT(*) DESC LIMIT 1"),
    ("순위", "2016-17 시즌 득점왕은 누구야?", "value", top_scorer("1617")),
    ("순위", "2023-24 시즌에 가장 많은 골을 넣은 선수는?", "value", top_scorer("2324")),
    ("순위", "2015-16 시즌 가장 많은 골을 넣은 팀은?", "value",
     "SELECT t, SUM(g) FROM (SELECT home_team t, SUM(home_score) g FROM matches WHERE season='1516' GROUP BY 1 UNION ALL SELECT away_team, SUM(away_score) FROM matches WHERE season='1516' GROUP BY 1) GROUP BY t ORDER BY SUM(g) DESC LIMIT 1"),
    ("경기", "아스널이 2023-24 시즌 홈에서 이긴 경기는 몇 번이야?", "value", team_wins("Arsenal", "2324", "home")),
    ("경기", "리버풀이 2019-20 시즌에 진 경기는 몇 번이야?", "value", team_losses("Liverpool", "1920")),
    ("경기", "2015-16 시즌 레스터가 이긴 경기는 몇 번이야?", "value", team_wins("Leicester", "1516")),
    ("경기", "2021-22 시즌 첼시가 넣은 총 골 수는?", "value", team_goals("Chelsea", "2122")),
    ("경기", "2019-20 시즌 토트넘이 넣은 총 골 수는?", "value", team_goals("Tottenham", "1920")),
    ("경기", "맨유가 2017-18 시즌 홈에서 진 경기는 몇 번이야?", "value", team_losses("Manchester United", "1718", "home")),
    ("경기", "2024-25 시즌 EPL 전체 득점 수(스코어 합계)는?", "value",
     "SELECT SUM(home_score+away_score) FROM matches WHERE season='2425'"),
    ("경기", "에버턴과 리버풀의 통산 맞대결에서 리버풀이 이긴 횟수는?", "value",
     "SELECT COUNT(*) FROM matches WHERE (home_team='Liverpool' AND away_team='Everton' AND home_score>away_score) OR (home_team='Everton' AND away_team='Liverpool' AND away_score>home_score)"),
    ("오류처리", "내일 서울 날씨 어때?", "error", "E02"),
    ("오류처리", "   ", "error", "E01"),
    ("지식답변", "토트넘의 홈구장 이름이 뭐야?", "fallback", "스타디움"),
    ("지식답변", "프리미어리그에서 승점은 어떻게 계산해?", "fallback", "승점"),
]


def run_reference(sql):
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def flatten(result):
    parts = [str(result.get("answer") or "")]
    for row in result.get("rows") or []:
        parts.extend(str(v) for v in row)
    return " ".join(parts)


def judge(kind, expected, result):
    if kind == "value":
        ref = run_reference(expected)
        if not ref:
            return False, "기준 SQL 결과 없음"
        exps = [str(v) for v in ref[0]]  # 첫 행의 모든 값(이름과 숫자)이 답에 있어야 정답
        text = flatten(result).replace(",", "")
        # 숫자는 앞뒤에 다른 숫자가 붙지 않은 경우만 인정 (정답 8을 84로 오인하지 않도록)
        hit = all(re.search(rf"(?<![\d.]){re.escape(e)}(?![\d])", text) for e in exps)
        # DB 조회를 거치지 않은 GPT 지식 답변은 우연히 맞아도 오답 처리
        if result.get("answer_source") != "db":
            return False, f"정답={'/'.join(exps)} (DB 조회 아님: {result.get('answer_source')})"
        return hit, f"정답={'/'.join(exps)}"
    if kind == "error":
        return (result.get("error_code") == expected), f"기대={expected}"
    if kind == "fallback":
        ok = (
            not result.get("error")
            and result.get("answer_source") == "gpt_fallback"
            and expected in (result.get("answer") or "")
        )
        return ok, f"필수단어={expected}"
    return False, "알 수 없는 종류"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--set", choices=["main", "unseen"], default="main",
                    help="main=기본 30문항, unseen=처음 보는 질문 20개")
    args = ap.parse_args()

    base = UNSEEN if args.set == "unseen" else CASES
    cases = base[: args.limit] if args.limit else base
    rows_out, stats = [], {}

    for i, (cat, q, kind, expected) in enumerate(cases, 1):
        t0 = time.time()
        try:
            result = answer_question(q)
        except Exception as exc:  # 테스트는 멈추지 않고 계속 진행
            result = {"error": str(exc), "error_code": "E09"}
        ok, note = judge(kind, expected, result)
        dt = time.time() - t0
        mark = "O" if ok else "X"
        print(f"[{i:02d}] {mark} ({cat}) {q}  -> {note}  | {str(result.get('answer') or result.get('error'))[:60]!r}")
        s = stats.setdefault(cat, [0, 0])
        s[0] += int(ok)
        s[1] += 1
        rows_out.append({
            "no": i, "분류": cat, "질문": q, "정답/기대": note, "결과": mark,
            "오류코드": result.get("error_code") or "", "답변출처": result.get("answer_source") or "",
            "답변": (result.get("answer") or result.get("error") or "")[:200],
            "SQL": result.get("sql") or "", "초": round(dt, 1),
        })
        time.sleep(1)

    total_ok = sum(v[0] for v in stats.values())
    total = sum(v[1] for v in stats.values())
    print("\n===== 결과 =====")
    for cat, (a, b) in stats.items():
        print(f"{cat:6s} {a}/{b}")
    print(f"전체  {total_ok}/{total}  ({total_ok / total * 100:.1f}%)")

    out = ROOT / "tests" / ("accuracy_report_unseen.csv" if args.set == "unseen" else "accuracy_report.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)
    print(f"상세 결과: {out}")


if __name__ == "__main__":
    main()
