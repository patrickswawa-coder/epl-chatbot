"""
RAG(검색 증강 생성): DB 기록으로 답할 수 없는 질문(경기 규칙, 리그 제도, 구단 정보, 이 챗봇의 데이터)을
우리가 직접 정리한 문서(knowledge/*.md)에서 찾아, 찾은 문단만 근거로 GPT가 답하게 한다.

흐름
  1) 문서를 '## 소제목' 단위 문단으로 나눈다.
  2) 질문과 가까운 문단을 찾는다: 임베딩 유사도(의미) + 글자 겹침(키워드)을 섞은 점수.
     - 임베딩은 처음 쓸 때 문단 전체를 한 번에 만들어 메모리에 둔다 (문서가 바뀌면 다시 만든다).
     - OpenAI 키가 없거나 임베딩이 실패해도 키워드 점수만으로 동작한다.
  3) 위 문단 3개를 GPT에 주고 "이 문서에 있는 내용으로만" 답하게 한다.
     문서에 답이 없으면 GPT가 NO_ANSWER를 내고, 호출한 쪽이 기존 GPT 지식 답변(경고 표시)으로 넘어간다.
  4) 답에 나온 숫자가 찾은 문단(또는 질문)에 없으면 근거 없는 답으로 보고 쓰지 않는다.
"""
from __future__ import annotations

import hashlib
import math
import re
import threading
from pathlib import Path

import numpy as np

from database.aliases import mentioned_names

KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"
EMBEDDING_MODEL = "text-embedding-3-small"
TOP_K = 3
MIN_SCORE = 0.18        # 이보다 낮으면 관련 문서가 없다고 보고 GPT를 부르지 않는다
NO_ANSWER = "NO_ANSWER"

_lock = threading.Lock()
_index: dict = {"hash": None, "chunks": [], "vectors": None}


# ---------------------------------------------------------------- 문서 → 문단
def load_chunks(folder: Path = KNOWLEDGE_DIR) -> list[dict]:
    """knowledge/*.md를 '## 소제목' 단위 문단으로 나눈다."""
    chunks = []
    for path in sorted(folder.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        doc_title = path.stem
        m = re.search(r"^#\s+(.+)$", text, re.M)
        if m:
            doc_title = m.group(1).strip()
        for sec in re.split(r"^##\s+", text, flags=re.M)[1:]:
            title, _, body = sec.partition("\n")
            body = body.strip()
            if body:
                chunks.append({"doc": doc_title, "title": title.strip(), "text": body, "file": path.name})
    return chunks


def _bigrams(text: str) -> set[str]:
    s = re.sub(r"[^0-9a-zA-Z가-힣]", "", (text or "").lower())
    return {s[i:i + 2] for i in range(len(s) - 1)}


_STOP = _bigrams("알려줘 알려 주세요 뭐야 무엇 어떻게 설명해줘 간단히 해줘 이야 인가요 입니까 대해 무슨 있어 누구야 몇 년 언제")


def idf_weights(chunks: list[dict]) -> dict[str, float]:
    """여러 문단에 흔히 나오는 글자 묶음(예: '프리', '리그')은 덜 중요하게 본다."""
    n = len(chunks)
    df: dict[str, int] = {}
    for c in chunks:
        for g in _bigrams(c["title"] + " " + c["text"]):
            df[g] = df.get(g, 0) + 1
    return {g: math.log((n + 1) / (d + 0.5)) for g, d in df.items()}


def keyword_score(question: str, chunk: dict, idf: dict[str, float] | None = None) -> float:
    """질문과 문단의 글자 두 개 묶음(바이그램) 겹침을 IDF로 가중한 점수 (0~1). 소제목 겹침은 더 크게 친다."""
    q = _bigrams(question) - _STOP
    if not q:
        return 0.0
    idf = idf or {}
    w = {g: idf.get(g, 1.0) for g in q}
    total = sum(w.values()) or 1.0
    title = _bigrams(chunk["title"])
    body = _bigrams(chunk["text"])
    hit_title = sum(w[g] for g in q & title) / total
    hit_body = sum(w[g] for g in q & body) / total
    return min(1.0, 0.7 * hit_body + 0.8 * hit_title)


# ---------------------------------------------------------------- 임베딩
def _client():
    try:
        from text_to_sql import client
    except Exception:
        return None
    return client


def _embed(texts: list[str]) -> np.ndarray | None:
    cli = _client()
    if cli is None:
        return None
    try:
        resp = cli.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    except Exception:
        return None
    vecs = np.array([d.embedding for d in resp.data], dtype=np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
    return vecs


def _ensure_index() -> dict:
    """문단 목록과 (가능하면) 문단 임베딩을 준비한다. 문서 내용이 바뀌면 다시 만든다."""
    chunks = load_chunks()
    digest = hashlib.sha1("".join(c["title"] + c["text"] for c in chunks).encode()).hexdigest()
    with _lock:
        if _index["hash"] != digest:
            _index.update(hash=digest, chunks=chunks, vectors=None)
        if _index["vectors"] is None and chunks:
            _index["vectors"] = _embed([f"{c['doc']} - {c['title']}\n{c['text']}" for c in chunks])
        return _index


# ---------------------------------------------------------------- 검색
def retrieve(question: str, top_k: int = TOP_K, use_embeddings: bool = True) -> list[dict]:
    """질문과 가까운 문단 top_k개를 점수와 함께 돌려준다. use_embeddings=False면 키워드 점수만 쓴다."""
    idx = _ensure_index() if use_embeddings else {"chunks": load_chunks(), "vectors": None}
    chunks = idx["chunks"]
    if not chunks:
        return []
    # 별명(토트넘, 맨유 ...)을 정식 이름으로도 함께 찾는다
    query = question + " " + " ".join(ko for _, ko in mentioned_names(question))
    idf = idf_weights(chunks)
    kw = np.array([keyword_score(query, c, idf) for c in chunks], dtype=np.float32)

    vectors = idx["vectors"]
    qvec = _embed([question]) if vectors is not None else None
    if vectors is not None and qvec is not None:
        score = 0.7 * (vectors @ qvec[0]) + 0.3 * kw  # 의미 유사도 + 키워드
    else:
        score = kw

    order = np.argsort(-score)[:top_k]
    return [dict(chunks[i], score=float(score[i])) for i in order if score[i] >= MIN_SCORE]


# ---------------------------------------------------------------- 답변
SYSTEM_PROMPT = """
당신은 EPL 챗봇의 문서 기반 답변 담당입니다.
아래 [문서]에 적힌 내용만 근거로 사용자의 질문에 한국어로 답하세요.

규칙
1. [문서]에 없는 사실, 숫자, 날짜, 이름을 덧붙이지 마세요. 일반 상식으로 보충하지 마세요.
2. [문서]로 답할 수 없는 질문이면 다른 말 없이 정확히 NO_ANSWER 만 출력하세요.
3. 2~5문장으로 자연스럽게 답하세요. 목록이나 마크다운 제목은 쓰지 마세요.
4. 답 끝에 출처를 적지 마세요. 화면이 출처를 따로 보여 줍니다.
""".strip()


def _numbers(text: str) -> set[float]:
    out = set()
    for m in re.findall(r"\d[\d,]*\.?\d*", text or ""):
        try:
            out.add(float(m.replace(",", "").rstrip(".")))
        except ValueError:
            pass
    return out


def grounded(answer: str, question: str, chunks: list[dict]) -> bool:
    """답 속 숫자가 모두 찾은 문단이나 질문에 있으면 True."""
    allowed = _numbers(question)
    for c in chunks:
        allowed |= _numbers(c["title"] + " " + c["text"])
    return _numbers(answer) <= allowed


def should_try(question: str) -> bool:
    """선수에 대한 질문(문서에 선수 소개는 없다)은 문서 검색을 건너뛴다."""
    kinds = {k for k, _ in mentioned_names(question)}
    return not ("player" in kinds and "team" not in kinds)


def answer_from_docs(question: str, history: list[dict] | None = None, chat=None,
                     use_embeddings: bool = True) -> dict | None:
    """문서로 답할 수 있으면 {'answer', 'sources'}를, 아니면 None을 돌려준다."""
    if not should_try(question):
        return None
    chunks = retrieve(question, use_embeddings=use_embeddings)
    if not chunks:
        return None
    docs = "\n\n".join(f"[문서 {i + 1}] {c['doc']} - {c['title']}\n{c['text']}" for i, c in enumerate(chunks))
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages.extend(history[-4:])
    messages.append({"role": "user", "content": f"[문서]\n{docs}\n\n[질문]\n{question}"})

    if chat is None:
        cli = _client()
        if cli is None:
            return None
        from text_to_sql import OPENAI_MODEL

        def chat(msgs):
            resp = cli.chat.completions.create(model=OPENAI_MODEL, messages=msgs, temperature=0)
            return resp.choices[0].message.content or ""

    try:
        text = (chat(messages) or "").strip()
    except Exception:
        return None
    if not text or text.upper().startswith(NO_ANSWER) or NO_ANSWER in text.upper():
        return None
    if not grounded(text, question, chunks):
        return None
    return {
        "answer": text,
        "sources": [
            {"doc": c["doc"], "title": c["title"], "text": c["text"], "score": round(c["score"], 3)}
            for c in chunks
        ],
    }
