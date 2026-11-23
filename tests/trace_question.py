"""
질문 하나가 챗봇 안에서 어떻게 처리되는지 단계별로 보여준다 (OpenAI 키 필요).
정확도 테스트에서 틀린 문항의 원인(GPT가 만든 SQL, 검사에서 거부된 이유)을 확인할 때 쓴다.

    python tests/trace_question.py "EPL 통산 득점 1위 선수는 누구야?"
    python tests/trace_question.py "EPL 통산 득점 1위 선수는 누구야?" --repeat 3
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import text_to_sql as t  # noqa: E402


def _short(text, n=300):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n] + " ..."


def install_tracing():
    orig_sql = t.question_to_sql
    orig_check = t.check_sql_semantics
    orig_missing = t.missing_entities
    orig_run = t.run_sql
    step = {"n": 0}

    def question_to_sql(prompt, *args, **kwargs):
        step["n"] += 1
        print(f"  [GPT {step['n']}회차] 요청: {_short(prompt, 120)}")
        try:
            sql = orig_sql(prompt, *args, **kwargs)
        except Exception as exc:
            print(f"    -> GPT 응답 처리 중 예외: {type(exc).__name__}: {_short(exc)}")
            raise
        print(f"    -> SQL: {_short(sql)}")
        return sql

    def missing_entities(question, sql):
        out = orig_missing(question, sql)
        if out:
            print(f"    -> 이름 누락으로 거부: {out}")
        return out

    def check_sql_semantics(question, sql):
        out = orig_check(question, sql)
        if out:
            print(f"    -> 의미 검사에서 거부: {_short(out)}")
        return out

    def run_sql(sql):
        try:
            cols, rows = orig_run(sql)
        except Exception as exc:
            print(f"    -> 실행 오류: {type(exc).__name__}: {_short(exc)}")
            raise
        print(f"    -> 실행 결과 {len(rows)}행: {_short(rows[:3])}")
        return cols, rows

    t.question_to_sql = question_to_sql
    t.missing_entities = missing_entities
    t.check_sql_semantics = check_sql_semantics
    t.run_sql = run_sql
    return step


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--repeat", type=int, default=1)
    args = ap.parse_args()

    step = install_tracing()
    for i in range(args.repeat):
        step["n"] = 0
        print(f"\n===== {i + 1}번째 실행: {args.question}")
        r = t.answer_question(args.question)
        print(f"  결과: 출처={r.get('answer_source')} 오류코드={r.get('error_code')} 빠른경로={r.get('fast_path')}")
        print(f"  답변: {_short(r.get('answer') or r.get('error'), 200)}")


if __name__ == "__main__":
    main()
