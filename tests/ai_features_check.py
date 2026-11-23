"""
AI 해설과 문서 근거 답변(RAG)을 실제 GPT로 확인한다 (OpenAI 키 필요, 호출 약 20회).

    python tests/ai_features_check.py

확인 내용
  1) 카드 4종(프로필·시즌별·비교·상대전적)의 AI 해설: 숫자 검증을 통과하는지, 해설 문장
  2) DB에 없는 질문 8개: 문서 근거 답변(rag)인지 GPT 지식 답변(gpt_fallback)인지, 답과 출처
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ai_commentary as ac  # noqa: E402
from fast_path import try_fast_path  # noqa: E402
from text_to_sql import answer_question  # noqa: E402

ok_count = total = 0
print("===== 1. AI 해설")
for q in ["손흥민 알려줘", "해리 케인 시즌별 골 수", "살라랑 케인 비교해줘", "아스날 맨시티 상대전적"]:
    card = try_fast_path(q)["card"]
    r = ac.generate_commentary(card)
    total += 1
    ok_count += r["ok"]
    print(f"\n[{'O' if r['ok'] else 'X'}] {q}")
    print("   " + (r["text"] or r["error"]))

print("\n===== 2. 문서 근거 답변 (기대: 앞 6개 rag, 뒤 2개 gpt_fallback)")
CASES = [
    ("오프사이드 규칙을 간단히 설명해줘", "rag"),
    ("토트넘의 홈구장 이름이 뭐야?", "rag"),
    ("프리미어리그에서 승점은 어떻게 계산해?", "rag"),
    ("승점이 같으면 순위는 어떻게 정해?", "rag"),
    ("에버턴 홈구장이 바뀌었어?", "rag"),
    ("이 챗봇 데이터는 어디서 가져와?", "rag"),
    ("리버풀 감독 누구야?", "gpt_fallback"),
    ("덕베가 누구야?", "gpt_fallback"),
]
for q, want in CASES:
    r = answer_question(q)
    src = r.get("answer_source")
    total += 1
    ok_count += src == want
    print(f"\n[{'O' if src == want else 'X'}] {q}  -> {src} (기대 {want})")
    print("   " + " ".join(str(r.get("answer") or r.get("error")).split())[:220])
    for s in r.get("sources") or []:
        print(f"   - 출처: {s['doc']} › {s['title']} (점수 {s['score']})")

print(f"\n===== 결과: {ok_count}/{total}")
