"""
선수/팀 이름 임베딩 기반 매칭 유틸.

기존 PLAYER_NAME_MAP / TEAM_NAME_MAP(하드코딩 매핑)은 절대 제거하지 않고,
이 모듈은 "보완" 역할만 합니다:

1. DB에 실제로 존재하는 선수/팀 이름을 미리 임베딩해서 캐싱해둡니다
   (build_entity_embeddings.py, 1회 실행 + 데이터 갱신 시 재실행)
2. 사용자 질문이 들어오면 질문 텍스트를 임베딩해서 캐싱된 이름들과
   코사인 유사도를 비교합니다.
3. 유사도가 일정 임계값(SIMILARITY_THRESHOLD) 이상인 후보만
   GPT 프롬프트에 "참고용 힌트"로 제공합니다.

⚠️ 한글 질문 ↔ 영문 DB 이름의 교차 언어 매칭이라, 같은 언어 내
   패러프레이즈보다 코사인 유사도 절대값이 낮게 나옵니다.
   SIMILARITY_THRESHOLD는 실제 질문으로 테스트하며 조정하세요.

캐시 파일이 없거나 OpenAI 호출이 실패해도 전체 챗봇이 죽지 않도록
항상 빈 리스트를 반환하며 조용히 실패합니다 (안전한 폴백).
"""
import os
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

EMBEDDING_MODEL = "text-embedding-3-small"
CACHE_PATH = Path(__file__).parent / "entity_embeddings.npz"

# 코사인 유사도 임계값. 한글-영문 교차 언어 매칭 특성상 다소 낮게 설정.
# 데모 전 반드시 실제 질문 몇 개로 값을 확인하고 필요시 조정하세요.
SIMILARITY_THRESHOLD = 0.45
TOP_K = 5

_client: OpenAI | None = None
_cache = None  # (names, types, normalized_vectors) 캐시


def _get_client() -> OpenAI | None:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        _client = OpenAI(api_key=api_key, timeout=15.0, max_retries=0)
    return _client


def _load_cache():
    global _cache
    if _cache is not None:
        return _cache

    if not CACHE_PATH.exists():
        _cache = (np.array([]), np.array([]), None)
        return _cache

    try:
        data = np.load(CACHE_PATH, allow_pickle=True)
        names = data["names"]
        types = data["types"]
        vectors = data["vectors"].astype(np.float32)

        # 코사인 유사도 계산을 내적만으로 하기 위해 미리 정규화
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1e-8
        vectors = vectors / norms

        _cache = (names, types, vectors)
    except Exception:
        _cache = (np.array([]), np.array([]), None)

    return _cache


def embed_text(text: str) -> np.ndarray | None:
    """텍스트 하나를 OpenAI 임베딩 벡터로 변환합니다. 실패 시 None."""
    client = _get_client()
    if client is None:
        return None

    try:
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text,
        )
        return np.array(response.data[0].embedding, dtype=np.float32)
    except Exception:
        return None


def resolve_entities(
    question: str,
    top_k: int = TOP_K,
    threshold: float = SIMILARITY_THRESHOLD,
) -> list[dict]:
    """
    질문 텍스트와 캐싱된 선수/팀 이름 임베딩을 비교하여
    의미적으로 가까운 후보 목록을 반환합니다.

    반환 형식: [{"name": "Heung-Min Son", "type": "player", "score": 0.51}, ...]
    캐시가 없거나 API 호출이 실패하면 빈 리스트를 반환합니다 (안전한 폴백).
    """
    if not question or not question.strip():
        return []

    names, types, vectors = _load_cache()

    if vectors is None or len(names) == 0:
        return []

    query_vec = embed_text(question)
    if query_vec is None:
        return []

    query_norm = np.linalg.norm(query_vec)
    if query_norm == 0:
        return []
    query_vec = query_vec / query_norm

    scores = vectors @ query_vec  # 이미 정규화된 벡터라 내적 = 코사인 유사도

    top_indices = np.argsort(scores)[::-1][:top_k]

    results = []
    for idx in top_indices:
        score = float(scores[idx])
        if score < threshold:
            continue
        results.append(
            {
                "name": str(names[idx]),
                "type": str(types[idx]),
                "score": round(score, 3),
            }
        )

    return results


def format_hint(candidates: list[dict]) -> str:
    """resolve_entities 결과를 GPT 프롬프트에 넣을 힌트 문자열로 변환합니다."""
    if not candidates:
        return ""

    lines = [
        "[임베딩 기반 이름 후보 - 참고용]",
        "아래는 사용자 질문과 의미적으로 유사한 DB 내 실제 선수/팀 이름 후보입니다.",
        "PLAYER_NAME_MAP/TEAM_NAME_MAP에 이미 명시된 이름이 있다면 그것을 우선하고,",
        "매핑에 없는 이름을 질문했을 때만 아래 후보를 참고해 정확한 DB 이름으로",
        "검색 조건을 만드세요. 확신이 없으면 무리해서 사용하지 마세요.",
    ]
    for c in candidates:
        label = "선수" if c["type"] == "player" else "팀"
        lines.append(f"- ({label}) {c['name']}  [유사도 {c['score']}]")

    return "\n".join(lines)