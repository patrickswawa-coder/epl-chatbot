"""
DB에 존재하는 모든 선수/팀 이름을 OpenAI 임베딩으로 변환해
database/entity_embeddings.npz 파일로 캐싱하는 1회성 스크립트입니다.

- 이미 계산된 이름은 다시 요청하지 않고 건너뜁니다 (비용 절감, 재실행 안전).
- 새로운 시즌 데이터를 수집(collect_understat.py / collect_api_football.py)한
  뒤에는 새로 추가된 선수/팀 이름을 반영하기 위해 이 스크립트를 다시 실행하세요.

사용법 (프로젝트 루트에서):
    python database/build_entity_embeddings.py
"""
import os
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

from database.db_utils import get_connection

load_dotenv()

EMBEDDING_MODEL = "text-embedding-3-small"
CACHE_PATH = Path(__file__).parent / "entity_embeddings.npz"
BATCH_SIZE = 100  # OpenAI embeddings API는 한 번에 여러 입력을 받을 수 있음


def fetch_names_from_db() -> list[tuple[str, str]]:
    """DB에서 중복 없는 (이름, 타입) 목록을 가져옵니다."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT DISTINCT player FROM match_events "
        "WHERE player IS NOT NULL AND TRIM(player) != ''"
    )
    players = [(row[0], "player") for row in cur.fetchall()]

    cur.execute(
        "SELECT DISTINCT home_team FROM matches "
        "WHERE home_team IS NOT NULL AND TRIM(home_team) != '' "
        "UNION "
        "SELECT DISTINCT away_team FROM matches "
        "WHERE away_team IS NOT NULL AND TRIM(away_team) != ''"
    )
    teams = [(row[0], "team") for row in cur.fetchall()]

    conn.close()
    return players + teams


def load_existing_cache():
    """이미 캐싱된 이름/벡터를 불러옵니다 (재실행 시 중복 계산 방지)."""
    if not CACHE_PATH.exists():
        return {}, [], [], []

    data = np.load(CACHE_PATH, allow_pickle=True)
    names = list(data["names"])
    types = list(data["types"])
    vectors = list(data["vectors"])

    existing = {(n, t): i for i, (n, t) in enumerate(zip(names, types))}
    return existing, names, types, vectors


def main():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ .env 파일에 OPENAI_API_KEY를 설정해주세요.")
        sys.exit(1)

    client = OpenAI(api_key=api_key, timeout=30.0, max_retries=0)

    all_names = fetch_names_from_db()
    print(f"DB에서 발견한 고유 이름: {len(all_names)}개")

    existing, names, types, vectors = load_existing_cache()

    to_embed = [
        (name, entity_type)
        for name, entity_type in all_names
        if (name, entity_type) not in existing
    ]

    print(
        f"새로 임베딩이 필요한 이름: {len(to_embed)}개 "
        f"(기존 캐시 {len(existing)}개 재사용)"
    )

    for i in range(0, len(to_embed), BATCH_SIZE):
        batch = to_embed[i : i + BATCH_SIZE]
        inputs = [name for name, _ in batch]

        try:
            response = client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=inputs,
            )
        except Exception as exc:
            print(f"❌ 임베딩 요청 실패 (배치 {i}~{i + len(batch)}): {exc}")
            continue

        for (name, entity_type), item in zip(batch, response.data):
            names.append(name)
            types.append(entity_type)
            vectors.append(np.array(item.embedding, dtype=np.float32))

        print(f"✅ {i + len(batch)}/{len(to_embed)} 처리 완료")
        time.sleep(0.2)  # 요청 속도 여유

    if not vectors:
        print("⚠️ 저장할 벡터가 없습니다. (이미 모든 이름이 캐싱되어 있을 수 있습니다)")
        return

    np.savez_compressed(
        CACHE_PATH,
        names=np.array(names, dtype=object),
        types=np.array(types, dtype=object),
        vectors=np.vstack(vectors).astype(np.float32),
    )

    print(f"\n🎉 임베딩 캐시 저장 완료: {CACHE_PATH} (총 {len(names)}개 이름)")


if __name__ == "__main__":
    main()